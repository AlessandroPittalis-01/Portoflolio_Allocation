"""Local cache of downloaded prices.

Why a cache
-----------
Free sources can rate-limit or break. With a cache we download each symbol once,
the pipeline can be re-run offline, and a run is reproducible from the saved files.

Format
------
One CSV file per symbol: ``<raw_dir>/<source name>/<symbol>.csv``. CSV is chosen
on purpose: it is readable in any editor, shows clean diffs, and needs no extra
library. (Parquet can replace it later if the data become large.)

Note: a cached file keeps the ``start`` date used when it was downloaded. If you
change ``start_date`` in settings.yaml, run the pipeline with ``--refresh``.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pandas as pd

from prm.data.sources import PriceSource


def safe_name(symbol: str) -> str:
    """Turn a symbol into a safe file name (``^VIX`` becomes ``_VIX``)."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", symbol)


def cache_path(raw_dir: Path, source_name: str, symbol: str) -> Path:
    """Where the cached file of a symbol lives."""
    return Path(raw_dir) / source_name / f"{safe_name(symbol)}.csv"


def write_cache(df: pd.DataFrame, path: Path) -> None:
    """Save a standard-format table to ``path`` (folders are created if needed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index_label="date")


def read_cache(path: Path) -> pd.DataFrame | None:
    """Read a cached table, or return ``None`` if the file does not exist."""
    if not path.exists():
        return None
    return pd.read_csv(path, index_col="date", parse_dates=True)


def is_fresh(path: Path, max_age_days: float, now: float | None = None) -> bool:
    """True if the file exists and was written less than ``max_age_days`` ago."""
    if not path.exists():
        return False
    now = time.time() if now is None else now
    age_seconds = now - path.stat().st_mtime
    return age_seconds <= max_age_days * 86400


def load_or_fetch(
    source: PriceSource,
    symbol: str,
    start: str,
    raw_dir: Path,
    max_age_days: float,
    refresh: bool = False,
) -> tuple[pd.DataFrame, str]:
    """Return ``(prices, origin)`` where origin is ``"cache"`` or ``"download"``.

    * fresh cache and no ``refresh``  -> read the file, no network call
    * otherwise                        -> download, and cache the result
    An empty download is NOT cached, so a temporary failure does not poison the cache.
    """
    path = cache_path(raw_dir, source.name, symbol)

    if not refresh and is_fresh(path, max_age_days):
        cached = read_cache(path)
        if cached is not None:
            return cached, "cache"

    df = source.fetch(symbol, start)
    if len(df) > 0:
        write_cache(df, path)
    return df, "download"


def load_currency(source: PriceSource, symbol: str, raw_dir: Path) -> str | None:
    """Quote currency of a symbol, remembered in ``<symbol>.meta.json`` next to the cached prices.

    The source is asked only the first time. If it cannot answer, nothing is stored and the next run asks again.
    """
    meta_path = cache_path(raw_dir, source.name, symbol).with_suffix(".meta.json")
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8")).get("currency")
        except (OSError, ValueError):
            pass  # a damaged side file is simply ignored and rebuilt below
    currency = source.currency(symbol)
    if currency:
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps({"currency": currency}), encoding="utf-8")
    return currency
