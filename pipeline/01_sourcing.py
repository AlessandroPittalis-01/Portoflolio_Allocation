"""Stage 01 - Sourcing.

What this stage does
--------------------
1. reads the ETF universe (config/universe_candidates.yaml) and the settings
   (config/settings.yaml)
2. downloads daily prices for every asset with a confirmed Yahoo symbol, reusing
   the local cache when it is fresh
3. runs the quality checks of ``prm.data.quality`` on each series
4. writes two tables to ``data/processed/``:
     * prices_adj_close.csv  - adjusted closing prices, one column per asset id
     * quality_report.csv    - one row per asset: status, size, dates, issues

Nothing is corrected silently: problems are listed in the report, and the
decision on what to do about them is yours (and goes into docs/IPS.md).

How to run (from the repository root, with the virtual environment active)
--------------------------------------------------------------------------
    python pipeline/01_sourcing.py                 # normal run
    python pipeline/01_sourcing.py --refresh       # ignore the cache and download again
    python pipeline/01_sourcing.py --assets dev_equity,gold
    python pipeline/01_sourcing.py --find          # ask Yahoo which symbols match each ISIN / name
    python pipeline/01_sourcing.py --probe         # test the UNCONFIRMED symbol guesses

Next stage: 02 (FX and PLN returns), not built yet.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from prm.config import DEFAULT_SETTINGS_PATH, load_data_settings
from prm.data.cache import load_or_fetch
from prm.data.quality import QualityReport, check_prices
from prm.data.sources import PriceSource, YahooSource
from prm.data.universe import DEFAULT_UNIVERSE_PATH, Asset, load_universe


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 01: download prices and check their quality.")
    parser.add_argument("--refresh", action="store_true", help="ignore the cache and download again")
    parser.add_argument("--probe", action="store_true", help="test the unconfirmed symbol guesses")
    parser.add_argument("--find", action="store_true",
                        help="list the Yahoo listings (symbol, exchange, name) found for each unconfirmed asset")
    parser.add_argument("--assets", default="", help="comma-separated asset ids (default: all)")
    parser.add_argument("--settings", default=str(DEFAULT_SETTINGS_PATH), help="path to settings.yaml")
    parser.add_argument("--universe", default=str(DEFAULT_UNIVERSE_PATH), help="path to the universe YAML")
    return parser


def _quality_row(asset_id: str, symbol: str, report: QualityReport, origin: str) -> dict:
    """One line of quality_report.csv."""
    return {
        "asset_id": asset_id,
        "symbol": symbol,
        "status": report.status,
        "n_rows": report.n_rows,
        "first_date": report.first_date.date().isoformat() if report.first_date is not None else "",
        "last_date": report.last_date.date().isoformat() if report.last_date is not None else "",
        "history_years": round(report.history_years, 1),
        "origin": origin,
        "issues": "; ".join(report.codes),
    }


def _check(df: pd.DataFrame, symbol: str, settings, min_history_years: float | None) -> QualityReport:
    return check_prices(
        df,
        symbol,
        max_daily_move=settings.max_daily_move,
        max_gap_days=settings.max_gap_days,
        max_stale_days=settings.max_stale_days,
        min_history_years=min_history_years,
    )


def _probe(assets: list[Asset], source: PriceSource, settings, refresh: bool, min_history: float | None) -> None:
    """Try the unconfirmed symbol guesses and print what each one returns."""
    print("Probing unconfirmed symbols (nothing is written to processed/):\n")
    for asset in assets:
        if asset.yahoo_symbol or not asset.symbols_to_try:
            continue
        for symbol in asset.symbols_to_try:
            try:
                df, origin = load_or_fetch(
                    source, symbol, settings.start_date, settings.raw_dir, settings.max_cache_age_days, refresh
                )
                report = _check(df, symbol, settings, min_history)
                first = report.first_date.date() if report.first_date is not None else "-"
                print(f"{asset.id:22s} {symbol:10s} rows={report.n_rows:5d} first={first} "
                      f"status={report.status} {report.codes or ''}")
            except Exception as exc:  # a failing symbol must not stop the probe
                print(f"{asset.id:22s} {symbol:10s} FAILED: {exc}")
    print("\nIf a symbol looks right (rows, first date, name on Yahoo), copy it by hand into")
    print("'yahoo_symbol' in config/universe_candidates.yaml and note it in docs/IPS.md.")


def _find(assets: list[Asset], source: PriceSource) -> None:
    """For each asset without a confirmed symbol, ask Yahoo which listings match its ISIN (or name).

    Read the fund name shown for each hit: it must be the fund you expect. Prefer the listing on a
    euro exchange (for example XETRA, Amsterdam, Milan), then copy the symbol into 'yahoo_symbol'.
    """
    print("Searching Yahoo for unconfirmed assets (nothing is written):\n")
    for asset in assets:
        if asset.yahoo_symbol:
            continue
        query = asset.isin or asset.search_text or asset.name
        print(f"[{asset.id}] {asset.name}")
        print(f"    searched for: {query}")
        try:
            hits = source.search(query)
        except Exception as exc:  # a failing search must not stop the others
            print(f"    SEARCH FAILED: {exc}\n")
            continue
        if not hits:
            print("    no result: search the ISIN on justETF (see docs/SETUP_it.md) and send me the listings table\n")
            continue
        for hit in hits:
            symbol = hit.get("symbol", "?")
            exchange = hit.get("exchDisp") or hit.get("exchange") or "?"
            kind = hit.get("quoteType", "?")
            name = hit.get("longname") or hit.get("shortname") or "?"
            print(f"    {symbol:14s} {exchange:22s} {kind:8s} {name}")
        print()
    print("Copy the right symbol by hand into 'yahoo_symbol' in config/universe_candidates.yaml,")
    print("or paste this output in the chat and ask for the exact lines to change.")


def main(argv: list[str] | None = None, source: PriceSource | None = None) -> int:
    """Run the stage. ``source`` can be replaced (used by the tests with fake data)."""
    args = _build_parser().parse_args(argv)
    settings = load_data_settings(args.settings)
    criteria, assets = load_universe(args.universe)
    source = source or YahooSource()

    wanted = {a.strip() for a in args.assets.split(",") if a.strip()}
    if wanted:
        unknown = wanted - {a.id for a in assets}
        if unknown:
            print(f"Unknown asset ids: {sorted(unknown)}")
            return 1
        assets = [a for a in assets if a.id in wanted]

    if args.find:
        _find(assets, source)
        return 0

    if args.probe:
        _probe(assets, source, settings, args.refresh, criteria.get("min_history_years"))
        return 0

    min_history = criteria.get("min_history_years")
    rows: list[dict] = []
    series: dict[str, pd.Series] = {}

    for asset in assets:
        if not asset.yahoo_symbol:
            rows.append({"asset_id": asset.id, "symbol": "", "status": "no_symbol", "issues": "symbol still to be found"})
            continue
        try:
            df, origin = load_or_fetch(
                source, asset.yahoo_symbol, settings.start_date, settings.raw_dir,
                settings.max_cache_age_days, args.refresh,
            )
        except Exception as exc:  # network errors, rate limits...
            rows.append({"asset_id": asset.id, "symbol": asset.yahoo_symbol, "status": "download_failed", "issues": str(exc)})
            continue

        report = _check(df, asset.yahoo_symbol, settings, min_history)
        rows.append(_quality_row(asset.id, asset.yahoo_symbol, report, origin))
        for issue in report.issues:
            print(f"  [{asset.id}] {issue.severity}: {issue.message}")
        # Series with structural errors (duplicates, non-positive prices...) are NOT passed on.
        if report.status != "error" and len(df):
            series[asset.id] = df["adj_close"].rename(asset.id)

    out_dir = Path(settings.processed_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    report_df = pd.DataFrame(rows)
    if "n_rows" in report_df.columns:
        report_df["n_rows"] = report_df["n_rows"].astype("Int64")  # whole numbers, empty for assets without data
    report_df.to_csv(out_dir / "quality_report.csv", index=False)
    if series:
        # Outer join: a date missing for one asset stays empty (NaN). Nothing is filled in.
        prices = pd.concat(series.values(), axis=1, sort=True)  # sort=True: dates in increasing order
        prices.to_csv(out_dir / "prices_adj_close.csv", index_label="date")

    print("\nQuality report:")
    print(report_df.to_string(index=False))
    print(f"\nFiles written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
