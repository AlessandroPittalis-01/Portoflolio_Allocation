"""Tests for prm.data.sources and prm.data.cache (no network: yfinance is faked)."""

import os
import sys
import tempfile
import time
import types
import unittest
import warnings
from pathlib import Path

import pandas as pd

from helpers import make_prices
from prm.data.cache import cache_path, is_fresh, load_currency, load_or_fetch, read_cache, safe_name, write_cache
from prm.data.sources import STANDARD_COLUMNS, PriceSource, YahooSource, standardise_frame


def yahoo_like_frame(tz=None) -> pd.DataFrame:
    """A table shaped like the output of yfinance: columns are (Price, Ticker)."""
    index = pd.bdate_range("2024-01-01", periods=5, tz=tz)
    columns = pd.MultiIndex.from_product(
        [["Adj Close", "Close", "High", "Low", "Open", "Volume"], ["EUNL.DE"]], names=["Price", "Ticker"]
    )
    return pd.DataFrame(100.0, index=index, columns=columns)


class FakeSource(PriceSource):
    """Returns synthetic data and counts how many times it is called."""

    name = "fake"

    def __init__(self, empty: bool = False):
        self.calls = 0
        self.currency_calls = 0
        self.empty = empty

    def currency(self, symbol):
        self.currency_calls += 1
        return "EUR"

    def fetch(self, symbol, start, end=None):
        self.calls += 1
        df = make_prices(start="2024-01-01")
        return df.iloc[0:0] if self.empty else df


class TestStandardise(unittest.TestCase):
    def test_multiindex_columns_become_standard(self):
        df = standardise_frame(yahoo_like_frame())
        self.assertEqual(list(df.columns), STANDARD_COLUMNS)
        self.assertEqual(df.index.name, "date")

    def test_timezone_is_removed(self):
        df = standardise_frame(yahoo_like_frame(tz="Europe/Berlin"))
        self.assertIsNone(df.index.tz)

    def test_missing_close_raises(self):
        raw = yahoo_like_frame().drop(columns="Close", level=0)
        with self.assertRaises(ValueError):
            standardise_frame(raw)

    def test_empty_input_gives_empty_standard_table(self):
        df = standardise_frame(pd.DataFrame())
        self.assertEqual(len(df), 0)
        self.assertEqual(list(df.columns), STANDARD_COLUMNS)


class TestYahooSource(unittest.TestCase):
    def tearDown(self):
        sys.modules.pop("yfinance", None)

    def test_fetch_uses_yfinance_and_standardises(self):
        calls = {}

        def fake_download(symbol, start, end, progress, auto_adjust):
            calls.update(symbol=symbol, auto_adjust=auto_adjust)
            return yahoo_like_frame()

        sys.modules["yfinance"] = types.SimpleNamespace(download=fake_download)
        df = YahooSource().fetch("EUNL.DE", "2020-01-01")
        self.assertEqual(calls["symbol"], "EUNL.DE")
        self.assertFalse(calls["auto_adjust"])  # we want both close and adj_close
        self.assertEqual(list(df.columns), STANDARD_COLUMNS)

    def test_harmless_inplace_warning_is_hidden(self):
        def noisy_download(symbol, start, end, progress, auto_adjust):
            warnings.warn("The inplace keyword in DataFrame.sort_index is deprecated", Warning)
            return yahoo_like_frame()

        sys.modules["yfinance"] = types.SimpleNamespace(download=noisy_download)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            YahooSource().fetch("EUNL.DE", "2020-01-01")
        self.assertEqual(len(caught), 0)

    def test_search_returns_quotes(self):
        class FakeSearch:
            def __init__(self, query, max_results=8):
                self.quotes = [{"symbol": "IWDA.AS", "exchDisp": "Amsterdam", "query": query}]

        sys.modules["yfinance"] = types.SimpleNamespace(Search=FakeSearch)
        hits = YahooSource().search("IE00B4L5Y983")
        self.assertEqual(hits[0]["symbol"], "IWDA.AS")
        self.assertEqual(hits[0]["query"], "IE00B4L5Y983")

    def test_search_without_support_gives_clear_error(self):
        sys.modules["yfinance"] = types.SimpleNamespace()  # an old version without Search
        with self.assertRaises(RuntimeError):
            YahooSource().search("anything")

    def test_missing_library_gives_clear_error(self):
        sys.modules["yfinance"] = None  # makes "import yfinance" fail
        with self.assertRaises(ImportError):
            YahooSource().fetch("EUNL.DE", "2020-01-01")


class TestCache(unittest.TestCase):
    def test_safe_name(self):
        self.assertEqual(safe_name("^VIX"), "_VIX")
        self.assertEqual(safe_name("EUNL.DE"), "EUNL.DE")

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = cache_path(Path(tmp), "fake", "EUNL.DE")
            original = make_prices(start="2024-01-01")
            write_cache(original, path)
            loaded = read_cache(path)
            pd.testing.assert_frame_equal(original, loaded, check_freq=False, check_index_type=False, check_dtype=False)

    def test_read_missing_file_returns_none(self):
        self.assertIsNone(read_cache(Path("/nonexistent/file.csv")))

    def test_freshness_follows_file_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.csv"
            path.write_text("x")
            self.assertTrue(is_fresh(path, max_age_days=1))
            old = time.time() - 3 * 86400
            os.utime(path, (old, old))
            self.assertFalse(is_fresh(path, max_age_days=1))
            self.assertFalse(is_fresh(Path(tmp) / "missing.csv", max_age_days=1))

    def test_load_or_fetch_uses_cache_then_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = FakeSource()
            _, origin1 = load_or_fetch(source, "S", "2024-01-01", Path(tmp), 1)
            _, origin2 = load_or_fetch(source, "S", "2024-01-01", Path(tmp), 1)
            _, origin3 = load_or_fetch(source, "S", "2024-01-01", Path(tmp), 1, refresh=True)
            self.assertEqual((origin1, origin2, origin3), ("download", "cache", "download"))
            self.assertEqual(source.calls, 2)

    def test_currency_is_asked_once_then_read_from_the_side_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = FakeSource()
            first = load_currency(source, "EUNL.DE", Path(tmp))
            second = load_currency(source, "EUNL.DE", Path(tmp))
            self.assertEqual((first, second), ("EUR", "EUR"))
            self.assertEqual(source.currency_calls, 1)

    def test_unknown_currency_is_not_stored(self):
        class NoCurrency(FakeSource):
            def currency(self, symbol):
                return None

        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(load_currency(NoCurrency(), "X", Path(tmp)))
            self.assertFalse(list(Path(tmp).rglob("*.meta.json")))

    def test_yahoo_currency_reads_fast_info(self):
        class FakeTicker:
            def __init__(self, symbol):
                self.fast_info = {"currency": "USD"}

        sys.modules["yfinance"] = types.SimpleNamespace(Ticker=FakeTicker)
        self.assertEqual(YahooSource().currency("IB01.L"), "USD")

    def test_yahoo_currency_failure_returns_none(self):
        sys.modules["yfinance"] = None  # the library cannot be imported
        self.assertIsNone(YahooSource().currency("IB01.L"))

    def test_empty_download_is_not_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = FakeSource(empty=True)
            load_or_fetch(source, "S", "2024-01-01", Path(tmp), 1)
            self.assertFalse(cache_path(Path(tmp), "fake", "S").exists())


if __name__ == "__main__":
    unittest.main()
