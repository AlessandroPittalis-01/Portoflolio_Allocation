"""Stage 07 - stationary block bootstrap of the backtest returns (IPS decision 33).

Reads  : data/processed/backtest_returns_full.csv (stage 06), config/bootstrap.yaml, config/profiles.yaml
Writes : data/processed/bootstrap_summary.csv       quantiles and threshold probabilities per strategy
         data/processed/bootstrap_paired.csv        each strategy minus the reference, on the same paths
         data/processed/bootstrap_sensitivity.csv   the same summary with other block lengths
         data/processed/bootstrap_threshold_grid.csv  probability of reaching each drawdown level in 10 years (threshold calibration)

WHAT IT SAYS: how much drawdown, time under water and the gap between strategies depend on the order of the days
we have seen. WHAT IT DOES NOT SAY: nothing outside the sample can appear (no new regime), the paths keep the
historical mean return (it is not a forecast), and the choice of ETFs is not re-run on each path.

Run:  python pipeline/07_bootstrap.py
      python pipeline/07_bootstrap.py --paths 5000
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prm.backtest.bootstrap import (  # noqa: E402
    DEFAULT_BOOTSTRAP_PATH, TRADING_DAYS, load_bootstrap, paired_difference, run_bootstrap, summarise_paths, threshold_grid,
)
from prm.config import DEFAULT_PROFILES_PATH, DEFAULT_SETTINGS_PATH, load_data_settings, load_profiles  # noqa: E402


def _show_summary(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["twr_ann_p05/50/95"] = [f"{a*100:.1f} / {b*100:.1f} / {c*100:.1f}" for a, b, c in zip(df["twr_ann_p05"], df["twr_ann_p50"], df["twr_ann_p95"])]
    out["max_dd_p05/50/95"] = [f"{a*100:.1f} / {b*100:.1f} / {c*100:.1f}" for a, b, c in zip(df["max_dd_p05"], df["max_dd_p50"], df["max_dd_p95"])]
    out["underwater_yrs_p50/95"] = [f"{b:.1f} / {c:.1f}" for b, c in zip(df["underwater_years_p50"], df["underwater_years_p95"])]
    out["money_x_p05/50/95"] = [f"{a:.2f} / {b:.2f} / {c:.2f}" for a, b, c in zip(df["money_multiple_p05"], df["money_multiple_p50"], df["money_multiple_p95"])]
    for k, label in (("hit_alert", "P(dd<=alert)%"), ("hit_review", "P(dd<=review)%"), ("hit_stop", "P(dd<=stop)%"), ("loss_of_capital", "P(loss)%")):
        out[label] = (df[k] * 100).round(1)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage 07: stationary block bootstrap.")
    parser.add_argument("--settings", default=str(DEFAULT_SETTINGS_PATH))
    parser.add_argument("--profiles", default=str(DEFAULT_PROFILES_PATH))
    parser.add_argument("--bootstrap", default=str(DEFAULT_BOOTSTRAP_PATH))
    parser.add_argument("--profile", default="owner")
    parser.add_argument("--paths", type=int, default=None, help="override n_paths")
    args = parser.parse_args(argv)

    processed = Path(load_data_settings(args.settings).processed_dir)
    src = processed / "backtest_returns_full.csv"
    if not src.exists():
        print("Missing backtest_returns_full.csv. Run first:  python pipeline/06_backtest.py")
        return 1
    profiles = load_profiles(args.profiles)
    if args.profile not in profiles:
        print(f"Unknown profile '{args.profile}'. Available: {sorted(profiles)}")
        return 1
    profile = profiles[args.profile]
    cfg = load_bootstrap(args.bootstrap)
    if args.paths:
        cfg = replace(cfg, n_paths=args.paths)

    returns = pd.read_csv(src, index_col="date", parse_dates=True)
    missing = [s for s in cfg.strategies if s not in returns.columns]
    if missing:
        print(f"Strategies not found in backtest_returns_full.csv: {missing}")
        return 1
    data = returns[list(cfg.strategies)].dropna()
    if len(data) < 500:
        print(f"Only {len(data)} common days: too short for a bootstrap.")
        return 1
    horizon = int(round(cfg.horizon_years * TRADING_DAYS))
    names = list(cfg.strategies)

    def run(block: int):
        m = run_bootstrap(data, horizon, block, cfg.n_paths, cfg.contribution_every_days, profile.dd_alert,
                          profile.dd_review, profile.stop_contributing_dd, cfg.seed)
        return m, summarise_paths(m, names)

    metrics, summary = run(cfg.mean_block_days)
    paired = paired_difference(metrics, names, cfg.reference)
    sens = []
    for b in cfg.sensitivity_blocks:
        _, s = run(b)
        s.insert(0, "mean_block_days", b)
        sens.append(s.reset_index())
    grid = threshold_grid(metrics, names)
    grid.to_csv(processed / "bootstrap_threshold_grid.csv")
    summary.to_csv(processed / "bootstrap_summary.csv")
    paired.to_csv(processed / "bootstrap_paired.csv")
    if sens:
        pd.concat(sens).to_csv(processed / "bootstrap_sensitivity.csv", index=False)

    print(f"\nProfile '{args.profile}': alert {profile.dd_alert:.0%}, review {profile.dd_review:.0%}, stop {profile.stop_contributing_dd:.0%}")
    print(f"Data: {data.index.min().date()} -> {data.index.max().date()} ({len(data)} common days). "
          f"{cfg.n_paths} paths of {cfg.horizon_years:g} years, mean block {cfg.mean_block_days} days, seed {cfg.seed}, paired dates.")
    print("\nOUTCOMES ON RESAMPLED PATHS (%, time-weighted return after costs; money_x = final value / money paid in)\n")
    print(_show_summary(summary).to_string())
    print(f"\nEACH STRATEGY MINUS '{cfg.reference}' ON THE SAME PATHS (median [5%, 95%]; share of paths where the gap is positive)\n")
    for name, r in paired.iterrows():
        print(f"{name}:")
        print(f"  return  {r['twr_ann_diff_median']*100:+.1f} pp a year [{r['twr_ann_diff_p05']*100:+.1f}, {r['twr_ann_diff_p95']*100:+.1f}]"
              f"   better in {r['twr_ann_share_positive']*100:.0f}% of paths")
        print(f"  max dd  {r['max_dd_diff_median']*100:+.1f} pp [{r['max_dd_diff_p05']*100:+.1f}, {r['max_dd_diff_p95']*100:+.1f}]"
              f"   shallower in {r['max_dd_share_positive']*100:.0f}% of paths")
        print(f"  time under water {r['underwater_years_diff_median']:+.1f} years [{r['underwater_years_diff_p05']:+.1f}, "
              f"{r['underwater_years_diff_p95']:+.1f}]   shorter in {(1 - r['underwater_years_share_positive'])*100:.0f}% of paths")
    print("\nPROBABILITY THAT THE MAXIMUM DRAWDOWN OF A 10-YEAR PATH REACHES AT LEAST EACH LEVEL (%)  [for calibrating the thresholds]\n")
    shown = (grid * 100).round(1)
    shown.index = [f"{lvl * 100:.1f}%" for lvl in grid.index]
    print(shown.to_string())
    print("A threshold that almost every path crosses is a routine event, not an alert.")
    if sens:
        s = pd.concat(sens)
        print("\nROBUSTNESS to the block length (probability of drawdown at or below the review level, %)\n")
        table = s.reset_index().pivot_table(index="strategy", columns="mean_block_days", values="hit_review").mul(100).round(1)
        table[cfg.mean_block_days] = (summary["hit_review"] * 100).round(1)
        print(table.reindex(columns=sorted(table.columns)).to_string())
    print("\nREAD WITH CARE")
    print(" * It reshuffles the same history: one 2022, one COVID. A regime never seen cannot appear.")
    print(" * The paths keep the historical mean return: it measures sampling noise, it is NOT a forecast.")
    print(" * The ETF choice is not repeated on each path (the walk-forward output is resampled).")
    print(" * Use it to judge the SIZE of differences and to calibrate drawdown thresholds, not to pick the 'best' strategy.")
    print("\nWrote bootstrap_summary.csv, bootstrap_paired.csv, bootstrap_sensitivity.csv, bootstrap_threshold_grid.csv in", processed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
