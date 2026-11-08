"""Risk-limit framework: a limit is a rule on a number the pipeline already computes (IPS decision 42).

Status of a value against a limit with an optional lower and upper bound and an ``amber_margin``:
    RED    value outside [lower, upper]
    AMBER  inside, but closer than ``amber_margin`` to a bound
    GREEN  inside by more than the margin
    N/A    no value (the stage that produces it has not been run)

Drawdown has its own rule with three levels from the profile: alert (amber), review (red), stop (red, stop contributing).
A limit never triggers a trade: amber = look, red = formal review of the IPS.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import yaml

from prm.config import REPO_ROOT

DEFAULT_LIMITS_PATH = REPO_ROOT / "config" / "limits.yaml"
GREEN, AMBER, RED, NA = "GREEN", "AMBER", "RED", "N/A"
STATUSES = ("decided", "proposed")


class LimitsConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Limit:
    id: str
    label: str
    lower: float | None
    upper: float | None
    amber_margin: float
    status: str
    accepted_exception: str | None = None


def load_limits(path: Path | str = DEFAULT_LIMITS_PATH) -> dict[str, Limit]:
    raw = (yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}).get("limits")
    if not isinstance(raw, dict) or not raw:
        raise LimitsConfigError("limits must be a non-empty mapping")
    out = {}
    for lid, body in raw.items():
        if not isinstance(body, dict):
            raise LimitsConfigError(f"limit '{lid}' must be a mapping")
        lower, upper = body.get("lower"), body.get("upper")
        margin = body.get("amber_margin", 0.0)
        status = body.get("status")
        for name, v in (("lower", lower), ("upper", upper), ("amber_margin", margin)):
            if v is not None and (not isinstance(v, (int, float)) or isinstance(v, bool)):
                raise LimitsConfigError(f"limit '{lid}': {name} must be a number")
        if lower is not None and upper is not None and lower >= upper:
            raise LimitsConfigError(f"limit '{lid}': lower must be below upper")
        if margin < 0:
            raise LimitsConfigError(f"limit '{lid}': amber_margin must be >= 0")
        if status not in STATUSES:
            raise LimitsConfigError(f"limit '{lid}': status must be one of {STATUSES}")
        exc = body.get("accepted_exception")
        if exc is not None and not isinstance(exc, str):
            raise LimitsConfigError(f"limit '{lid}': accepted_exception must be text")
        out[str(lid)] = Limit(str(lid), str(body.get("label", lid)), lower, upper, float(margin), status, exc)
    return out


def evaluate(value: float | None, lower: float | None = None, upper: float | None = None, amber_margin: float = 0.0) -> str:
    """GREEN / AMBER / RED / N/A for ``value`` against the bounds (see module doc)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return NA
    if (lower is not None and value < lower) or (upper is not None and value > upper):
        return RED
    near_low = lower is not None and value - lower < amber_margin
    near_up = upper is not None and upper - value < amber_margin
    return AMBER if near_low or near_up else GREEN


def drawdown_status(dd: float | None, alert: float, review: float, stop: float) -> str:
    """Current drawdown (negative number) against the profile thresholds (alert > review > stop, all negative)."""
    if dd is None or (isinstance(dd, float) and math.isnan(dd)):
        return NA
    if dd <= review:
        return RED                                   # review level and below (stop included: see the text of the report)
    return AMBER if dd <= alert else GREEN


def zone_status(zone: str | None) -> str:
    """Basel traffic light of a VaR backtest -> report status."""
    return {"green": GREEN, "yellow": AMBER, "red": RED}.get(str(zone).lower(), NA)


def worst_status(statuses: list[str]) -> str:
    """Overall status: RED if any RED, else AMBER if any AMBER, else GREEN (N/A ignored; N/A if all are N/A)."""
    real = [s for s in statuses if s != NA]
    if not real:
        return NA
    return RED if RED in real else AMBER if AMBER in real else GREEN
