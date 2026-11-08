"""Stage 13 - further risk metrics of the allocated portfolio (IPS decision 39, step 5).

Reads  : data/processed/allocation_weights.csv (stage 05), returns_pln.csv, returns_local.csv (stage 03), config/risk_factors.yaml
Writes : data/processed/risk_extras_summary.csv   DaR, CDaR, Ulcer index, diversification ratio, effective risk bets, ES
         data/processed/risk_extras_assets.csv    per ETF: weight, share of volatility, share of tail loss (ES), stress correlation

* DaR / CDaR: drawdown depth exceeded 5% of the time and the average depth in that worst 5% (drawdown analogue of VaR / ES)
* Ulcer index: root-mean-square drawdown (deep AND long drawdowns)
* Diversification ratio and effective number of risk bets
* Component ES: who carries the tail loss (adds up to the portfolio ES) next to who carries the volatility
* Stress correlation: correlation of each ETF with the equity market on the worst 10% market days, corrected for selection
  (Forbes-Rigobon); 'change' above 0 means the diversification weakens in stress

HOW TO READ THE RESULT
* Historical and in-sample. The tail shares rest on about 5% of the days.
* A tail share larger than the volatility share = the asset is riskier in bad times than its volatility says.
* The corrected correlation undoes only the selection effect; it is evidence of a change, not a forecast.

Run:  python pipeline/13_risk_extras.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prm.config import DEFAULT_SETTINGS_PATH, load_data_settings  # noqa: E402
from prm.risk.contributions import risk_contributions  # noqa: E402
from prm.risk.covariance import ledoit_wolf  # noqa: E402
from prm.risk.extra_metrics import (  # noqa: E402
    component_es, dar_cdar, diversification_ratio, effective_risk_bets, stress_correlation, ulcer_index,
)
from prm.risk.factors import DEFAULT_FACTORS_PATH, FactorConfigError, build_factors, load_factor_config  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage 13: further risk metrics.")
    parser.add_argument("--settings", default=str(DEFAULT_SETTINGS_PATH))
    parser.add_argument("--factors", default=str(DEFAULT_FACTORS_PATH))
    parser.add_argument("--method", default="risk_budget", help="row of allocation_weights.csv")
    parser.add_argument("--tail", type=float, default=0.10, help="share of worst market days for the stress correlation")
    args = parser.parse_args(argv)

    processed = Path(load_data_settings(args.settings).processed_dir)
    needed = ("allocation_weights.csv", "returns_pln.csv", "returns_local.csv")
    if any(not (processed / f).exists() for f in needed):
        print("Missing stage-03/05 output. Run first:  python pipeline/03_fx_returns.py  and  python pipeline/05_allocation.py")
        return 1
    weights = pd.read_csv(processed / "allocation_weights.csv", index_col="method")
    if args.method not in weights.index:
        print(f"Unknown method '{args.method}'. Available: {list(weights.index)}")
        return 1
    w = weights.loc[args.method]
    w = w[w > 1e-12]
    pln = pd.read_csv(processed / "returns_pln.csv", index_col="date", parse_dates=True)
    local = pd.read_csv(processed / "returns_local.csv", index_col="date", parse_dates=True)
    if any(a not in pln.columns for a in w.index):
        print("Some weighted ETFs have no PLN returns.")
        return 1
    try:
        cfg = load_factor_config(args.factors)
        factors = build_factors(local, pln, cfg["factors"], cfg["fx_reference_asset"])
    except FactorConfigError as exc:
        print(f"Factor setup problem: {exc}")
        return 1
    if "market" not in factors.columns:
        print("config/risk_factors.yaml needs a factor called 'market' (equity market).")
        return 1

    window = pln[list(w.index)].dropna()
    if len(window) < 600:
        print(f"Common window too short ({len(window)} days).")
        return 1
    port = window @ w
    cov = ledoit_wolf(window)[0] * 252
    dar, cdar = dar_cdar(port, 0.95)
    comp = component_es(window, w, 0.95)
    rc = risk_contributions(w, cov)
    try:
        sc = stress_correlation(window, factors["market"], args.tail)
    except ValueError as exc:
        print(f"Stress correlation not possible: {exc}")
        return 1

    summary = pd.DataFrame({"value": {
        "dar_95": dar, "cdar_95": cdar, "ulcer_index": ulcer_index(port),
        "diversification_ratio": diversification_ratio(w, cov), "effective_risk_bets": effective_risk_bets(rc["risk_share"]),
        "es_95_daily": float(comp["es_total"].iloc[0]), "n_days": float(len(window))}})
    summary.to_csv(processed / "risk_extras_summary.csv", index_label="metric")
    assets = pd.DataFrame({"weight": w, "risk_share_vol": rc["risk_share"], "component_es": comp["component_es"],
                           "share_of_es": comp["share_of_es"]}).join(sc)
    assets.to_csv(processed / "risk_extras_assets.csv", index_label="asset_id")

    s = summary["value"]
    print(f"\nFURTHER RISK METRICS of '{args.method}' ({len(w)} ETFs, fixed weights, PLN). Window {window.index.min().date()} -> "
          f"{window.index.max().date()} ({len(window)} days)\n")
    print(f"Drawdown at risk 95% (depth exceeded 5% of the time): {s['dar_95']:.1%} | conditional (average depth in the worst 5%): "
          f"{s['cdar_95']:.1%} | Ulcer index: {s['ulcer_index']:.1%}")
    print(f"Diversification ratio: {s['diversification_ratio']:.2f} (1 = none) | effective number of risk bets: "
          f"{s['effective_risk_bets']:.2f} of {len(w)} ETFs | daily ES 95%: {s['es_95_daily']:.2%}\n")
    show = assets.copy()
    for c in ("weight", "risk_share_vol", "component_es", "share_of_es"):
        show[c] = (show[c] * 100).round(1)
    for c in ("corr_all", "corr_stress_raw", "corr_stress_adjusted", "change"):
        show[c] = show[c].round(2)
    print("PER ETF: weight, share of volatility, component ES (% of the portfolio, adds up to the daily ES) and its share, and the "
          f"correlation with the equity market on all days / on the worst {args.tail:.0%} market days (raw, corrected, change)\n")
    print(show.to_string())
    print(f"\nStress days: {sc.attrs['n_stress_days']}; variance of the market on those days vs all days: {sc.attrs['delta'] + 1:.2f}x")
    print("\nREAD WITH CARE\n * Historical and in-sample; tail shares rest on about 5% of the days."
          "\n * Tail share > volatility share = riskier in bad times than its volatility says."
          "\n * Corrected correlation undoes only the selection effect (Forbes-Rigobon): it shows a change, not its future size."
          f"\n\nWrote risk_extras_summary.csv, risk_extras_assets.csv in {processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
