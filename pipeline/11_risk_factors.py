"""Stage 11 - risk-factor sensitivities of the allocated portfolio (IPS decision 39, step 3).

Reads  : data/processed/allocation_weights.csv (stage 05), returns_pln.csv, returns_local.csv (stage 03),
         config/risk_factors.yaml
Writes : data/processed/risk_factors.csv           beta, t-stat, factor volatility, 1-sigma monthly move, share of variance
         data/processed/risk_factors_rolling.csv   betas re-estimated on 2-year windows (stability)

For a portfolio of ETFs the 'Greeks' are linear: the sensitivity (beta) of the PLN return to equity market, interest
rates, credit spread, inflation, gold and EUR/PLN. The shares of variance add up to 100% with a residual.

HOW TO READ THE RESULT
* Factors are ETF proxies and are correlated: individual betas are less reliable than the total picture.
* A negative share = that factor diversifies the portfolio. The residual = risk the factors do not explain.
* Compare the rolling betas: if they move a lot, the sensitivity is not a constant of the portfolio.
* A beta describes small moves: it is not a stress test (see the stress stage).

Run:  python pipeline/11_risk_factors.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prm.config import DEFAULT_SETTINGS_PATH, load_data_settings  # noqa: E402
from prm.risk.factors import (  # noqa: E402
    DEFAULT_FACTORS_PATH, FactorConfigError, build_factors, load_factor_config, rolling_beta, sensitivities,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage 11: risk-factor sensitivities.")
    parser.add_argument("--settings", default=str(DEFAULT_SETTINGS_PATH))
    parser.add_argument("--factors", default=str(DEFAULT_FACTORS_PATH))
    parser.add_argument("--method", default="risk_budget", help="row of allocation_weights.csv")
    parser.add_argument("--window", type=int, default=504, help="days of the rolling betas")
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
    port = pln[list(w.index)].dropna() @ w
    data = pd.concat([port.rename("port"), factors], axis=1).dropna()
    if len(data) < 600:
        print(f"Common window too short ({len(data)} days).")
        return 1

    table = sensitivities(data["port"], data[factors.columns])
    resid = table.attrs["residual_share"]
    out = table.copy()
    out.loc["residual"] = [float("nan")] * 4 + [resid]
    out.to_csv(processed / "risk_factors.csv", index_label="factor")
    rolling = rolling_beta(data["port"], data[factors.columns], window=min(args.window, len(data) - 100))
    rolling.to_csv(processed / "risk_factors_rolling.csv", index_label="date")

    show = table.copy()
    show["beta"], show["t_stat"] = show["beta"].round(2), show["t_stat"].round(1)
    for c in ("factor_vol_ann", "one_sigma_month_move", "share_of_variance"):
        show[c] = (show[c] * 100).round(1)
    print(f"\nRISK FACTORS of '{args.method}' ({len(w)} ETFs, fixed weights, PLN). Window {data.index.min().date()} -> "
          f"{data.index.max().date()} ({len(data)} days). R-squared {table.attrs['r2']:.2f}\n")
    print("Factors: " + "; ".join(f"{k} = {v}" for k, v in cfg["factors"].items()) + "\n")
    print("beta = % move of the portfolio for a +1% move of the factor; factor_vol_ann, one_sigma_month_move and "
          "share_of_variance in %\n")
    print(show.to_string())
    print(f"\nShare of variance NOT explained by the factors (residual): {resid:.1%}")
    if len(rolling) > 1:
        rng = pd.DataFrame({"min": rolling.min(), "max": rolling.max()}).round(2)
        print(f"\nROLLING BETAS (windows of {min(args.window, len(data) - 100)} days, {len(rolling)} windows): range of each beta\n")
        print(rng.to_string())
    print("\nREAD WITH CARE\n * Factors are ETF proxies and are correlated; trust the overall picture more than one beta."
          "\n * Fixed weights, in-sample, OLS standard errors ignore autocorrelation and fat tails."
          "\n * A beta is a sensitivity to small moves, not a stress test."
          f"\n\nWrote risk_factors.csv, risk_factors_rolling.csv in {processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
