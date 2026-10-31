"""Price sources.

A *source* is anything that can return daily prices for a symbol. All sources
return the SAME table format, so the rest of the code never needs to know where
the data came from. Today there is one source (Yahoo Finance); a second one can
be added later (for example an issuer NAV file) to cross-check the first.

Standard format
---------------
* index: ``DatetimeIndex`` named ``date`` (no timezone)
* columns: ``open, high, low, close, adj_close, volume``

``close`` is the price as traded. ``adj_close`` also includes dividends and
splits, so it is the right series for returns. For accumulating ETFs the two are
normally identical.
"""

from __future__ import annotations

import warnings
from abc import ABC, abstractmethod

import pandas as pd

STANDARD_COLUMNS = ["open", "high", "low", "close", "adj_close", "volume"]


def standardise_frame(raw: pd.DataFrame | None) -> pd.DataFrame:
    """Convert a raw download into the standard format.

    The function does NOT fix or hide data problems (duplicates, gaps, odd
    prices): those are reported later by ``quality.check_prices``.
    """
    empty = pd.DataFrame(columns=STANDARD_COLUMNS, index=pd.DatetimeIndex([], name="date"))
    if raw is None or len(raw) == 0:
        return empty

    df = raw.copy()

    # yfinance returns two column levels (Price, Ticker) even for one symbol.
    # We keep the price level only.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.columns = [str(c).strip().lower() for c in df.columns]
    df = df.rename(columns={"adj close": "adj_close"})

    missing = [c for c in ("close", "adj_close") if c not in df.columns]
    if missing:
        raise ValueError(f"download is missing required columns: {missing}")

    for col in STANDARD_COLUMNS:
        if col not in df.columns:
            df[col] = float("nan")
    df = df[STANDARD_COLUMNS]

    index = pd.DatetimeIndex(df.index)
    if index.tz is not None:
        index = index.tz_localize(None)  # drop the timezone, keep the calendar date
    df.index = index.rename("date")
    return df


class PriceSource(ABC):
    """Interface every price source must implement."""

    #: short name, used for the cache folder (for example ``yahoo``)
    name: str = "source"

    @abstractmethod
    def fetch(self, symbol: str, start: str, end: str | None = None) -> pd.DataFrame:
        """Return daily prices for ``symbol`` in the standard format."""

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        """List the listings found for an ISIN or a name (optional: not every source can do it)."""
        raise NotImplementedError(f"source '{self.name}' cannot search")


class YahooSource(PriceSource):
    """Yahoo Finance through the ``yfinance`` library.

    Yahoo has no official API: ``yfinance`` uses undocumented endpoints, so it
    can be rate-limited or change without notice. That is why the pipeline
    caches every download and runs quality checks on it.
    """

    name = "yahoo"

    def fetch(self, symbol: str, start: str, end: str | None = None) -> pd.DataFrame:
        try:
            import yfinance as yf  # imported here so the rest of the package works without it
        except ImportError as exc:
            raise ImportError("yfinance is not installed: run 'pip install yfinance'") from exc

        # auto_adjust=False keeps BOTH close and adj_close, so we can compare them.
        # yfinance still uses a pandas feature ("inplace") that pandas plans to remove. The warning is
        # harmless and not about our code, so we hide ONLY that message, and only during this call.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="The inplace keyword")
            raw = yf.download(symbol, start=start, end=end, progress=False, auto_adjust=False)
        return standardise_frame(raw)

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        """Ask Yahoo which symbols match an ISIN or a name (one entry per listing).

        Each entry is a dictionary with keys such as ``symbol``, ``exchange``, ``quoteType``,
        ``shortname`` and ``longname``. The exact keys depend on the yfinance version.
        """
        try:
            import yfinance as yf
        except ImportError as exc:
            raise ImportError("yfinance is not installed: run 'pip install yfinance'") from exc
        if not hasattr(yf, "Search"):
            raise RuntimeError("this yfinance version has no Search: run 'pip install -U yfinance'")

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="The inplace keyword")
            try:
                result = yf.Search(query, max_results=max_results)
            except TypeError:  # older versions do not accept max_results
                result = yf.Search(query)
        return list(result.quotes)
