"""Stage 06 - walk-forward backtest with monthly contributions, a rebalancing band and costs.

Reads  : data/processed/returns_pln.csv, returns_local.csv (stage 03), selection.csv (stage 02),
         config/universe_candidates.yaml, config/portfolio.yaml, config/profiles.yaml, config/backtest.yaml
Writes : data/processed/backtest_summary_full.csv     each strategy from its own first date
         data/processed/backtest_summary_common.csv   all strategies from the first date of the 60/40 benchmark
         data/processed/backtest_returns.csv          daily time-weighted return after costs (common period)
         data/processed/backtest_choices.csv          ETFs chosen at each month-end
         data/processed/backtest_weights.csv          target weights at each month-end, per method

HOW IT WORKS
At every month-end the choice of the ETFs, the covariance and the weights are recomputed using ONLY the data up to
that day (no look-ahead in the allocation). A new ETF can be chosen only after ``min_train_days`` of history, so the
test can start early without any proxy. Contributions go to the most underweight ETFs; an ETF is sold only if it
leaves the portfolio or breaks the band (IPS section 6). Every trade pays ``cost_bps``. Taxes are not modelled.

HOW TO READ THE RESULT (important)
* The aim is to see whether the portfolio stays inside the risk limits at a reasonable cost (IPS section 7), NOT
  to beat the benchmark. One parameter set, declared in advance, run once.
* There is NO separate hold-out period: the data are too short. Do not re-run with different settings looking
  for a better result: that is data snooping.

Run:  python pipeline/06_backtest.py
      python pipeline/06_backtest.py --profile prudent --cost-bps 25
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prm.allocation.build import build_meta  # noqa: E402
from prm.allocation.spec import DEFAULT_PORTFOLIO_PATH, load_portfolio  # noqa: E402
from prm.backtest.engine import BENCHMARK, BENCHMARK_LONG, walk_forward  # noqa: E402
from prm.backtest.report import summarise  # noqa: E402
from prm.backtest.settings import DEFAULT_BACKTEST_PATH, load_backtest  # noqa: E402
from prm.backtest.simulate import simulate  # noqa: E402
from prm.config import DEFAULT_PROFILES_PATH, DEFAULT_SETTINGS_PATH, load_data_settings, load_profiles  # noqa: E402
from prm.data.universe import DEFAULT_UNIVERSE_PATH, load_universe  # noqa: E402

PCT_COLS = ("twr_ann", "irr_ann", "vol_ann", "max_dd", "es95_daily", "days_below_alert_pct", "days_below_review_pct", "turnover_ann")


def _show(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in PCT_COLS:
        out[c] = (out[c] * 100).round(1)
    for c in ("contributed_pln", "final_value_pln", "costs_pln"):
        out[c] = out[c].round(0)
    out["years"] = out["years"].round(1)
    out["max_underwater_years"] = out["max_underwater_years"].round(1)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage 06: walk-forward backtest.")
    parser.add_argument("--settings", default=str(DEFAULT_SETTINGS_PATH))
    parser.add_argument("--profiles", default=str(DEFAULT_PROFILES_PATH))
    parser.add_argument("--portfolio", default=str(DEFAULT_PORTFOLIO_PATH))
    parser.add_argument("--backtest", default=str(DEFAULT_BACKTEST_PATH))
    parser.add_argument("--universe", default=str(DEFAULT_UNIVERSE_PATH))
    parser.add_argument("--profile", default="owner")
    parser.add_argument("--cov", default="", help="sample, ewma or ledoit_wolf (default: portfolio.yaml)")
    parser.add_argument("--cost-bps", type=float, default=None, help="override cost_bps (robustness check only)")
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
    spec = load_portfolio(args.portfolio)
    bt = load_backtest(args.backtest)
    if args.cost_bps is not None:
        bt = replace(bt, cost_bps=args.cost_bps)
    cov_kind = args.cov or spec.covariance

    pln = pd.read_csv(processed / "returns_pln.csv", index_col="date", parse_dates=True)
    local = pd.read_csv(processed / "returns_local.csv", index_col="date", parse_dates=True)
    _, assets = load_universe(args.universe)
    meta = build_meta(pd.read_csv(processed / "selection.csv"), assets)
    meta = meta[meta.index.isin(pln.columns)]

    wf = walk_forward(pln, local, meta, spec, profile, cov_kind, bt)
    if not wf.schedules[bt.methods[0]]:
        print("No rebalance date was possible. Reasons (first 5):")
        for d, why in wf.skipped[:5]:
            print(f"  {d.date()}: {why}")
        return 1
    band = profile.rebalance_band_pp
    all_cols = list(pln.columns)
    strategies = [*bt.methods, *[b for b in (BENCHMARK, BENCHMARK_LONG) if wf.schedules.get(b)]]

    full, common, daily = {}, {}, {}
    for name in strategies:
        sched = wf.schedules[name]
        if not sched:
            continue
        sim = simulate(pln[all_cols], sched, bt.monthly_contribution_pln, bt.cost_bps, band)
        full[name] = summarise(sim, profile)
        if wf.benchmark_start is not None:
            sub = {d: w for d, w in sched.items() if d >= wf.benchmark_start}
            if sub:
                sim_c = simulate(pln[all_cols], sub, bt.monthly_contribution_pln, bt.cost_bps, band)
                common[name] = summarise(sim_c, profile)
                daily[name] = sim_c.twr
    full_df = pd.DataFrame(full).T
    full_df.index.name = "strategy"
    full_df.to_csv(processed / "backtest_summary_full.csv")
    if common:
        common_df = pd.DataFrame(common).T
        common_df.index.name = "strategy"
        common_df.to_csv(processed / "backtest_summary_common.csv")
        pd.DataFrame(daily).to_csv(processed / "backtest_returns.csv", index_label="date")
    wf.choices.to_csv(processed / "backtest_choices.csv")
    rows = []
    for method in bt.methods:
        for d, w in wf.schedules[method].items():
            rows += [{"date": d, "method": method, "asset": a, "weight": float(x)} for a, x in w.items()]
    wdf = pd.DataFrame(rows)
    wdf.to_csv(processed / "backtest_weights.csv", index=False)
    cls_of = meta["asset_class"].to_dict()
    wdf["asset_class"] = wdf["asset"].map(cls_of)
    class_w = wdf.groupby(["date", "method", "asset_class"])["weight"].sum().reset_index()
    class_w.to_csv(processed / "backtest_class_weights.csv", index=False)
    avg_class = (class_w.pivot_table(index=["date", "method"], columns="asset_class", values="weight", fill_value=0.0)
                 .groupby("method").mean().reindex(bt.methods))

    # ---- console ----------------------------------------------------------------------------------------------
    first, last = min(wf.schedules[bt.methods[0]]), pln.index.max()
    print(f"\nProfile '{args.profile}': target vol {profile.target_vol:.1%}, band +-{band:.0%}, drawdown alert {profile.dd_alert:.0%} / "
          f"review {profile.dd_review:.0%}")
    print(f"Walk-forward {first.date()} -> {last.date()}  |  contribution {bt.monthly_contribution_pln:.0f} PLN/month, "
          f"cost {bt.cost_bps:g} bps per trade, covariance {cov_kind}, min history {bt.min_train_days} days")
    print(f"Rebalance dates: {len(wf.schedules[bt.methods[0]])}   skipped: {len(wf.skipped)}")
    if wf.skipped:
        print(f"  first skipped: {wf.skipped[0][0].date()} ({wf.skipped[0][1]}); last skipped: {wf.skipped[-1][0].date()}")
    print("\nCHOSEN ETFs OVER TIME (each line = a change of the set)\n")
    prev = None
    for d, r in wf.choices.iterrows():
        key = (r["risky"], r["cash"])
        if key != prev:
            note = f"   [no ETF for: {r['missing_classes']}]" if r["missing_classes"] else ""
            print(f"  {d.date()}  {r['risky']}  | cash {r['cash']}{note}")
            prev = key
    changes = int((wf.choices["risky"] != wf.choices["risky"].shift()).sum() - 1)
    print(f"  -> {changes} changes of the risky set in {len(wf.choices)} months")
    print("\nAVERAGE TARGET WEIGHT BY CLASS (%, mean of the month-end targets; a class is 0 while no ETF of it is eligible)\n")
    print((avg_class * 100).round(1).to_string())
    print("\nFULL PERIOD, each strategy from its own first date (%, after costs; twr/irr = annual, not a prediction)\n")
    print(_show(full_df).to_string())
    if common:
        print(f"\nCOMMON PERIOD from {wf.benchmark_start.date()} (start of the 60/40 benchmark with the all-world ETF): fair comparison\n")
        print(_show(common_df).to_string())
    print("\nbenchmark_60_40_long = 60% world_xtrackers + 40% eur_govt_bond: same idea, older ETF, so it covers the whole period.")
    print("max_underwater_years = longest time below a previous peak (time-weighted return, so contributions do not hide it).")
    print("\nREAD WITH CARE")
    print(" * Not a performance test: one history, one regime sequence; no hold-out period is possible with this data.")
    print(" * Look-ahead left: stage 02 picked category winners with today's TER/flags; the 'core' list knows today's ETFs.")
    print(" * No taxes (accumulating ETFs defer them), no FX conversion costs on the contributions (PLN -> EUR).")
    print(" * Judge: drawdown vs thresholds, cost, turnover, stability of the choice - not the highest return.")
    print("\nWrote backtest_*.csv in", processed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
