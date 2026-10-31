"""Tests for prm.data.quality (synthetic data, no network)."""

import unittest

import pandas as pd

from helpers import make_prices
from prm.data.quality import check_prices

TODAY = pd.Timestamp("2026-10-29")
KWARGS = dict(max_daily_move=0.12, max_gap_days=7, max_stale_days=5, today=TODAY)


class TestCheckPrices(unittest.TestCase):
    def test_clean_series_is_ok(self):
        report = check_prices(make_prices(), "X", min_history_years=5, **KWARGS)
        self.assertEqual(report.status, "ok", report.codes)
        self.assertGreater(report.history_years, 11)

    def test_empty_is_error(self):
        report = check_prices(make_prices().iloc[0:0], "X", **KWARGS)
        self.assertEqual(report.status, "error")
        self.assertIn("empty", report.codes)

    def test_duplicate_dates_are_error(self):
        df = make_prices()
        df = pd.concat([df, df.iloc[[5]]])
        report = check_prices(df, "X", **KWARGS)
        self.assertEqual(report.status, "error")
        self.assertIn("duplicate_dates", report.codes)

    def test_non_positive_price_is_error(self):
        df = make_prices()
        df.iloc[10, df.columns.get_loc("close")] = -1.0
        report = check_prices(df, "X", **KWARGS)
        self.assertIn("non_positive_price", report.codes)
        self.assertEqual(report.status, "error")

    def test_large_daily_move_is_warning(self):
        df = make_prices()
        df.iloc[100:, df.columns.get_loc("adj_close")] *= 1.3  # one +30% jump
        report = check_prices(df, "X", **KWARGS)
        self.assertIn("large_daily_move", report.codes)
        self.assertEqual(report.status, "warning")

    def test_gap_is_warning(self):
        df = make_prices()
        df = df.drop(df.index[200:215])  # about three weeks without data
        report = check_prices(df, "X", **KWARGS)
        self.assertIn("gaps", report.codes)

    def test_stale_prices_are_warning(self):
        df = make_prices()
        for col in ("close", "adj_close"):
            df.iloc[300:310, df.columns.get_loc(col)] = df.iloc[300][col]
        report = check_prices(df, "X", **KWARGS)
        self.assertIn("stale_prices", report.codes)
        message = next(i.message for i in report.issues if i.code == "stale_prices")
        self.assertIn("longest 10 days", message)  # rows 300-309 are identical

    def test_short_history_is_warning(self):
        df = make_prices(start="2024-10-01")
        report = check_prices(df, "X", min_history_years=5, **KWARGS)
        self.assertIn("short_history", report.codes)

    def test_old_last_date_is_warning(self):
        df = make_prices(end="2026-09-01")
        report = check_prices(df, "X", **KWARGS)
        self.assertIn("stale_last_date", report.codes)

    def test_missing_values_are_warning(self):
        df = make_prices()
        df.iloc[50:53, df.columns.get_loc("adj_close")] = float("nan")
        report = check_prices(df, "X", **KWARGS)
        self.assertIn("missing_values", report.codes)


if __name__ == "__main__":
    unittest.main()
