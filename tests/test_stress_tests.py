"""Tests for prm.risk.stress_tests and stage 12 (synthetic data)."""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from prm.risk.stress_tests import (
    DEFAULT_HYPOTHETICAL_PATH, StressConfigError, apply_shocks, direct_historical, factor_moves, load_hypothetical,
    reverse_stress,
)

SCEN = [{"id": "ep", "start": pd.Timestamp("2020-03-02"), "end": pd.Timestamp("2020-03-06")}]


class TestReverse(unittest.TestCase):
    BETA = pd.Series({"a": 0.5, "b": -0.2, "c": 1.0})
    COV = pd.DataFrame([[4e-4, 1e-4, 0.0], [1e-4, 2e-4, 5e-5], [0.0, 5e-5, 1e-4]], index=list("abc"), columns=list("abc"))

    def test_shock_hits_the_loss_exactly(self):
        r = reverse_stress(self.BETA, self.COV, 0.25, 21)
        self.assertAlmostEqual(float(self.BETA @ r["shock"]), -0.25, places=12)

    def test_it_is_the_most_plausible_shock(self):
        h = 21
        r = reverse_stress(self.BETA, self.COV, 0.25, h)
        S_inv = np.linalg.inv(self.COV.to_numpy() * h)
        best = float(r["shock"] @ S_inv @ r["shock"])
        self.assertAlmostEqual(best, r["distance"] ** 2, places=9)
        rng = np.random.default_rng(0)
        for _ in range(200):                                       # any other shock with the same loss is less plausible
            d = rng.normal(0, 0.2, 3)
            d = d * (-0.25 / float(self.BETA.to_numpy() @ d))
            self.assertGreaterEqual(float(d @ S_inv @ d), best - 1e-9)

    def test_scaling_with_loss_and_horizon(self):
        a = reverse_stress(self.BETA, self.COV, 0.10, 21)["distance"]
        b = reverse_stress(self.BETA, self.COV, 0.20, 21)["distance"]
        c = reverse_stress(self.BETA, self.COV, 0.10, 84)["distance"]
        self.assertAlmostEqual(b, 2 * a, places=12)
        self.assertAlmostEqual(c, a / 2, places=12)                # 4x the horizon: half the distance
        self.assertLess(reverse_stress(self.BETA, self.COV, 0.20, 21)["normal_prob"], reverse_stress(self.BETA, self.COV, 0.10, 21)["normal_prob"])

    def test_bad_inputs(self):
        with self.assertRaises(ValueError):
            reverse_stress(self.BETA, self.COV, 0.0, 21)
        with self.assertRaises(ValueError):
            reverse_stress(pd.Series({"a": 0.0, "b": 0.0, "c": 0.0}), self.COV, 0.1, 21)


class TestApply(unittest.TestCase):
    def test_linear_and_missing_factors(self):
        beta = pd.Series({"a": 0.5, "b": -0.2})
        r = apply_shocks(beta, pd.Series({"a": -0.3}))
        self.assertAlmostEqual(r["pnl"], -0.15)
        self.assertEqual(r["missing"], ["b"])
        r2 = apply_shocks(beta, pd.Series({"a": -0.3, "b": np.nan}))
        self.assertEqual(r2["missing"], ["b"])


class TestHistorical(unittest.TestCase):
    def test_direct_coverage_and_rescaling(self):
        idx = pd.bdate_range("2020-01-01", "2020-04-30")
        pln = pd.DataFrame({"old": 0.01, "new": 0.02}, index=idx)
        pln.loc[idx < "2020-03-10", "new"] = np.nan                   # 'new' did not exist yet in the window
        w = pd.Series({"old": 0.6, "new": 0.4})
        out = direct_historical(pln, w, SCEN)
        self.assertAlmostEqual(out.loc["ep", "coverage"], 0.6)
        self.assertEqual(out.loc["ep", "n_missing"], 1)
        self.assertAlmostEqual(out.loc["ep", "covered_return"], 1.01 ** 4 - 1, places=9)   # 4 trading days after the start

    def test_factor_moves_nan_when_no_history(self):
        idx = pd.bdate_range("2020-03-09", "2020-04-30")
        f = pd.DataFrame({"x": 0.01, "y": 0.0}, index=idx)
        m = factor_moves(f, SCEN)
        self.assertTrue(m.isna().all().all())


class TestConfig(unittest.TestCase):
    def test_real_file_loads_with_the_real_factors(self):
        from prm.risk.factors import DEFAULT_FACTORS_PATH, load_factor_config
        names = list(load_factor_config(DEFAULT_FACTORS_PATH)["factors"])
        scen = load_hypothetical(DEFAULT_HYPOTHETICAL_PATH, names)
        self.assertIn("equity_crash", scen)
        self.assertTrue(all(s["shocks"] for s in scen.values()))

    def test_bad_files(self):
        for text in ["scenarios: {}\n", "scenarios: {a: {description: x}}\n", "scenarios: {a: {zzz: -0.1}}\n",
                     "scenarios: {a: {market: -1.5}}\n", "scenarios: {a: {market: yes}}\n"]:
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "h.yaml"
                p.write_text(text)
                with self.assertRaises(StressConfigError):
                    load_hypothetical(p, ["market", "fx"])


class TestStage12(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.processed = self.tmp / "processed"
        self.processed.mkdir()
        (self.tmp / "settings.yaml").write_text(
            f'data:\n  start_date: "2018-01-01"\n  raw_dir: {self.tmp / "raw"}\n  processed_dir: {self.processed}\n'
            "  max_cache_age_days: 1\nquality:\n  max_daily_move: 0.12\n  max_gap_days: 7\n  max_stale_days: 5\n")
        (self.tmp / "factors.yaml").write_text("factors: {market: eq, rates: bd, fx: EURPLN}\nfx_reference_asset: bd\n")
        (self.tmp / "hypo.yaml").write_text("scenarios:\n  crash: {description: x, market: -0.3, fx: 0.05}\n  fxloss: {fx: -0.12}\n")
        (self.tmp / "scen.yaml").write_text("scenarios:\n  - {id: ep, start: 2019-03-01, end: 2019-03-29, description: x}\n")
        rng = np.random.default_rng(3)
        idx = pd.bdate_range("2017-01-02", periods=2000, name="date")
        local = pd.DataFrame({"eq": rng.normal(0.0003, 0.009, 2000), "bd": rng.normal(0.0001, 0.003, 2000)}, index=idx)
        fx = rng.normal(0, 0.0035, 2000)
        pln = (1 + local).mul(1 + fx, axis=0) - 1
        local.to_csv(self.processed / "returns_local.csv")
        pln.to_csv(self.processed / "returns_pln.csv")
        pd.DataFrame({"eq": [0.4], "bd": [0.6]}, index=pd.Index(["risk_budget"], name="method")).to_csv(self.processed / "allocation_weights.csv")

    def run_stage(self, extra=()):
        path = Path(__file__).resolve().parents[1] / "pipeline" / "12_stress.py"
        spec = importlib.util.spec_from_file_location("stage12", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = module.main(["--settings", str(self.tmp / "settings.yaml"), "--factors", str(self.tmp / "factors.yaml"),
                                "--hypothetical", str(self.tmp / "hypo.yaml"), "--scenarios", str(self.tmp / "scen.yaml"), *extra])
        return code, buf.getvalue()

    def test_end_to_end(self):
        code, out = self.run_stage()
        self.assertEqual(code, 0, out)
        h = pd.read_csv(self.processed / "stress_hypothetical.csv", index_col="scenario")
        self.assertEqual(set(h.index), {"crash", "fxloss"})
        self.assertLess(h.loc["crash", "portfolio_move"], 0)
        self.assertLess(h.loc["fxloss", "portfolio_move"], 0)           # PLN appreciation hurts a EUR portfolio
        r = pd.read_csv(self.processed / "stress_reverse.csv")
        self.assertEqual(set(r["loss"]), {-0.15, -0.20, -0.25})
        self.assertTrue((r["distance"] > 0).all())
        hist = pd.read_csv(self.processed / "stress_historical.csv", index_col="scenario")
        self.assertAlmostEqual(hist.loc["ep", "coverage"], 1.0)

    def test_errors(self):
        code, out = self.run_stage(["--method", "nope"])
        self.assertEqual((code, "Unknown method" in out), (1, True))
        (self.processed / "returns_local.csv").unlink()
        code, out = self.run_stage()
        self.assertEqual((code, "Missing" in out), (1, True))


if __name__ == "__main__":
    unittest.main()
