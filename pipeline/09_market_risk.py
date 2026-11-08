"""Stage 09 - VaR and ES of the allocated portfolio with several models (IPS decision 39, step 1).

Reads  : data/processed/allocation_weights.csv (stage 05), returns_pln.csv (stage 03)
Writes : data/processed/market_risk_var.csv   one row per model x level (1-day VaR and ES, % of the portfolio)

Portfolio = the weights of one method of stage 05 (default risk_budget), held fixed, PLN returns, common window.
Models (see prm/risk/var_models.py): historical, gaussian, EWMA-gaussian, FHS (EWMA and GARCH), Monte Carlo
gaussian and Monte Carlo Student-t. The question they answer is the same; the spread between them is the model risk.

HOW TO READ THE RESULT
* 1-day horizon, fixed weights, in-sample window. No model is 'right': the next stage backtests them.
* 'current_vol' vs 'average_vol' says whether the market is calmer or stormier than the sample average today.
* A big gap between gaussian and the fat-tail models at 99% / ES says how much the bell curve understates the tail.

Run:  python pipeline/09_market_risk.py                       (method risk_budget)
      python pipeline/09_market_risk.py --method equal_weight --paths 500000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prm.config import DEFAULT_SETTINGS_PATH, load_data_settings  # noqa: E402
from prm.risk.covariance import ledoit_wolf  # noqa: E402
from prm.risk.metrics import gaussian_var_es, hist_var_es  # noqa: E402
from prm.risk.var_models import (  # noqa: E402
    ewma_sigma, fhs_var_es, fit_student_df, garch11_fit, mc_var_es, normal_var_es,
)

LEVELS = (0.95, 0.99)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage 09: VaR / ES with several models.")
    parser.add_argument("--settings", default=str(DEFAULT_SETTINGS_PATH))
    parser.add_argument("--method", default="risk_budget", help="row of allocation_weights.csv")
    parser.add_argument("--paths", type=int, default=200_000, help="Monte Carlo paths")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    processed = Path(load_data_settings(args.settings).processed_dir)
    if not (processed / "allocation_weights.csv").exists() or not (processed / "returns_pln.csv").exists():
        print("Missing stage-03/05 output. Run first:  python pipeline/03_fx_returns.py  and  python pipeline/05_allocation.py")
        return 1
    weights_all = pd.read_csv(processed / "allocation_weights.csv", index_col="method")
    if args.method not in weights_all.index:
        print(f"Unknown method '{args.method}'. Available: {list(weights_all.index)}")
        return 1
    w = weights_all.loc[args.method]
    w = w[w > 1e-12]
    pln = pd.read_csv(processed / "returns_pln.csv", index_col="date", parse_dates=True)
    missing = [a for a in w.index if a not in pln.columns]
    if missing:
        print(f"No PLN returns for: {missing}")
        return 1
    window = pln[list(w.index)].dropna()
    if len(window) < 500:
        print(f"Common window too short ({len(window)} days).")
        return 1
    port = window @ w
    cov = ledoit_wolf(window)[0]

    garch = garch11_fit(port)
    z_ewma = fhs_var_es(port, 0.95, "ewma")["z"]
    df_t = fit_student_df(z_ewma)
    sig_ewma = ewma_sigma(port)[1]

    rows = []
    for level in LEVELS:
        hv, he = hist_var_es(port, level)
        gv, ge = gaussian_var_es(port, level)
        ev, ee = normal_var_es(sig_ewma, level)
        gav, gae = normal_var_es(garch["sigma_next"], level)
        fe = fhs_var_es(port, level, "ewma")
        fg = fhs_var_es(port, level, "garch")
        mcn = mc_var_es(w, cov, level, args.paths, None, seed=args.seed)
        mct = mc_var_es(w, cov, level, args.paths, df_t, seed=args.seed)
        for model, (v, e) in {
            "historical": (hv, he), "gaussian_full_sample": (gv, ge), "gaussian_ewma": (ev, ee),
            "gaussian_garch": (gav, gae), "fhs_ewma": (fe["var"], fe["es"]), "fhs_garch": (fg["var"], fg["es"]),
            "montecarlo_gaussian": mcn, f"montecarlo_t(df={df_t:.1f})": mct,
        }.items():
            rows.append({"model": model, "level": level, "var": v, "es": e})
    out = pd.DataFrame(rows)
    out.to_csv(processed / "market_risk_var.csv", index=False)

    ann = np.sqrt(252)
    print(f"\nPORTFOLIO '{args.method}' ({len(w)} ETFs, fixed weights, PLN). Window {window.index.min().date()} -> "
          f"{window.index.max().date()} ({len(window)} days). 1-day horizon.")
    print(f"Volatility, annual: average {port.std() * ann:.1%} | current EWMA {sig_ewma * ann:.1%} | current GARCH "
          f"{garch['sigma_next'] * ann:.1%} (GARCH persistence {garch['persistence']:.3f}, long-run {garch['long_run_vol_ann']:.1%})")
    print(f"Student-t degrees of freedom of the standardised portfolio returns: {df_t:.1f} (lower = fatter tails)\n")
    for level in LEVELS:
        sub = out[out["level"] == level].set_index("model")
        base = sub.loc["gaussian_full_sample"]
        show = pd.DataFrame({"VaR_%": (sub["var"] * 100).round(2), "ES_%": (sub["es"] * 100).round(2),
                             "VaR_vs_gauss": (sub["var"] / base["var"]).round(2), "ES_vs_gauss": (sub["es"] / base["es"]).round(2)})
        print(f"{level:.0%} level:\n{show.to_string()}\n")
    print("READ WITH CARE\n * Same portfolio, same day, different assumptions: the spread is MODEL RISK; do not pick the smallest number."
          "\n * 1 day, fixed weights, in-sample; Monte Carlo uses the Ledoit-Wolf covariance and ONE df for all assets."
          "\n * Which model is adequate is decided by backtesting (next step), not here."
          f"\n\nWrote market_risk_var.csv in {processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
