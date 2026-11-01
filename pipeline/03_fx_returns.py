"""Stage 03 - PLN exchange rates (NBP) and returns in PLN.

Reads  : data/processed/prices_selected.csv  (stage 02), quality_report.csv (quote currency per asset)
Writes : data/processed/fx_rates.csv           PLN per 1 unit of each currency needed (as published by NBP)
         data/processed/returns_local.csv      simple daily returns in the quote currency
         data/processed/returns_pln.csv        simple daily returns in PLN  <- input of the risk stages
         data/processed/fx_decomposition.csv   per asset: volatilities, correlation, FX share of the variance

Each return is computed between the days on which that asset trades (see prm/fx/returns.py).

Run:  python pipeline/03_fx_returns.py            (needs internet the first time; then the cache is used)
      python pipeline/03_fx_returns.py --refresh  (download the rates again)
      python pipeline/03_fx_returns.py --input data/processed/prices_adj_close.csv   (all candidates)
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prm.config import DEFAULT_SETTINGS_PATH, REPO_ROOT, load_data_settings  # noqa: E402
from prm.fx.nbp import NbpSource, load_rates  # noqa: E402
from prm.fx.returns import decompose, simple_from_log, summarise  # noqa: E402


def main(argv: list[str] | None = None, source=None, today: date | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage 03: NBP rates and PLN returns.")
    parser.add_argument("--settings", default=str(DEFAULT_SETTINGS_PATH))
    parser.add_argument("--input", default="", help="price table (default: prices_selected.csv from stage 02)")
    parser.add_argument("--refresh", action="store_true", help="ignore the cache and download again")
    args = parser.parse_args(argv)

    settings = load_data_settings(args.settings)
    processed = Path(settings.processed_dir)
    prices_path = Path(args.input) if args.input else processed / "prices_selected.csv"
    report_path = processed / "quality_report.csv"
    if not prices_path.exists() or not report_path.exists():
        print("Missing input. Run first:  python pipeline/01_sourcing.py  and  python pipeline/02_selection.py")
        return 1

    prices = pd.read_csv(prices_path, index_col="date", parse_dates=True)
    currency_of = pd.read_csv(report_path).set_index("asset_id")["currency"].to_dict()

    # ---- which currencies do we need? -----------------------------------------------
    codes = sorted({str(currency_of.get(a)).upper() for a in prices.columns
                    if isinstance(currency_of.get(a), str)} - {"PLN"})
    start = date.fromisoformat(settings.start_date)
    end = today or date.today()
    source = source or NbpSource()

    rates: dict[str, pd.Series] = {}
    for code in codes:
        series, origin = load_rates(source, code, start, end, settings.raw_dir, settings.max_cache_age_days, args.refresh)
        if len(series) == 0:
            print(f"ERROR: no {code}/PLN rates received from NBP.")
            return 1
        rates[code] = series
        print(f"  {code}/PLN: {len(series)} rates from {series.index.min().date()} to {series.index.max().date()} ({origin})")
    processed.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rates).to_csv(processed / "fx_rates.csv", index_label="date")

    # ---- returns ------------------------------------------------------------------------
    local_cols, pln_cols, rows = {}, {}, []
    for asset_id in prices.columns:
        currency = currency_of.get(asset_id)
        if not isinstance(currency, str):
            print(f"  [{asset_id}] skipped: quote currency unknown")
            continue
        code = currency.upper()
        d = decompose(prices[asset_id], None if code == "PLN" else rates[code])
        if len(d) < 30:
            print(f"  [{asset_id}] skipped: only {len(d)} usable returns")
            continue
        local_cols[asset_id] = simple_from_log(d["local"])
        pln_cols[asset_id] = simple_from_log(d["pln"])
        rows.append({"asset_id": asset_id, "currency": code, **summarise(d)})

    pd.DataFrame(local_cols).sort_index().to_csv(processed / "returns_local.csv", index_label="date")
    pd.DataFrame(pln_cols).sort_index().to_csv(processed / "returns_pln.csv", index_label="date")
    table = pd.DataFrame(rows)
    table.to_csv(processed / "fx_decomposition.csv", index=False)

    show = table.copy()
    for col in ("vol_local_ann", "vol_fx_ann", "vol_pln_ann"):
        show[col] = (show[col] * 100).round(1)
    show["corr_local_fx"] = show["corr_local_fx"].round(2)
    show["fx_share_full"] = (show["fx_share_full"] * 100).round(0)
    show["fx_share_last3y"] = (show["fx_share_last3y"] * 100).round(0)
    print("\nVolatility in % per year; FX share = % of the PLN variance explained by the currency\n")
    print(show[["asset_id", "currency", "n_obs", "vol_local_ann", "vol_fx_ann", "vol_pln_ann",
                "corr_local_fx", "fx_share_full", "fx_share_last3y"]].to_string(index=False))
    print("\nWrote fx_rates.csv, returns_local.csv, returns_pln.csv, fx_decomposition.csv in", processed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
