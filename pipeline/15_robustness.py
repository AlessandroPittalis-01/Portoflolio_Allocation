"""Stage 15 - robustness of the backtest: the same walk-forward with one assumption changed at a time.

Reads  : the same files as stage 06 (returns_pln.csv, returns_local.csv, selection.csv, configs)
Writes : data/processed/robustness.csv    one row per (variant, strategy)

The 7 variants are fixed in src/prm/backtest/robustness.py and declared in the IPS BEFORE running (decision 43):
base, cost 5 / 25 bps, switch margin 0.05 / 0.15, equity secondary share 0.10 / 0.30.
This is a stress of the assumptions, not a search for a better setting: do NOT pick the best variant.
Run:  python pipeline/15_robustness.py        (about 7 times the run time of stage 06)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prm.allocation.build import build_meta  # noqa: E402
from prm.allocation.spec import DEFAULT_PORTFOLIO_PATH, load_portfolio  # noqa: E402
from prm.backtest.engine import BENCHMARK, BENCHMARK_LONG  # noqa: E402
from prm.backtest.robustness import VARIANTS, excess_over_benchmark, run_variant, spread  # noqa: E402
from prm.backtest.settings import DEFAULT_BACKTEST_PATH, load_backtest  # noqa: E402
from prm.config import DEFAULT_PROFILES_PATH, DEFAULT_SETTINGS_PATH, load_data_settings, load_profiles  # noqa: E402
from prm.data.universe import DEFAULT_UNIVERSE_PATH, load_universe  # noqa: E402

FOCUS = "risk_budget"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage 15: robustness of the backtest.")
    parser.add_argument("--settings", default=str(DEFAULT_SETTINGS_PATH))
    parser.add_argument("--profiles", default=str(DEFAULT_PROFILES_PATH))
    parser.add_argument("--portfolio", default=str(DEFAULT_PORTFOLIO_PATH))
    parser.add_argument("--backtest", default=str(DEFAULT_BACKTEST_PATH))
    parser.add_argument("--universe", default=str(DEFAULT_UNIVERSE_PATH))
    parser.add_argument("--profile", default="owner")
    args = parser.parse_args(argv)

    processed = Path(load_data_settings(args.settings).processed_dir)
    for name, stage in (("returns_pln.csv", "03_fx_returns"), ("returns_local.csv", "03_fx_returns"), ("selection.csv", "02_selection")):
        if not (processed / name).exists():
            print(f"Missing {name}. Run first:  python pipeline/{stage}.py")
            return 1
    profiles = load_profiles(args.profiles)
    if args.profile not in profiles:
        print(f"Unknown profile '{args.profile}'. Available: {sorted(profiles)}")
        return 1
    profile = profiles[args.profile]
    spec, bt = load_portfolio(args.portfolio), load_backtest(args.backtest)
    pln = pd.read_csv(processed / "returns_pln.csv", index_col="date", parse_dates=True)
    local = pd.read_csv(processed / "returns_local.csv", index_col="date", parse_dates=True)
    _, assets = load_universe(args.universe)
    meta = build_meta(pd.read_csv(processed / "selection.csv"), assets)
    meta = meta[meta.index.isin(pln.columns)]
    strategies = (FOCUS, "equal_weight", BENCHMARK, BENCHMARK_LONG)
    strategies = tuple(s for s in strategies if s in bt.methods or s in (BENCHMARK, BENCHMARK_LONG))

    frames = []
    for v in VARIANTS:
        print(f"running {v.name} ...", flush=True)
        frames.append(run_variant(pln, local, meta, spec, profile, spec.covariance, bt, v, strategies).reset_index())
    res = pd.concat(frames, ignore_index=True)
    res.to_csv(processed / "robustness.csv", index=False)

    show = res[res["strategy"] == FOCUS].set_index("variant").drop(columns="strategy")
    pct = ["twr_ann", "vol_ann", "max_dd", "turnover_ann"]
    show[pct] = (show[pct] * 100).round(1)
    show["costs_pln"] = show["costs_pln"].round(0)
    show["final_value_pln"] = show["final_value_pln"].round(0)
    show["max_underwater_years"] = show["max_underwater_years"].round(1)
    print(f"\nROBUSTNESS of '{FOCUS}' (profile {args.profile}; % and PLN; each variant changes ONE thing; twr = annual, not a forecast)\n")
    print(show.to_string())
    print("\nHOW MUCH THE KEY NUMBERS MOVE ACROSS THE 7 VARIANTS (max - min, in percentage points / years)\n")
    sp = pd.DataFrame({c: spread(res, FOCUS, c) for c in ("twr_ann", "vol_ann", "max_dd", "max_underwater_years", "turnover_ann")}).T
    for c in ("twr_ann", "vol_ann", "max_dd", "turnover_ann"):
        sp.loc[c] = sp.loc[c] * 100
    print(sp.round(2).to_string())
    if (res["strategy"] == BENCHMARK_LONG).any():
        gap = excess_over_benchmark(res, FOCUS, BENCHMARK_LONG, "max_dd") * 100
        print("\nMax drawdown of risk_budget minus the 60/40 (long) benchmark, in points (positive = risk_budget lost less):\n")
        print(gap.round(1).to_string())
    print("\nREAD WITH CARE")
    print(" * The 7 variants were declared before running (IPS decision 43). Do not choose the best one: that would be data snooping.")
    print(" * Conclusion to look for: do vol, drawdown and the comparison with the benchmark keep the same sign and size?")
    print(" * Same single history as stage 06: this tests assumptions, not the future.")
    print(f"\nWrote robustness.csv in {processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
