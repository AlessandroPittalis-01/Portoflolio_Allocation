"""Tests for prm.risk.var_backtest (synthetic data, fixed seeds)."""

import math
import unittest

import numpy as np
import pandas as pd
from scipy import stats

from prm.risk.var_backtest import (
    MODELS, backtest_model, christoffersen_independence, conditional_coverage, es_checks, kupiec_pof, rolling_forecasts,
    tick_loss, traffic_light,
)
from test_var_models import garch_series


class TestKupiec(unittest.TestCase):
    def test_exact_coverage_has_zero_statistic(self):
        k = kupiec_pof(25, 2500, 0.01)
        self.assertAlmostEqual(k["lr"], 0.0, places=9)
        self.assertAlmostEqual(k["p_value"], 1.0)

    def test_known_value(self):                       # 10 exceptions in 250 days at 99%: LR = 2 * (ll1 - ll0)
        k = kupiec_pof(10, 250, 0.01)
        ph = 10 / 250
        lr = -2 * (240 * math.log(0.99) + 10 * math.log(0.01) - 240 * math.log(1 - ph) - 10 * math.log(ph))
        self.assertAlmostEqual(k["lr"], lr, places=9)
        self.assertLess(k["p_value"], 0.01)

    def test_zero_exceptions_is_testable_and_too_few_is_rejected_eventually(self):
        self.assertGreater(kupiec_pof(0, 100, 0.01)["p_value"], 0.05)
        self.assertLess(kupiec_pof(0, 2500, 0.01)["p_value"], 0.001)
        with self.assertRaises(ValueError):
            kupiec_pof(5, 0, 0.01)


class TestIndependence(unittest.TestCase):
    def test_clustered_hits_are_rejected_and_spread_hits_are_not(self):
        clustered = np.zeros(1000, dtype=int)
        for s in range(50, 1000, 100):
            clustered[s:s + 4] = 1                                    # 4 hits in a row, 10 times
        self.assertLess(christoffersen_independence(clustered)["p_value"], 0.001)
        spread = np.zeros(1000, dtype=int)
        spread[::50] = 1
        self.assertGreater(christoffersen_independence(spread)["p_value"], 0.05)

    def test_untestable_series_gives_nan(self):
        self.assertTrue(math.isnan(christoffersen_independence(np.zeros(100, dtype=int))["p_value"]))

    def test_conditional_coverage_adds_the_statistics(self):
        cc = conditional_coverage({"lr": 2.0, "p_value": 0.2}, {"lr": 3.0, "p_value": 0.1})
        self.assertAlmostEqual(cc["lr"], 5.0)
        self.assertAlmostEqual(cc["p_value"], float(stats.chi2.sf(5.0, 2)))


class TestTrafficLight(unittest.TestCase):
    def test_basel_zones_for_250_days_at_99(self):
        self.assertEqual(traffic_light(4, 250, 0.01), "green")
        self.assertEqual(traffic_light(5, 250, 0.01), "yellow")
        self.assertEqual(traffic_light(9, 250, 0.01), "yellow")
        self.assertEqual(traffic_light(10, 250, 0.01), "red")


class TestForecasts(unittest.TestCase):
    R = garch_series(1400, seed=11)

    def test_no_look_ahead(self):
        for model in ("historical", "gaussian", "gaussian_ewma", "fhs_ewma"):
            base = rolling_forecasts(self.R, model, 0.99, 500)
            r2 = self.R.copy()
            r2.iloc[900] = -0.3                                        # one huge day
            alt = rolling_forecasts(r2, model, 0.99, 500)
            d = self.R.index[900]
            self.assertEqual(base.loc[d, "var"], alt.loc[d, "var"], model)          # forecast of that day unchanged
            nxt = self.R.index[901]
            self.assertGreater(alt.loc[nxt, "var"], base.loc[nxt, "var"] - 1e-15, model)

    def test_garch_forecast_has_no_look_ahead(self):
        r = self.R.iloc[:800]
        base = rolling_forecasts(r, "gaussian_garch", 0.99, 500, refit_every=100)
        r2 = r.copy()
        r2.iloc[700] = -0.3
        alt = rolling_forecasts(r2, "gaussian_garch", 0.99, 500, refit_every=100)
        d = r.index[700]
        self.assertEqual(base.loc[d, "var"], alt.loc[d, "var"])

    def test_shapes_and_signs(self):
        for model in MODELS:
            fc = rolling_forecasts(self.R.iloc[:900], model, 0.95, 500, refit_every=100)
            self.assertEqual(len(fc), 400)
            self.assertTrue((fc["var"] > 0).all(), model)
            self.assertTrue((fc["es"] >= fc["var"] - 1e-12).all(), model)

    def test_unknown_model_and_short_series(self):
        with self.assertRaises(ValueError):
            rolling_forecasts(self.R, "nope")
        with self.assertRaises(ValueError):
            rolling_forecasts(self.R.iloc[:200], "historical", 0.99, 250)


class TestBacktestModel(unittest.TestCase):
    def test_a_correct_model_is_not_rejected_and_a_blind_one_is(self):
        rng = np.random.default_rng(5)
        r = pd.Series(rng.normal(0, 0.01, 3000), index=pd.bdate_range("2005-01-03", periods=3000))
        good = backtest_model(r, "gaussian", 0.99, 500)
        self.assertGreater(good["kupiec_p"], 0.01)
        self.assertEqual(good["n_obs"], 2500)
        calm_then_storm = pd.concat([pd.Series(rng.normal(0, 0.003, 1500)), pd.Series(rng.normal(0, 0.02, 1500))], ignore_index=True)
        calm_then_storm.index = pd.bdate_range("2005-01-03", periods=3000)
        bad = backtest_model(calm_then_storm, "historical", 0.99, 500)       # a 500-day memory is slow after the break
        self.assertGreater(bad["exceptions"], bad["expected"])
        self.assertEqual(bad["zone"], "red")

    def test_ewma_reacts_faster_than_gaussian_on_garch_data(self):
        r = garch_series(3000, seed=21)
        g = backtest_model(r, "gaussian", 0.99, 500)
        e = backtest_model(r, "gaussian_ewma", 0.99, 500)
        self.assertLess(e["tick_loss"], g["tick_loss"])                    # volatility clustering is exploited

    def test_es_checks_and_tick_loss(self):
        fc = pd.DataFrame({"var": [1.0] * 10, "es": [1.5] * 10, "loss": [2.0, 2.0, 2.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]})
        c = es_checks(fc)
        self.assertAlmostEqual(c["es_ratio"], 2.0 / 1.5)
        self.assertTrue(math.isnan(es_checks(fc.iloc[3:])["es_ratio"]))
        self.assertGreater(tick_loss(fc, 0.99), 0)


if __name__ == "__main__":
    unittest.main()


# ---- stage 10 ---------------------------------------------------------------------------------------------
import contextlib  # noqa: E402
import importlib.util  # noqa: E402
import io  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402


class TestStage10(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.processed = self.tmp / "processed"
        self.processed.mkdir()
        (self.tmp / "settings.yaml").write_text(
            f'data:\n  start_date: "2018-01-01"\n  raw_dir: {self.tmp / "raw"}\n  processed_dir: {self.processed}\n'
            "  max_cache_age_days: 1\nquality:\n  max_daily_move: 0.12\n  max_gap_days: 7\n  max_stale_days: 5\n")
        r = garch_series(1100, seed=4)
        pd.DataFrame({"risk_budget": r.to_numpy(), "equal_weight": r.to_numpy() * 1.1}, index=r.index.rename("date")).to_csv(
            self.processed / "backtest_returns_full.csv")

    def run_stage(self, extra=()):
        path = Path(__file__).resolve().parents[1] / "pipeline" / "10_var_backtest.py"
        spec = importlib.util.spec_from_file_location("stage10", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = module.main(["--settings", str(self.tmp / "settings.yaml"), "--window", "400", "--refit-every", "120", *extra])
        return code, buf.getvalue()

    def test_end_to_end(self):
        code, out = self.run_stage()
        self.assertEqual(code, 0, out)
        t = pd.read_csv(self.processed / "var_backtest.csv")
        self.assertEqual(len(t), 2 * len(MODELS))
        self.assertTrue((t["n_obs"] == 700).all())
        self.assertTrue((t["exceptions"] >= 0).all())
        self.assertIn("ok", t.columns)

    def test_errors(self):
        code, out = self.run_stage(["--method", "nope"])
        self.assertEqual(code, 1)
        self.assertIn("Unknown strategy", out)
        code, out = self.run_stage(["--window", "900"])
        self.assertEqual(code, 1)
        self.assertIn("too short", out)
        (self.processed / "backtest_returns_full.csv").unlink()
        code, out = self.run_stage()
        self.assertEqual(code, 1)
        self.assertIn("Missing", out)
