"""Stage 04 - risk analysis of the selected ETFs, in PLN.

Reads  : data/processed/returns_pln.csv, returns_local.csv, fx_rates.csv, fx_decomposition.csv (stage 03)
Writes : data/processed/risk_summary.csv      one row per asset: volatility, drawdown, VaR/ES, tails, dollar beta
         data/processed/correlation.csv       correlations on the common window
         data/processed/cov_sample.csv        annualised covariance matrices on the common window:
         data/processed/cov_ewma.csv            sample, EWMA (lambda 0.94) and Ledoit-Wolf shrinkage
         data/processed/cov_ledoit_wolf.csv
         data/processed/stress_scenarios.csv  PLN return of each asset in each historical episode

Nothing here picks a winner: it only MEASURES risk. Returns shown are descriptive, never a selection criterion.

Run:  python pipeline/04_risk_analysis.py
      python pipeline/04_risk_analysis.py --assets allworld_vanguard,global_bond_hedged,gold,cash_like
The covariance matrices need a window where every chosen asset has data, so the shortest history sets the
window. Choose the assets to compare with --assets (fewer assets, longer window).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prm.config import DEFAULT_SETTINGS_PATH, load_data_settings  # noqa: E402
from prm.risk.covariance import annualise, common_window, ewma_cov, ledoit_wolf, sample_cov, to_correlation  # noqa: E402
from prm.risk.metrics import summarise_returns  # noqa: E402
from prm.risk.stress import DEFAULT_SCENARIOS_PATH, load_scenarios, stress_table  # noqa: E402
from prm.risk.usd import usd_beta, usd_in_eur  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage 04: risk analysis.")
    parser.add_argument("--settings", default=str(DEFAULT_SETTINGS_PATH))
    parser.add_argument("--scenarios", default=str(DEFAULT_SCENARIOS_PATH))
    parser.add_argument("--assets", default="", help="comma-separated asset ids (default: all)")
    parser.add_argument("--ewma-lambda", type=float, default=0.94)
    args = parser.parse_args(argv)

    processed = Path(load_data_settings(args.settings).processed_dir)
    needed = ["returns_pln.csv", "returns_local.csv", "fx_rates.csv", "fx_decomposition.csv"]
    if any(not (processed / f).exists() for f in needed):
        print("Missing stage-03 output. Run first:  python pipeline/03_fx_returns.py")
        return 1

    pln = pd.read_csv(processed / "returns_pln.csv", index_col="date", parse_dates=True)
    local = pd.read_csv(processed / "returns_local.csv", index_col="date", parse_dates=True)
    rates = pd.read_csv(processed / "fx_rates.csv", index_col="date", parse_dates=True)
    currency_of = pd.read_csv(processed / "fx_decomposition.csv").set_index("asset_id")["currency"].to_dict()

    wanted = [a.strip() for a in args.assets.split(",") if a.strip()]
    if wanted:
        unknown = [a for a in wanted if a not in pln.columns]
        if unknown:
            print(f"Unknown asset ids: {unknown}")
            return 1
        pln = pln[wanted]

    # ---- 1. single-asset risk table -------------------------------------------------------
    usd_eur = usd_in_eur(rates["USD"], rates["EUR"]) if {"USD", "EUR"} <= set(rates.columns) else None
    rows = []
    for asset_id in pln.columns:
        row = {"asset_id": asset_id, "currency": currency_of.get(asset_id), **summarise_returns(pln[asset_id])}
        if usd_eur is not None and currency_of.get(asset_id) == "EUR" and asset_id in local.columns:
            row["usd_beta"], row["usd_r2"] = usd_beta(local[asset_id], usd_eur)
        else:
            row["usd_beta"], row["usd_r2"] = float("nan"), float("nan")
        rows.append(row)
    summary = pd.DataFrame(rows)
    summary.to_csv(processed / "risk_summary.csv", index=False)

    # ---- 2. covariance on the common window --------------------------------------------------
    window = common_window(pln)
    if len(window) < 250:
        print(f"Common window has only {len(window)} days: choose fewer assets with --assets.")
        return 1
    cov_s = sample_cov(window)
    cov_e = ewma_cov(window, args.ewma_lambda)
    cov_lw, shrink = ledoit_wolf(window)
    for name, cov in (("cov_sample", cov_s), ("cov_ewma", cov_e), ("cov_ledoit_wolf", cov_lw)):
        annualise(cov).to_csv(processed / f"{name}.csv", index_label="asset_id")
    corr = to_correlation(cov_s)
    corr.to_csv(processed / "correlation.csv", index_label="asset_id")

    # ---- 3. stress scenarios ---------------------------------------------------------------------
    stress = stress_table(pln, load_scenarios(args.scenarios))
    stress.to_csv(processed / "stress_scenarios.csv", index_label="asset_id")

    # ---- console summary ----------------------------------------------------------------------------
    pct = lambda s, d=1: (s * 100).round(d)  # noqa: E731
    show = pd.DataFrame({
        "asset_id": summary["asset_id"], "vol%": pct(summary["ann_vol"]), "maxDD%": pct(summary["max_dd"]),
        "now DD%": pct(summary["current_dd"]), "VaR99h%": pct(summary["var99_hist"], 2), "ES99h%": pct(summary["es99_hist"], 2),
        "ES99 gauss%": pct(summary["es99_gauss"], 2), "kurt": summary["excess_kurtosis"].round(1),
        "USD beta": summary["usd_beta"].round(2), "USD R2": summary["usd_r2"].round(2),
    })
    print("\nRisk in PLN (daily data). VaR/ES: 1 day, 99%. 'gauss' = if returns were normal. kurt = excess kurtosis (fat tails if > 0)\n")
    print(show.to_string(index=False))
    print(f"\nCommon window for covariances: {window.index.min().date()} to {window.index.max().date()} "
          f"({len(window)} days, {window.shape[1]} assets)")
    print(f"Ledoit-Wolf shrinkage: {shrink:.3f} (0 = trust the sample, 1 = trust the simple target)")
    print(f"Condition number (high = unstable inverse): sample {np.linalg.cond(cov_s):.0f}, "
          f"Ledoit-Wolf {np.linalg.cond(cov_lw):.0f}")
    pairs = [(a, b, corr.loc[a, b]) for i, a in enumerate(corr.columns) for b in corr.columns[i + 1:] if corr.loc[a, b] > 0.95]
    if pairs:
        print("Pairs with correlation above 0.95 (almost the same bet):")
        for a, b, v in sorted(pairs, key=lambda t: -t[2]):
            print(f"  {a} vs {b}: {v:.3f}")
    print("\nStress scenarios, PLN return in % (empty = the asset did not exist yet):\n")
    print((stress * 100).round(1).to_string())
    print("\nWrote risk_summary.csv, correlation.csv, cov_*.csv, stress_scenarios.csv in", processed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
