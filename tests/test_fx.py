"""Tests for prm.fx (NBP rates, PLN returns) and stage 03. No network."""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from prm.fx.nbp import NbpSource, load_rates, parse_rates, windows
from prm.fx.returns import align_fx, decompose, fx_variance_share, simple_from_log, summarise


def series(values, start="2020-01-01", name=None):
    idx = pd.bdate_range(start, periods=len(values), name="date")
    return pd.Series(values, index=idx, dtype="float64", name=name)


class TestNbp(unittest.TestCase):
    def test_windows_cover_the_period_without_gaps_or_overlaps(self):
        start, end = date(2010, 1, 1), date(2026, 11, 1)
        ws = windows(start, end)
        self.assertEqual(ws[0][0], start)
        self.assertEqual(ws[-1][1], end)
        for (a1, b1), (a2, _) in zip(ws, ws[1:]):
            self.assertEqual((a2 - b1).days, 1)
        self.assertTrue(all((b - a).days + 1 <= 360 for a, b in ws))

    def test_windows_single_day(self):
        self.assertEqual(windows(date(2024, 1, 2), date(2024, 1, 2)), [(date(2024, 1, 2), date(2024, 1, 2))])

    def test_parse_rates(self):
        payload = {"table": "A", "currency": "euro", "code": "EUR", "rates": [
            {"no": "1/A/NBP/2024", "effectiveDate": "2024-01-02", "mid": 4.35},
            {"no": "2/A/NBP/2024", "effectiveDate": "2024-01-03", "mid": 4.36}]}
        s = parse_rates(payload)
        self.assertEqual(list(s.values), [4.35, 4.36])
        self.assertEqual(s.index[0], pd.Timestamp("2024-01-02"))
        self.assertEqual(len(parse_rates({"rates": []})), 0)

    def test_cache_is_used_the_second_time_and_empty_is_not_cached(self):
        class Fake:
            calls = 0

            def fetch(self, code, start, end):
                Fake.calls += 1
                return series([4.3, 4.31], "2024-01-02")

        class Empty:
            def fetch(self, code, start, end):
                return pd.Series(dtype="float64", index=pd.DatetimeIndex([], name="date"))

        with tempfile.TemporaryDirectory() as tmp:
            args = (date(2024, 1, 1), date(2024, 1, 10), Path(tmp), 1)
            _, first = load_rates(Fake(), "eur", *args)
            _, second = load_rates(Fake(), "EUR", *args)
            self.assertEqual((first, second, Fake.calls), ("download", "cache", 1))
            load_rates(Empty(), "USD", *args)
            self.assertFalse((Path(tmp) / "nbp" / "USDPLN.csv").exists())
            with self.assertRaises(ValueError):
                load_rates(Fake(), "PLN", *args)


class TestReturns(unittest.TestCase):
    def test_align_fx_never_uses_a_future_rate(self):
        fx = pd.Series([4.0, 5.0], index=pd.to_datetime(["2024-01-02", "2024-01-05"]))
        dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
        self.assertEqual(list(align_fx(fx, pd.DatetimeIndex(dates)).values), [4.0, 4.0, 4.0, 5.0])

    def test_align_fx_before_first_rate_is_missing(self):
        fx = pd.Series([4.0], index=pd.to_datetime(["2024-01-05"]))
        out = align_fx(fx, pd.DatetimeIndex(pd.to_datetime(["2024-01-02"])))
        self.assertTrue(out.isna().all())

    def test_identity_pln_equals_local_times_fx(self):
        rng = np.random.default_rng(0)
        price = series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))))
        fx = series(4.3 * np.exp(np.cumsum(rng.normal(0, 0.004, 300))))
        d = decompose(price, fx)
        simple = simple_from_log(d)
        self.assertTrue(np.allclose(1 + simple["pln"], (1 + simple["local"]) * (1 + simple["fx"])))
        # and it matches a direct computation on PLN prices
        direct = (price * fx).pct_change().dropna()
        self.assertTrue(np.allclose(simple["pln"], direct.reindex(simple.index)))

    def test_pln_asset_has_zero_fx_part(self):
        price = series([100, 101, 102, 101, 103])
        d = decompose(price, None)
        self.assertTrue((d["fx"] == 0).all())
        self.assertTrue(np.allclose(d["pln"], d["local"]))

    def test_holiday_gap_in_prices_does_not_create_fake_returns(self):
        price = series([100, 101, np.nan, 103, 104])   # one missing day (another exchange's holiday)
        fx = series([4.0] * 5)
        d = decompose(price, fx)
        self.assertEqual(len(d), 3)                    # 4 prices -> 3 returns, none missing or zero
        self.assertAlmostEqual(simple_from_log(d["local"]).iloc[1], 103 / 101 - 1)

    def test_variance_shares_in_extreme_cases(self):
        rng = np.random.default_rng(1)
        n = 500
        noise = series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))))
        flat_price = series([100.0] * n)
        flat_fx = series([4.3] * n)
        moving_fx = series(4.3 * np.exp(np.cumsum(rng.normal(0, 0.005, n))))
        self.assertAlmostEqual(fx_variance_share(decompose(noise, flat_fx)), 0.0, places=9)
        # constant local price + moving fx: all variance is FX
        fx_only = pd.DataFrame({"local": 0.0, "fx": np.log(moving_fx).diff().dropna()})
        fx_only["pln"] = fx_only["fx"]
        self.assertAlmostEqual(fx_variance_share(fx_only), 1.0, places=9)
        # local + fx shares always add up to 1
        d = decompose(noise, moving_fx)
        local_share = d["pln"].cov(d["local"]) / d["pln"].var()
        self.assertAlmostEqual(local_share + fx_variance_share(d), 1.0, places=9)
        self.assertTrue(np.isnan(fx_variance_share(decompose(flat_price, flat_fx))))   # no variance: undefined

    def test_hedging_currency_gives_negative_share(self):
        rng = np.random.default_rng(2)
        local_ret = rng.normal(0, 0.01, 800)
        fx_ret = -0.5 * local_ret + rng.normal(0, 0.002, 800)   # currency rises when the asset falls
        price = series(100 * np.exp(np.cumsum(local_ret)))
        fx = series(4.3 * np.exp(np.cumsum(fx_ret)))
        self.assertLess(fx_variance_share(decompose(price, fx)), 0)

    def test_summarise_has_expected_keys(self):
        rng = np.random.default_rng(3)
        price = series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 1000))))
        fx = series(4.3 * np.exp(np.cumsum(rng.normal(0, 0.004, 1000))))
        s = summarise(decompose(price, fx))
        self.assertAlmostEqual(s["vol_local_ann"], 0.01 * np.sqrt(252), delta=0.02)
        for key in ("n_obs", "vol_fx_ann", "vol_pln_ann", "corr_local_fx", "fx_share_full", "fx_share_last3y"):
            self.assertIn(key, s)


class FakeNbp(NbpSource):
    def fetch(self, code, start, end):
        rng = np.random.default_rng(10 if code == "EUR" else 11)
        idx = pd.bdate_range(start, end, name="date")
        base = 4.3 if code == "EUR" else 3.9
        return pd.Series(base * np.exp(np.cumsum(rng.normal(0, 0.004, len(idx)))), index=idx)


class TestStage03(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.processed = self.tmp / "processed"
        self.processed.mkdir()
        (self.tmp / "settings.yaml").write_text(
            f'data:\n  start_date: "2020-01-01"\n  raw_dir: {self.tmp / "raw"}\n  processed_dir: {self.processed}\n'
            "  max_cache_age_days: 1\nquality:\n  max_daily_move: 0.12\n  max_gap_days: 7\n  max_stale_days: 5\n")
        rng = np.random.default_rng(0)
        idx = pd.bdate_range("2020-01-01", "2024-12-31", name="date")
        prices = pd.DataFrame({k: 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx)))) for k in ("eur_etf", "usd_etf", "pln_etf", "nocur")}, index=idx)
        prices.loc[prices.index[10], "eur_etf"] = np.nan
        prices.to_csv(self.processed / "prices_selected.csv")
        pd.DataFrame({"asset_id": ["eur_etf", "usd_etf", "pln_etf", "nocur"],
                      "currency": ["EUR", "USD", "PLN", np.nan]}).to_csv(self.processed / "quality_report.csv", index=False)

    def run_stage(self, extra=()):
        spec = importlib.util.spec_from_file_location("stage03", Path(__file__).resolve().parents[1] / "pipeline" / "03_fx_returns.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = module.main(["--settings", str(self.tmp / "settings.yaml"), *extra], source=FakeNbp(), today=date(2024, 12, 31))
        return code, buf.getvalue()

    def test_end_to_end(self):
        code, output = self.run_stage()
        self.assertEqual(code, 0)
        pln = pd.read_csv(self.processed / "returns_pln.csv", index_col="date", parse_dates=True)
        local = pd.read_csv(self.processed / "returns_local.csv", index_col="date", parse_dates=True)
        self.assertEqual(sorted(pln.columns), ["eur_etf", "pln_etf", "usd_etf"])   # 'nocur' skipped
        self.assertTrue(np.allclose(pln["pln_etf"].dropna(), local["pln_etf"].dropna()))   # PLN asset: no FX effect
        self.assertFalse(np.allclose(pln["eur_etf"].dropna(), local["eur_etf"].dropna()))
        rates = pd.read_csv(self.processed / "fx_rates.csv", index_col="date")
        self.assertEqual(sorted(rates.columns), ["EUR", "USD"])
        table = pd.read_csv(self.processed / "fx_decomposition.csv").set_index("asset_id")
        self.assertAlmostEqual(table.loc["pln_etf", "fx_share_full"], 0.0)
        self.assertIn("nocur", output)

    def test_missing_input_returns_error(self):
        (self.processed / "prices_selected.csv").unlink()
        code, _ = self.run_stage()
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
