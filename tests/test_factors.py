"""Tests for prm.risk.factors and stage 11 (synthetic data)."""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from prm.risk.factors import (
    DEFAULT_FACTORS_PATH, FactorConfigError, build_factors, load_factor_config, ols, rolling_beta, sensitivities,
    variance_attribution,
)


def make_world(n=1500, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n, name="date")
    f = pd.DataFrame({"mkt": rng.normal(0, 0.009, n), "rate": rng.normal(0, 0.003, n), "fx": rng.normal(0, 0.0035, n)}, index=idx)
    noise = rng.normal(0, 0.001, n)
    y = 0.5 * f["mkt"] + 2.0 * f["rate"] - 0.3 * f["fx"] + noise
    return y, f, noise


class TestOls(unittest.TestCase):
    def test_recovers_known_betas(self):
        y, f, _ = make_world()
        fit = ols(y, f)
        self.assertAlmostEqual(fit["beta"]["mkt"], 0.5, delta=0.03)
        self.assertAlmostEqual(fit["beta"]["rate"], 2.0, delta=0.1)
        self.assertAlmostEqual(fit["beta"]["fx"], -0.3, delta=0.1)
        self.assertGreater(fit["r2"], 0.9)
        self.assertGreater(abs(fit["t"]["mkt"]), 10)

    def test_attribution_adds_up_to_one_and_negative_share_is_possible(self):
        y, f, _ = make_world()
        a = variance_attribution(y, f)
        self.assertAlmostEqual(float(a["share_of_variance"].sum()), 1.0, places=9)
        self.assertLess(a.loc["fx", "share_of_variance"] , a.loc["mkt", "share_of_variance"])
        self.assertLess(a.loc["fx", "share_of_variance"], 0.05)        # fx has a negative loading: it diversifies
        self.assertAlmostEqual(a.loc["residual", "share_of_variance"], (1 - ols(y, f)["r2"]), places=9)

    def test_sensitivities_table(self):
        y, f, _ = make_world()
        t = sensitivities(y, f)
        self.assertEqual(list(t.index), ["mkt", "rate", "fx"])
        self.assertAlmostEqual(t.loc["mkt", "one_sigma_month_move"], t.loc["mkt", "beta"] * f["mkt"].std() * np.sqrt(21), places=12)
        self.assertGreater(t.attrs["r2"], 0.9)

    def test_too_few_observations(self):
        y, f, _ = make_world(12)
        with self.assertRaises(ValueError):
            ols(y, f)

    def test_rolling_beta_shape_and_stable_when_truth_is_constant(self):
        y, f, _ = make_world(1800)
        rb = rolling_beta(y, f, window=504, step=126)
        self.assertEqual(list(rb.columns), ["mkt", "rate", "fx"])
        self.assertLess(rb["mkt"].max() - rb["mkt"].min(), 0.1)


class TestBuild(unittest.TestCase):
    def test_spread_fx_and_errors(self):
        idx = pd.bdate_range("2020-01-01", periods=5)
        local = pd.DataFrame({"a": [0.01] * 5, "b": [0.004] * 5}, index=idx)
        pln = (1 + local) * 1.002 - 1
        f = build_factors(local, pln, {"spread": "a - b", "level": "a", "fx": "EURPLN"}, "a")
        np.testing.assert_allclose(f["spread"], 0.006)
        np.testing.assert_allclose(f["level"], 0.01)
        np.testing.assert_allclose(f["fx"], 0.002, atol=1e-12)
        with self.assertRaises(FactorConfigError):
            build_factors(local, pln, {"x": "zzz"}, "a")
        with self.assertRaises(FactorConfigError):
            build_factors(local, pln, {"fx": "EURPLN"}, "missing")

    def test_real_config_and_bad_configs(self):
        cfg = load_factor_config(DEFAULT_FACTORS_PATH)
        self.assertIn("market", cfg["factors"])
        for text in ["factors: {a: x}\n", "factors: {a: x, b: ''}\n", "factors: {a: 'x - y - z', b: q}\n",
                     "factors: {a: EURPLN, b: q}\n"]:
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "f.yaml"
                p.write_text(text)
                with self.assertRaises(FactorConfigError):
                    load_factor_config(p)


class TestStage11(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.processed = self.tmp / "processed"
        self.processed.mkdir()
        (self.tmp / "settings.yaml").write_text(
            f'data:\n  start_date: "2018-01-01"\n  raw_dir: {self.tmp / "raw"}\n  processed_dir: {self.processed}\n'
            "  max_cache_age_days: 1\nquality:\n  max_daily_move: 0.12\n  max_gap_days: 7\n  max_stale_days: 5\n")
        (self.tmp / "factors.yaml").write_text(
            "factors: {market: eq, rates: bd, credit: cr - bd, fx: EURPLN}\nfx_reference_asset: bd\n")
        rng = np.random.default_rng(2)
        idx = pd.bdate_range("2018-01-01", periods=1500, name="date")
        local = pd.DataFrame({"eq": rng.normal(0.0003, 0.009, 1500), "bd": rng.normal(0.0001, 0.003, 1500),
                              "cr": rng.normal(0.0002, 0.0035, 1500)}, index=idx)
        fx = rng.normal(0, 0.0035, 1500)
        pln = (1 + local).mul(1 + fx, axis=0) - 1
        local.to_csv(self.processed / "returns_local.csv")
        pln.to_csv(self.processed / "returns_pln.csv")
        pd.DataFrame({"eq": [0.4, 0.3], "bd": [0.4, 0.5], "cr": [0.2, 0.2]}, index=pd.Index(["risk_budget", "hrp"], name="method")).to_csv(
            self.processed / "allocation_weights.csv")

    def run_stage(self, extra=()):
        path = Path(__file__).resolve().parents[1] / "pipeline" / "11_risk_factors.py"
        spec = importlib.util.spec_from_file_location("stage11", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = module.main(["--settings", str(self.tmp / "settings.yaml"), "--factors", str(self.tmp / "factors.yaml"), *extra])
        return code, buf.getvalue()

    def test_end_to_end(self):
        code, out = self.run_stage()
        self.assertEqual(code, 0, out)
        t = pd.read_csv(self.processed / "risk_factors.csv", index_col=0)
        self.assertEqual(set(t.index), {"market", "rates", "credit", "fx", "residual"})
        self.assertAlmostEqual(float(t["share_of_variance"].sum()), 1.0, places=6)
        self.assertGreater(t.loc["market", "share_of_variance"], 0.3)           # equity dominates a 40% equity portfolio
        self.assertTrue((self.processed / "risk_factors_rolling.csv").exists())

    def test_errors(self):
        code, out = self.run_stage(["--method", "nope"])
        self.assertEqual((code, "Unknown method" in out), (1, True))
        (self.processed / "returns_local.csv").unlink()
        code, out = self.run_stage()
        self.assertEqual((code, "Missing" in out), (1, True))


if __name__ == "__main__":
    unittest.main()
