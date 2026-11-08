"""Robustness checks of the backtest: the SAME walk-forward re-run with ONE setting changed at a time.

The variants are declared in advance (IPS decision 43) and are not chosen after seeing results:
    cost_bps          5 and 25      (base 10)
    switch_margin     0.05 and 0.15 (base 0.10)
    equity secondary share  0.10 and 0.30 (base 0.20)
The purpose is NOT to find a better setting. It is to see whether the conclusions (risk, drawdown, comparison with
the benchmark) change when a reasonable assumption changes. If they change a lot, the base result was fragile.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pandas as pd

from prm.allocation.spec import PortfolioSpec
from prm.backtest.engine import BENCHMARK_LONG, walk_forward
from prm.backtest.report import summarise
from prm.backtest.settings import BacktestSettings
from prm.backtest.simulate import simulate
from prm.config import Profile

KEY_COLUMNS = ("twr_ann", "vol_ann", "max_dd", "max_underwater_years", "turnover_ann", "costs_pln", "final_value_pln")


@dataclass(frozen=True)
class Variant:
    name: str
    cost_bps: float | None = None
    switch_margin: float | None = None
    equity_secondary_share: float | None = None


# Declared in advance. 'base' is first and must stay first.
VARIANTS: tuple[Variant, ...] = (
    Variant("base"),
    Variant("cost_5bps", cost_bps=5.0),
    Variant("cost_25bps", cost_bps=25.0),
    Variant("switch_margin_0.05", switch_margin=0.05),
    Variant("switch_margin_0.15", switch_margin=0.15),
    Variant("equity_secondary_0.10", equity_secondary_share=0.10),
    Variant("equity_secondary_0.30", equity_secondary_share=0.30),
)


def apply_variant(spec: PortfolioSpec, bt: BacktestSettings, v: Variant) -> tuple[PortfolioSpec, BacktestSettings]:
    """Copies of ``spec`` and ``bt`` with the variant's change (the inputs are frozen and are not modified)."""
    if v.cost_bps is not None:
        bt = replace(bt, cost_bps=v.cost_bps)
    if v.switch_margin is not None:
        spec = replace(spec, rules=replace(spec.rules, switch_margin=v.switch_margin))
    if v.equity_secondary_share is not None:
        if not 0 < v.equity_secondary_share < 1:
            raise ValueError("equity_secondary_share must be strictly between 0 and 1")
        spec = replace(spec, secondary_share={**spec.secondary_share, "equity": v.equity_secondary_share})
    return spec, bt


def run_variant(pln: pd.DataFrame, local: pd.DataFrame, meta: pd.DataFrame, spec: PortfolioSpec, profile: Profile,
                cov_kind: str, bt: BacktestSettings, v: Variant, strategies: tuple[str, ...]) -> pd.DataFrame:
    """Summary (one row per strategy, ``KEY_COLUMNS`` plus ``variant``) of one variant, each from its own first date."""
    spec_v, bt_v = apply_variant(spec, bt, v)
    wf = walk_forward(pln, local, meta, spec_v, profile, cov_kind, bt_v)
    rows = {}
    for name in strategies:
        sched = wf.schedules.get(name)
        if not sched:
            continue
        sim = simulate(pln, sched, bt_v.monthly_contribution_pln, bt_v.cost_bps, profile.rebalance_band_pp)
        s = summarise(sim, profile)
        rows[name] = {k: s[k] for k in KEY_COLUMNS}
    out = pd.DataFrame(rows).T
    out.index.name = "strategy"
    out.insert(0, "variant", v.name)
    return out


def spread(results: pd.DataFrame, strategy: str, column: str) -> dict[str, float]:
    """min, max and range of ``column`` for ``strategy`` across the variants (how much the number moves)."""
    x = results[results["strategy"] == strategy][column].astype(float)
    return {"min": float(x.min()), "max": float(x.max()), "range": float(x.max() - x.min())}


def excess_over_benchmark(results: pd.DataFrame, strategy: str, benchmark: str = BENCHMARK_LONG, column: str = "max_dd") -> pd.Series:
    """Per variant: ``column`` of the strategy minus the same column of the benchmark (e.g. drawdown gap)."""
    a = results[results["strategy"] == strategy].set_index("variant")[column].astype(float)
    b = results[results["strategy"] == benchmark].set_index("variant")[column].astype(float)
    return (a - b).dropna()
