"""Load and validate configuration: investor profiles and data settings.

Two files are read here: ``config/profiles.yaml`` (investor profiles) and
``config/settings.yaml`` (parameters of the data stage).

Why this module exists
----------------------
The IPS (docs/IPS.md) says that every parameter used by the code must come from
the configuration, never from numbers typed inside functions. This module is the
single entry point: it reads the YAML file, checks that the numbers make sense,
and returns simple ``Profile`` objects that the rest of the code can use.

Usage
-----
>>> from prm.config import load_profiles
>>> profiles = load_profiles()           # reads config/profiles.yaml
>>> owner = profiles["owner"]
>>> owner.target_vol
0.09
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date
from pathlib import Path

import yaml

# Repository root = three levels up from this file (src/prm/config.py).
# Using a path relative to the file means the code works from any folder.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILES_PATH = REPO_ROOT / "config" / "profiles.yaml"
DEFAULT_SETTINGS_PATH = REPO_ROOT / "config" / "settings.yaml"


@dataclass(frozen=True)
class Profile:
    """One investor profile = one set of parameters (frozen: cannot be edited).

    Drawdowns are NEGATIVE numbers (-0.10 means -10%). Volatility and weights are
    plain fractions (0.07 means 7%).
    """

    name: str

    # --- Required parameters (every profile must define them) -----------------
    target_vol: float            # annual volatility target
    dd_alert: float              # drawdown that triggers a first look (never an automatic sale)
    dd_review: float             # drawdown that triggers a formal review of the IPS
    max_weight_per_etf: float    # cap on the weight of any single ETF
    equity_cap: float            # cap on the total equity weight
    rebalance_band_pp: float     # rebalance only if a weight drifts more than this
    stop_contributing_dd: float  # drawdown at which the investor says they would stop contributing

    # --- Optional parameters (only some profiles define them) -----------------
    horizon_years: int | None = None
    base_currency: str | None = None
    tax_residence: str | None = None
    monthly_contribution_eur_range: tuple[float, float] | None = None


def _validate(profile: Profile) -> None:
    """Raise ValueError with a clear message if a profile breaks an IPS rule."""
    n = profile.name  # used only to make error messages readable

    if not 0 < profile.target_vol < 1:
        raise ValueError(f"[{n}] target_vol must be between 0 and 1, got {profile.target_vol}")

    # Drawdowns must be negative numbers.
    for field_name in ("dd_alert", "dd_review", "stop_contributing_dd"):
        value = getattr(profile, field_name)
        if not -1 < value < 0:
            raise ValueError(f"[{n}] {field_name} must be negative and above -1, got {value}")

    # The review threshold is deeper (more negative) than the alert threshold.
    if profile.dd_review > profile.dd_alert:
        raise ValueError(
            f"[{n}] dd_review ({profile.dd_review}) must not be less severe than dd_alert ({profile.dd_alert})"
        )

    # Behavioural consistency rule (IPS decision #6): the formal review must trigger
    # BEFORE (or at) the drawdown where the investor says they would stop contributing.
    if profile.dd_review < profile.stop_contributing_dd:
        raise ValueError(
            f"[{n}] dd_review ({profile.dd_review}) is deeper than stop_contributing_dd "
            f"({profile.stop_contributing_dd}): the review would come too late"
        )

    if not 0 < profile.max_weight_per_etf <= 1:
        raise ValueError(f"[{n}] max_weight_per_etf must be in (0, 1], got {profile.max_weight_per_etf}")
    if not 0 <= profile.equity_cap <= 1:
        raise ValueError(f"[{n}] equity_cap must be in [0, 1], got {profile.equity_cap}")
    if not 0 < profile.rebalance_band_pp < 1:
        raise ValueError(f"[{n}] rebalance_band_pp must be in (0, 1), got {profile.rebalance_band_pp}")

    if profile.monthly_contribution_eur_range is not None:
        low, high = profile.monthly_contribution_eur_range
        if not 0 < low <= high:
            raise ValueError(f"[{n}] monthly_contribution_eur_range must satisfy 0 < low <= high")


def load_profiles(path: Path | str = DEFAULT_PROFILES_PATH) -> dict[str, Profile]:
    """Read the YAML file and return ``{profile_name: Profile}``.

    Raises
    ------
    ValueError
        If a profile has a missing field, an unknown field (usually a typo),
        or values that break the rules in ``_validate``.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict) or "profiles" not in raw:
        raise ValueError("The YAML file must contain a top-level 'profiles' key")

    allowed = {f.name for f in fields(Profile)} - {"name"}
    profiles: dict[str, Profile] = {}

    for name, params in raw["profiles"].items():
        # Unknown keys are almost always typos: fail loudly instead of ignoring them.
        unknown = set(params) - allowed
        if unknown:
            raise ValueError(f"[{name}] unknown parameters: {sorted(unknown)}")

        params = dict(params)  # copy, so we do not modify the loaded data
        if "monthly_contribution_eur_range" in params:
            params["monthly_contribution_eur_range"] = tuple(params["monthly_contribution_eur_range"])

        try:
            profile = Profile(name=name, **params)
        except TypeError as exc:  # raised when a required field is missing
            raise ValueError(f"[{name}] invalid profile definition: {exc}") from exc

        _validate(profile)
        profiles[name] = profile

    return profiles


# ---------------------------------------------------------------------------
# Data settings (stage 01 - sourcing)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DataSettings:
    """Parameters of the data stage, read from ``config/settings.yaml``."""

    start_date: str            # first day to download, ISO format (YYYY-MM-DD)
    raw_dir: Path              # where downloaded prices are cached (one CSV per symbol)
    processed_dir: Path        # where clean tables are written
    max_cache_age_days: int    # a cached file younger than this is reused
    max_daily_move: float      # quality check: flag daily moves larger than this (0.12 = 12%)
    max_gap_days: int          # quality check: flag gaps without data longer than this
    max_stale_days: int        # quality check: flag identical closes repeated this many days


def _resolve_path(value: str) -> Path:
    """Relative paths are interpreted from the repository root."""
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def load_data_settings(path: Path | str = DEFAULT_SETTINGS_PATH) -> DataSettings:
    """Read ``settings.yaml`` and return validated ``DataSettings``.

    Raises
    ------
    ValueError
        If a section or a key is missing, or a value is out of range.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    try:
        data, quality = raw["data"], raw["quality"]
        start = data["start_date"]
        # YAML turns an unquoted 2010-01-01 into a date object: accept both forms.
        start_date = start.isoformat() if isinstance(start, date) else str(start)
        settings = DataSettings(
            start_date=start_date,
            raw_dir=_resolve_path(data["raw_dir"]),
            processed_dir=_resolve_path(data["processed_dir"]),
            max_cache_age_days=int(data["max_cache_age_days"]),
            max_daily_move=float(quality["max_daily_move"]),
            max_gap_days=int(quality["max_gap_days"]),
            max_stale_days=int(quality["max_stale_days"]),
        )
    except (TypeError, KeyError) as exc:
        raise ValueError(f"settings file is incomplete or malformed: {exc!r}") from exc

    date.fromisoformat(settings.start_date)  # raises ValueError if not a valid ISO date
    if settings.max_cache_age_days < 0:
        raise ValueError("max_cache_age_days must be >= 0")
    if not 0 < settings.max_daily_move < 1:
        raise ValueError("max_daily_move must be between 0 and 1")
    if settings.max_gap_days < 1:
        raise ValueError("max_gap_days must be >= 1")
    if settings.max_stale_days < 2:
        raise ValueError("max_stale_days must be >= 2")
    return settings
