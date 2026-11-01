"""Load the ETF universe from ``config/universe_candidates.yaml``.

The YAML marks every value that is not yet confirmed with the word ``verify``.
Here ``verify`` becomes ``None``: an unknown value stays unknown, it is never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from prm.config import REPO_ROOT

DEFAULT_UNIVERSE_PATH = REPO_ROOT / "config" / "universe_candidates.yaml"

# The two groups of assets defined in the YAML file.
TIERS = ("implementable", "research_only")


@dataclass(frozen=True)
class Asset:
    """One ETF (or ETC) of the universe."""

    id: str                          # short name used everywhere in the code, e.g. "dev_equity"
    name: str
    tier: str                        # "implementable" (first shortlist) or "research_only"
    risk_driver: str
    category: str                    # what the ETF represents; several candidates can share one category
    yahoo_symbol: str | None         # confirmed Yahoo symbol, or None if still to be found
    symbols_to_try: tuple[str, ...]  # unconfirmed guesses, tested by the --probe option
    isin: str | None
    base_currency: str | None
    search_text: str | None          # text used by --find when the ISIN is not known
    use_from: str | None             # ISO date: ignore earlier rows (a documented decision, see IPS log)
    accumulating: bool | None = None  # True = reinvests income (Acc), False = pays it out (Dist), None = unknown
    ter_pct: float | None = None      # annual cost in percent (0.20 = 0.20%); None = not verified yet


def _known(value) -> str | None:
    """Return the value as text, or ``None`` if it is empty or marked ``verify``."""
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in ("", "verify", "n/a") else text


def _bool_or_none(value) -> bool | None:
    """Read an optional true/false field; anything else (empty, 'verify') means unknown."""
    return value if isinstance(value, bool) else None


def _float_or_none(value) -> float | None:
    """Read an optional number; empty or 'verify' means unknown. Negative costs are rejected."""
    text = _known(value)
    if text is None:
        return None
    number = float(text)
    if number < 0:
        raise ValueError(f"a cost cannot be negative: {value}")
    return number


def _iso_date_or_none(value) -> str | None:
    """Read an optional date from YAML (a date object or a text) and return it as 'YYYY-MM-DD'."""
    if value is None:
        return None
    text = value.isoformat() if isinstance(value, date) else str(value)
    date.fromisoformat(text)  # raises ValueError if it is not a valid ISO date
    return text


def load_universe(path: Path | str = DEFAULT_UNIVERSE_PATH) -> tuple[dict, list[Asset]]:
    """Return ``(criteria, assets)`` read from the YAML file.

    Raises
    ------
    ValueError
        If an asset has no id, name or risk driver, or two assets share an id.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    assets: list[Asset] = []
    seen: set[str] = set()

    for tier in TIERS:
        for item in raw.get(tier) or []:
            for key in ("id", "name", "risk_driver"):
                if key not in item:
                    raise ValueError(f"[{tier}] an asset is missing the field '{key}': {item}")
            if item["id"] in seen:
                raise ValueError(f"duplicate asset id: {item['id']}")
            seen.add(item["id"])

            assets.append(
                Asset(
                    id=item["id"],
                    name=item["name"],
                    tier=tier,
                    risk_driver=item["risk_driver"],
                    category=str(item.get("category") or item["risk_driver"]),
                    yahoo_symbol=_known(item.get("yahoo_symbol")),
                    symbols_to_try=tuple(str(s) for s in (item.get("yahoo_symbol_try") or [])),
                    isin=_known(item.get("isin")),
                    base_currency=_known(item.get("base_currency")),
                    search_text=_known(item.get("search")),
                    use_from=_iso_date_or_none(item.get("use_from")),
                    accumulating=_bool_or_none(item.get("accumulating")),
                    ter_pct=_float_or_none(item.get("ter_pct")),
                )
            )

    # The same Yahoo symbol on two assets means one of them is wrong (it happened once: see IPS log).
    owner: dict[str, str] = {}
    for asset in assets:
        if asset.yahoo_symbol:
            if asset.yahoo_symbol in owner:
                raise ValueError(
                    f"symbol {asset.yahoo_symbol} is assigned to both '{owner[asset.yahoo_symbol]}' and '{asset.id}'"
                )
            owner[asset.yahoo_symbol] = asset.id

    return raw.get("criteria") or {}, assets
