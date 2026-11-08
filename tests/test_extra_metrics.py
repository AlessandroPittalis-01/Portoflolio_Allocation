"""Tests for prm.risk.extra_metrics and stage 13 (synthetic data)."""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from prm.risk.extra_metrics import (
    component_es, dar_cdar, diversification_ratio, drawdown_depths, effective_risk_bets, stress_correlation, ulcer_index,
)
from prm.risk.metrics import hist_var_es


def series(values):
    return pd.Series(values, index=pd.bdate_range("2020-01-01", periods=len(values)))


class TestDrawdownMetrics(unittest.TestCase):
    def test_depths_ulcer_and_cdar_on_a_known_path(self):
        r = series([0.10, -0.10, -0.10, 0.0, 0.25] + [0.0] * 20)
        d = drawdown_depths(r)
        self.assertAlmostEqual(d.iloc[0], 0.0)
        self.assertAlmostEqual(d.iloc[1], 0.10)
        self.assertAlmostEqual(d.iloc[2], 1 - 0.9 * 0.9)
        self.assertAlmostEqual(ulcer_index(r), float(np.sqrt((d ** 2).mean())))
        dar, cdar = dar_cdar(r, 0.95)
        self.assertGreaterEqual(cdar, dar)
        self.assertLessEqual(dar, d.max() + 1e-12)

    def test_no_drawdown_gives_zero(self):
        r = series([0.001] * 100)
        self.assertEqual(dar_cdar(r)[1], 0.0)
        self.assertEqual(ulcer_index(r), 0.0)

    def test_short_series_is_nan(self):
        self.assertTrue(np.isnan(dar_cdar(series([0.01] * 5))[0]))


class TestDiversification(unittest.TestCase):
    def test_ratio_one_for_perfect_correlation_and_larger_otherwise(self):
        cov1 = pd.DataFrame([[4e-4, 2e-4], [2e-4, 1e-4]], index=["a", "b"], columns=["a", "b"])       # rho = 1
        w = pd.Series({"a": 0.5, "b": 0.5})
        self.assertAlmostEqual(diversification_ratio(w, cov1), 1.0, places=9)
        cov0 = pd.DataFrame(np.diag([4e-4, 1e-4]), index=["a", "b"], columns=["a", "b"])
        self.assertGreater(diversification_ratio(w, cov0), 1.1)

    def test_effective_bets(self):
        self.assertAlmostEqual(effective_risk_bets(pd.Series([0.25] * 4)), 4.0)
        self.assertAlmostEqual(effective_risk_bets(pd.Series([1.0, 0.0, 0.0])), 1.0)
        self.assertTrue(1.0 < effective_risk_bets(pd.Series([0.7, 0.2, 0.1])) < 3.0)


class TestComponentEs(unittest.TestCase):
    def test_components_add_up_to_the_portfolio_es(self):
        rng = np.random.default_rng(0)
        df = pd.DataFrame(rng.normal(0, 0.01, (3000, 3)), columns=list("abc"))
        w = pd.Series({"a": 0.5, "b": 0.3, "c": 0.2})
        out = component_es(df, w, 0.95)
        self.assertAlmostEqual(float(out["component_es"].sum()), hist_var_es(df @ w, 0.95)[1], places=12)
        self.assertAlmostEqual(float(out["share_of_es"].sum()), 1.0, places=12)

    def test_a_hedge_has_negative_component(self):
        rng = np.random.default_rng(1)
        x = rng.normal(0, 0.01, 4000)
        df = pd.DataFrame({"risk": x, "hedge": -0.5 * x + rng.normal(0, 0.002, 4000)})
        out = component_es(df, pd.Series({"risk": 0.5, "hedge": 0.5}), 0.95)
        self.assertLess(out.loc["hedge", "component_es"], 0)


class TestStressCorrelation(unittest.TestCase):
    def test_constant_relation_gives_adjusted_close_to_the_normal_correlation(self):
        rng = np.random.default_rng(2)
        m = pd.Series(rng.normal(0, 0.01, 20000))
        y = 0.8 * m + rng.normal(0, 0.006, 20000)
        out = stress_correlation(pd.DataFrame({"y": y}), m, 0.10)
        self.assertLess(out.loc["y", "corr_stress_raw"], out.loc["y", "corr_all"])          # selection lowers it
        self.assertAlmostEqual(out.loc["y", "corr_stress_adjusted"], out.loc["y", "corr_all"], delta=0.03)

    def test_a_real_break_is_detected(self):
        rng = np.random.default_rng(3)
        m = pd.Series(rng.normal(0, 0.01, 20000))
        slope = np.where(m <= m.quantile(0.10), 1.6, 0.4)                                   # the asset follows the market more in stress
        y = slope * m + rng.normal(0, 0.004, 20000)
        out = stress_correlation(pd.DataFrame({"y": y}), m, 0.10)
        self.assertGreater(out.loc["y", "change"], 0.05)
        self.assertAlmostEqual(out.attrs["n_stress_days"], 2000, delta=5)

    def test_too_few_days(self):
        with self.assertRaises(ValueError):
            stress_correlation(pd.DataFrame({"y": np.arange(50.0)}), pd.Series(np.arange(50.0)), 0.10)


class TestStage13(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.processed = self.tmp / "processed"
        self.processed.mkdir()
        (self.tmp / "settings.yaml").write_text(
            f'data:\n  start_date: "2018-01-01"\n  raw_dir: {self.tmp / "raw"}\n  processed_dir: {self.processed}\n'
            "  max_cache_age_days: 1\nquality:\n  max_daily_move: 0.12\n  max_gap_days: 7\n  max_stale_days: 5\n")
        (self.tmp / "factors.yaml").write_text("factors: {market: eq, rates: bd, fx: EURPLN}\nfx_reference_asset: bd\n")
        rng = np.random.default_rng(4)
        idx = pd.bdate_range("2017-01-02", periods=1500, name="date")
        local = pd.DataFrame({"eq": rng.normal(0.0003, 0.009, 1500), "bd": rng.normal(0.0001, 0.003, 1500),
                              "gd": rng.normal(0.0002, 0.008, 1500)}, index=idx)
        fx = rng.normal(0, 0.0035, 1500)
        pln = (1 + local).mul(1 + fx, axis=0) - 1
        local.to_csv(self.processed / "returns_local.csv")
        pln.to_csv(self.processed / "returns_pln.csv")
        pd.DataFrame({"eq": [0.4], "bd": [0.5], "gd": [0.1]}, index=pd.Index(["risk_budget"], name="method")).to_csv(
            self.processed / "allocation_weights.csv")

    def run_stage(self, extra=()):
        path = Path(__file__).resolve().parents[1] / "pipeline" / "13_risk_extras.py"
        spec = importlib.util.spec_from_file_location("stage13", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = module.main(["--settings", str(self.tmp / "settings.yaml"), "--factors", str(self.tmp / "factors.yaml"), *extra])
        return code, buf.getvalue()

    def test_end_to_end(self):
        code, out = self.run_stage()
        self.assertEqual(code, 0, out)
        s = pd.read_csv(self.processed / "risk_extras_summary.csv", index_col="metric")
        for m in ("dar_95", "cdar_95", "ulcer_index", "diversification_ratio", "effective_risk_bets", "es_95_daily"):
            self.assertIn(m, s.index)
        self.assertGreaterEqual(s.loc["diversification_ratio", "value"], 1.0)
        c = pd.read_csv(self.processed / "risk_extras_assets.csv", index_col="asset_id")
        self.assertAlmostEqual(float(c["share_of_es"].sum()), 1.0, places=6)
        self.assertAlmostEqual(float(c["risk_share_vol"].sum()), 1.0, places=6)
        self.assertIn("corr_stress_adjusted", c.columns)

    def test_errors(self):
        code, out = self.run_stage(["--method", "nope"])
        self.assertEqual((code, "Unknown method" in out), (1, True))
        (self.processed / "returns_pln.csv").unlink()
        code, out = self.run_stage()
        self.assertEqual((code, "Missing" in out), (1, True))


if __name__ == "__main__":
    unittest.main()
