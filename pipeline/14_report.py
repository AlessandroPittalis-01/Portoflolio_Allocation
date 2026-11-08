"""Stage 14 - monitoring report: numbers of the earlier stages against the risk limits (IPS decision 42).

Reads  : data/processed/allocation_summary.csv, allocation_weights.csv, allocation_risk_shares.csv (stage 05),
         backtest_returns_full.csv (06), market_risk_var.csv (09), var_backtest.csv (10), stress_hypothetical.csv (12),
         selection.csv (02); config/limits.yaml, config/profiles.yaml, config/portfolio.yaml
Writes : data/processed/report_<profile>.md and data/processed/report_<profile>.csv

Missing inputs do not stop the report: the affected check is shown as N/A.
Run:  python pipeline/14_report.py            (profile owner, portfolio risk_budget)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prm.allocation.build import build_meta  # noqa: E402
from prm.allocation.spec import DEFAULT_PORTFOLIO_PATH, load_portfolio  # noqa: E402
from prm.config import DEFAULT_PROFILES_PATH, DEFAULT_SETTINGS_PATH, load_data_settings, load_profiles  # noqa: E402
from prm.data.universe import DEFAULT_UNIVERSE_PATH, load_universe  # noqa: E402
from prm.risk.limits import DEFAULT_LIMITS_PATH, load_limits  # noqa: E402
from prm.risk.monitor import build_checks, class_risk_gap, render_markdown  # noqa: E402


def _read(path: Path, **kw):
    return pd.read_csv(path, **kw) if path.exists() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage 14: risk monitoring report.")
    parser.add_argument("--settings", default=str(DEFAULT_SETTINGS_PATH))
    parser.add_argument("--profiles", default=str(DEFAULT_PROFILES_PATH))
    parser.add_argument("--portfolio", default=str(DEFAULT_PORTFOLIO_PATH))
    parser.add_argument("--limits", default=str(DEFAULT_LIMITS_PATH))
    parser.add_argument("--universe", default=str(DEFAULT_UNIVERSE_PATH))
    parser.add_argument("--profile", default="owner")
    parser.add_argument("--method", default="risk_budget")
    args = parser.parse_args(argv)

    processed = Path(load_data_settings(args.settings).processed_dir)
    profiles = load_profiles(args.profiles)
    if args.profile not in profiles:
        print(f"Unknown profile '{args.profile}'. Available: {sorted(profiles)}")
        return 1
    profile = profiles[args.profile]
    limits = load_limits(args.limits)
    spec = load_portfolio(args.portfolio)

    summary = _read(processed / "allocation_summary.csv")
    if summary is None or args.method not in set(summary["method"]):
        print(f"Missing allocation_summary.csv or method '{args.method}'. Run first:  python pipeline/05_allocation.py")
        return 1
    row = summary.set_index("method").loc[args.method]
    weights_all = _read(processed / "allocation_weights.csv", index_col="method")
    shares_all = _read(processed / "allocation_risk_shares.csv", index_col="method")
    weights = weights_all.loc[args.method] if weights_all is not None and args.method in weights_all.index else None

    gap = None
    sel = processed / "selection.csv"
    if shares_all is not None and args.method in shares_all.index and sel.exists():
        _, assets = load_universe(args.universe)
        meta = build_meta(pd.read_csv(sel), assets)
        classes = meta["asset_class"].to_dict()
        gap = class_risk_gap(shares_all.loc[args.method], classes, spec.class_budgets)

    var_table = _read(processed / "market_risk_var.csv")
    var_bt = _read(processed / "var_backtest.csv")
    hyp = _read(processed / "stress_hypothetical.csv")
    twr = None
    bt = _read(processed / "backtest_returns_full.csv", index_col="date", parse_dates=True)
    if bt is not None and args.method in bt.columns:
        twr = bt[args.method]
    as_of = str(bt.index.max().date()) if bt is not None else "n/a"

    checks = build_checks(limits, profile, summary_row=row, weights=weights, class_gap=gap, var_table=var_table,
                          var_backtest=var_bt, hypothetical=hyp, twr=twr)
    accepted = {k: v.accepted_exception for k, v in limits.items() if v.accepted_exception}
    md = render_markdown(checks, profile, args.method, as_of, accepted)
    (processed / f"report_{args.profile}.md").write_text(md, encoding="utf-8")
    checks.to_csv(processed / f"report_{args.profile}.csv", index=False)
    print("\n" + md)
    print(f"Wrote report_{args.profile}.md and report_{args.profile}.csv in {processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
