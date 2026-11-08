"""Tests for prm.risk.var_models (synthetic data, fixed seeds)."""

import unittest

import numpy as np
import pandas as pd

from prm.risk.var_models import (
    ewma_sigma, fhs_var_es, fit_student_df, garch11_fit, mc_var_es, normal_var_es, simulate_returns, student_var_es,
)


def garch_series(n=4000, omega=2e-6, alpha=0.08, beta=0.90, seed=3):
    rng = np.random.default_rng(seed)
    x, var = np.empty(n), omega / (1 - alpha - beta)
    for t in range(n):
        x[t] = np.sqrt(var) * rng.standard_normal()
        var = omega + alpha * x[t] ** 2 + beta * var
    return pd.Series(x, index=pd.bdate_range("2005-01-03", periods=n))


class TestClosedForms(unittest.TestCase):
    def test_normal_reference_values(self):
        var, es = normal_var_es(0.01, 0.95)
        self.assertAlmostEqual(var, 0.01644854, places=6)
        self.assertAlmostEqual(es, 0.02062713, places=6)

    def test_student_tends_to_normal_and_has_fatter_tail_at_99(self):
        v_n, e_n = normal_var_es(0.01, 0.99)
        v_t, e_t = student_var_es(0.01, 1e5, 0.99)
        self.assertAlmostEqual(v_t, v_n, places=5)
        self.assertAlmostEqual(e_t, e_n, places=5)
        v4, e4 = student_var_es(0.01, 4, 0.99)
        self.assertGreater(e4, e_n)                         # fat tails: bigger ES at the same volatility
        with self.assertRaises(ValueError):
            student_var_es(0.01, 2.0)


class TestVolatility(unittest.TestCase):
    def test_ewma_has_no_look_ahead(self):
        r = garch_series(500)
        s1, _ = ewma_sigma(r)
        r2 = r.copy()
        r2.iloc[200] = 0.5                                   # change one day
        s2, _ = ewma_sigma(r2)
        self.assertEqual(s1.iloc[200], s2.iloc[200])         # the forecast for that day does not know it
        self.assertGreater(s2.iloc[201], s1.iloc[201])       # but the next day does

    def test_ewma_reacts_to_a_shock(self):
        r = pd.Series(np.random.default_rng(0).normal(0, 0.005, 400), index=pd.bdate_range("2020-01-01", periods=400))
        _, calm = ewma_sigma(r)
        r.iloc[-1] = -0.06
        _, after = ewma_sigma(r)
        self.assertGreater(after, 1.5 * calm)

    def test_garch_recovers_persistence(self):
        fit = garch11_fit(garch_series())
        self.assertAlmostEqual(fit["persistence"], 0.98, delta=0.02)
        self.assertGreater(fit["alpha"], 0.03)
        self.assertLess(fit["alpha"], 0.15)
        self.assertAlmostEqual(fit["long_run_vol_ann"], np.sqrt(2e-6 / 0.02 * 252), delta=0.03)
        self.assertEqual(len(fit["sigma"]), 4000)

    def test_too_short_series_is_rejected(self):
        with self.assertRaises(ValueError):
            ewma_sigma(pd.Series(np.zeros(20)))


class TestStudentFit(unittest.TestCase):
    def test_df_of_t_data_and_of_normal_data(self):
        rng = np.random.default_rng(1)
        self.assertAlmostEqual(fit_student_df(rng.standard_t(5, 20000)), 5.0, delta=0.6)
        self.assertGreater(fit_student_df(rng.standard_normal(20000)), 30)


class TestFHS(unittest.TestCase):
    def test_on_iid_normal_it_matches_the_gaussian(self):
        rng = np.random.default_rng(7)
        r = pd.Series(rng.normal(0, 0.01, 6000), index=pd.bdate_range("2000-01-03", periods=6000))
        out = fhs_var_es(r, 0.95, "ewma")
        var, es = normal_var_es(0.01, 0.95)
        self.assertAlmostEqual(out["var"], var, delta=0.003)       # EWMA noise in sigma_next, so a loose tolerance
        self.assertGreater(out["es"], out["var"])

    def test_var_rises_after_a_shock(self):
        r = garch_series(1500)
        calm = fhs_var_es(r, 0.99, "ewma")["var"]
        r.iloc[-1] = -0.07
        self.assertGreater(fhs_var_es(r, 0.99, "ewma")["var"], 1.3 * calm)

    def test_garch_variant_runs_and_is_positive(self):
        out = fhs_var_es(garch_series(2500), 0.99, "garch")
        self.assertGreater(out["var"], 0)
        self.assertGreater(out["es"], out["var"])
        with self.assertRaises(ValueError):
            fhs_var_es(garch_series(500), 0.99, "nope")


class TestMonteCarlo(unittest.TestCase):
    COV = pd.DataFrame([[1e-4, 2e-5], [2e-5, 4e-5]], index=["a", "b"], columns=["a", "b"])

    def test_simulated_covariance_matches_for_normal_and_t(self):
        for df in (None, 5.0):
            sims = simulate_returns(self.COV, 400_000, df, seed=1)
            np.testing.assert_allclose(np.cov(sims.T), self.COV.to_numpy(), rtol=0.05)

    def test_mc_matches_the_closed_forms(self):
        w = pd.Series({"a": 0.6, "b": 0.4})
        sigma = float(np.sqrt(w @ self.COV @ w))
        v, e = mc_var_es(w, self.COV, 0.99, 400_000, None, seed=2)
        vn, en = normal_var_es(sigma, 0.99)
        self.assertAlmostEqual(v, vn, delta=0.03 * vn)
        self.assertAlmostEqual(e, en, delta=0.04 * en)
        v5, e5 = mc_var_es(w, self.COV, 0.99, 400_000, 5.0, seed=2)
        vt, et = student_var_es(sigma, 5.0, 0.99)
        self.assertAlmostEqual(e5, et, delta=0.06 * et)
        self.assertGreater(e5, e)                                   # fat tails: larger ES at the same volatility

    def test_same_seed_same_result_and_bad_df(self):
        w = pd.Series({"a": 0.5, "b": 0.5})
        self.assertEqual(mc_var_es(w, self.COV, 0.95, 10_000, 4.0, seed=5), mc_var_es(w, self.COV, 0.95, 10_000, 4.0, seed=5))
        with self.assertRaises(ValueError):
            simulate_returns(self.COV, 100, 2.0)


if __name__ == "__main__":
    unittest.main()


# ---- stage 09 ---------------------------------------------------------------------------------------------
import contextlib  # noqa: E402
import importlib.util  # noqa: E402
import io  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402


class TestStage09(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.processed = self.tmp / "processed"
        self.processed.mkdir()
        (self.tmp / "settings.yaml").write_text(
            f'data:\n  start_date: "2018-01-01"\n  raw_dir: {self.tmp / "raw"}\n  processed_dir: {self.processed}\n'
            "  max_cache_age_days: 1\nquality:\n  max_daily_move: 0.12\n  max_gap_days: 7\n  max_stale_days: 5\n")
        idx = pd.bdate_range("2018-01-01", periods=1500, name="date")
        rng = np.random.default_rng(0)
        pd.DataFrame({"eq": garch_series(1500, seed=1).to_numpy() * 1.5, "bd": rng.normal(0, 0.003, 1500)}, index=idx).to_csv(
            self.processed / "returns_pln.csv")
        pd.DataFrame({"eq": [0.5, 0.4], "bd": [0.5, 0.6], "unused": [0.0, 0.0]}, index=pd.Index(["risk_budget", "hrp"], name="method")).to_csv(
            self.processed / "allocation_weights.csv")

    def run_stage(self, extra=()):
        path = Path(__file__).resolve().parents[1] / "pipeline" / "09_market_risk.py"
        spec = importlib.util.spec_from_file_location("stage09", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = module.main(["--settings", str(self.tmp / "settings.yaml"), "--paths", "20000", *extra])
        return code, buf.getvalue()

    def test_end_to_end(self):
        code, out = self.run_stage()
        self.assertEqual(code, 0, out)
        t = pd.read_csv(self.processed / "market_risk_var.csv")
        self.assertEqual(len(t), 16)                                        # 8 models x 2 levels
        self.assertTrue((t["es"] >= t["var"] - 1e-12).all())                # ES is never below VaR
        for model, sub in t.groupby("model"):
            lo, hi = sub[sub["level"] == 0.95].iloc[0], sub[sub["level"] == 0.99].iloc[0]
            self.assertGreater(hi["var"], lo["var"], model)                  # 99% is a larger loss than 95%

    def test_unknown_method_and_missing_input(self):
        code, out = self.run_stage(["--method", "nope"])
        self.assertEqual(code, 1)
        self.assertIn("Unknown method", out)
        (self.processed / "returns_pln.csv").unlink()
        code, out = self.run_stage()
        self.assertEqual(code, 1)
        self.assertIn("Missing", out)
