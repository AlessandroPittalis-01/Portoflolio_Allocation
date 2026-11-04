"""Read ``config/backtest.yaml``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from prm.allocation.build import METHODS
from prm.config import REPO_ROOT

DEFAULT_BACKTEST_PATH = REPO_ROOT / "config" / "backtest.yaml"


@dataclass(frozen=True)
class BacktestSettings:
    min_train_days: int            # an ETF/class needs this many days of history, and so does the covariance window
    lookback_days: int | None      # None = expanding window (all the past); a number = only the last N days
    monthly_contribution_pln: float
    cost_bps: float                # paid on every purchase and sale
    methods: tuple[str, ...]


def load_backtest(path: Path | str = DEFAULT_BACKTEST_PATH) -> BacktestSettings:
    with open(path, "r", encoding="utf-8") as f:
        raw = (yaml.safe_load(f) or {}).get("backtest") or {}
    min_days = int(raw.get("min_train_days", 504))
    if min_days < 252:
        raise ValueError("min_train_days must be at least 252 (one year)")
    look = raw.get("lookback_days")
    if look is not None:
        look = int(look)
        if look < min_days:
            raise ValueError("lookback_days cannot be shorter than min_train_days")
    contribution = float(raw.get("monthly_contribution_pln", 2800))
    cost = float(raw.get("cost_bps", 10))
    if contribution <= 0 or not 0 <= cost <= 200:
        raise ValueError("monthly_contribution_pln must be > 0 and cost_bps in [0, 200]")
    methods = tuple(raw.get("methods") or METHODS)
    unknown = [m for m in methods if m not in METHODS]
    if unknown:
        raise ValueError(f"unknown methods: {unknown}")
    return BacktestSettings(min_days, look, contribution, cost, methods)
