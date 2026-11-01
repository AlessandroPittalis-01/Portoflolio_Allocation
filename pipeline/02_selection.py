"""Stage 02 - choose ONE ETF per category, by criteria only (never by performance).

Reads  : config/universe_candidates.yaml, data/processed/quality_report.csv (from stage 01)
Writes : data/processed/selection.csv           every candidate with its rank and the reason
         data/processed/selected_assets.csv     the winners only, one per category
         data/processed/prices_selected.csv     prices of the winners (input of the next stages)

Also prints a redundancy check: winners that are almost the same exposure (daily-return
correlation above 0.95). Correlation is not performance, so looking at it is allowed.
The optimiser (stage 05) will choose weights among the winners.

Run:  python pipeline/02_selection.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prm.config import DEFAULT_SETTINGS_PATH, REPO_ROOT, load_data_settings  # noqa: E402
from prm.data.universe import DEFAULT_UNIVERSE_PATH, load_universe  # noqa: E402
from prm.selection.selector import (  # noqa: E402
    build_candidates, explain_choice, high_correlation_pairs, select_per_category,
)


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage 02: select one ETF per category (criteria only).")
    parser.add_argument("--settings", default=str(DEFAULT_SETTINGS_PATH))
    parser.add_argument("--universe", default=str(DEFAULT_UNIVERSE_PATH))
    args = parser.parse_args(argv)

    settings = load_data_settings(args.settings)
    processed = _resolve(str(settings.processed_dir))
    report_path = processed / "quality_report.csv"
    prices_path = processed / "prices_adj_close.csv"
    if not report_path.exists() or not prices_path.exists():
        print("Missing stage-01 output. Run first:  python pipeline/01_sourcing.py")
        return 1

    criteria, assets = load_universe(args.universe)
    report = pd.read_csv(report_path)
    table = select_per_category(build_candidates(assets, report), criteria)
    winners = table[table["selected"]].copy()
    winners["why"] = [explain_choice(table, c) for c in winners["category"]]

    table.to_csv(processed / "selection.csv", index=False)
    winners.to_csv(processed / "selected_assets.csv", index=False)

    prices = pd.read_csv(prices_path, index_col="date", parse_dates=True)
    selected_ids = [i for i in winners["asset_id"] if i in prices.columns]
    prices[selected_ids].to_csv(processed / "prices_selected.csv")

    # ---- console summary -------------------------------------------------------------
    print(f"\nCandidates: {len(table)}   categories: {table['category'].nunique()}   winners: {len(winners)}\n")
    show = winners[["category", "asset_id", "symbol", "ter_pct", "history_years", "n_candidates", "why"]]
    print(show.to_string(index=False))

    empty = sorted(set(table["category"]) - set(winners["category"]))
    if empty:
        print("\nCategories WITHOUT a winner (no eligible candidate):")
        for cat in empty:
            reasons = "; ".join(f"{r.asset_id}: {r.excluded_because}" for r in table[table["category"] == cat].itertuples())
            print(f"  - {cat}  ->  {reasons}")

    dist = winners[winners["accumulating"] != True]  # noqa: E712  (False or unknown)
    if len(dist):
        print("\nWinners that are NOT confirmed accumulating (tax and total-return handling to decide):")
        print("  " + ", ".join(dist["asset_id"]))

    returns = prices[selected_ids].pct_change(fill_method=None)
    pairs = high_correlation_pairs(returns)
    if pairs:
        print("\nRedundancy check: winners with daily-return correlation above 0.95")
        for a, b, v in pairs:
            print(f"  {a} vs {b}: {v:.3f}")
    print("\nWrote selection.csv, selected_assets.csv, prices_selected.csv in", processed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
