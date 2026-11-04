"""Walk-forward engine: at every month-end the whole allocation is redone with the data available up to that day.

What is repeated at each date (nothing from the future is used)
* the choice of the ETFs of each class (eligibility, correlation groups, medoid, maximin);
* the covariance estimate and the weights of every method, with the volatility target and the limits.
The history of each ETF is measured AS OF the date, so a young ETF enters only after ``min_train_days`` of data.

Known remaining look-ahead (to be said in every result): stage 02 chose the winner of each category using TER,
accumulating flag and data warnings of today, and the universe file (``core`` flags) was written knowing which ETFs
exist today.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import pandas as pd

from prm.allocation.build import AllocationError, allocate
from prm.allocation.spec import PortfolioSpec
from prm.backtest.settings import BacktestSettings
from prm.config import Profile

BENCHMARK = "benchmark_60_40"


@dataclass
class WalkForward:
    schedules: dict[str, dict[pd.Timestamp, pd.Series]]
    choices: pd.DataFrame                              # per rebalance date: chosen ETFs and cash
    skipped: list[tuple[pd.Timestamp, str]] = field(default_factory=list)
    benchmark_start: pd.Timestamp | None = None


def month_ends(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """Last trading day of each calendar month present in ``index``."""
    s = pd.Series(index, index=index)
    return list(s.groupby([index.year, index.month]).max())


def history_years_asof(local: pd.DataFrame) -> pd.Series:
    """Years of history of each ETF up to the last date of ``local`` (first valid return to the end)."""
    first = local.apply(pd.Series.first_valid_index)
    end = local.index[-1]
    return pd.Series({a: ((end - f).days / 365.25 if f is not None and not pd.isna(f) else 0.0) for a, f in first.items()})


def walk_forward(pln: pd.DataFrame, local: pd.DataFrame, meta: pd.DataFrame, spec: PortfolioSpec, profile: Profile,
                 cov_kind: str, bt: BacktestSettings) -> WalkForward:
    rules = replace(spec.rules, min_history_years=bt.min_train_days / 252, min_overlap_days=bt.min_train_days)
    schedules: dict[str, dict] = {m: {} for m in bt.methods}
    schedules[BENCHMARK] = {}
    rows, skipped = [], []
    bench = [spec.benchmark_equity, spec.benchmark_bond]
    bench_start = None
    for d in month_ends(pln.index):
        p, l = pln.loc[:d], local.loc[:d]
        if bench_start is None and all(b in l.columns and l[b].count() >= bt.min_train_days for b in bench):
            bench_start = d
        m = meta.copy()
        hist = history_years_asof(l)
        m["history_years"] = hist.reindex(m.index).fillna(0.0)
        try:
            alloc = allocate(p, l, m, spec, profile, cov_kind, min_window=bt.min_train_days, rules=rules,
                             lookback_days=bt.lookback_days, methods=bt.methods)
        except AllocationError as exc:
            skipped.append((d, str(exc)))
            continue
        for method, w in alloc.weights.items():
            schedules[method][d] = w[w > 0]
        rows.append({"date": d, "risky": " ".join(alloc.risky_ids), "cash": alloc.cash_id, "n_risky": len(alloc.risky_ids),
                     "missing_classes": " ".join(alloc.missing_classes)})
        if bench_start is not None:
            schedules[BENCHMARK][d] = pd.Series({bench[0]: 0.6, bench[1]: 0.4})
    choices = pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame(columns=["risky", "cash", "n_risky", "missing_classes"])
    return WalkForward(schedules, choices, skipped, bench_start)
