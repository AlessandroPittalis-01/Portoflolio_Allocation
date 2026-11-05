"""Tests for prm.backtest.bootstrap and stage 07. No network."""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from prm.backtest.bootstrap import (
    load_bootstrap, paired_difference, path_metrics, run_bootstrap, stationary_indices, summarise_paths,
)
from prm.backtest.report import longest_underwater_years
from prm.risk.metrics import drawdown_series


def fake_returns(n=1500, seed=0, cols=("a", "b", "ref")):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2016-01-04", periods=n, name="date")
    base = rng.normal(0.0003, 0.008, n)
    return pd.DataFrame({c: base * (0.5 + i * 0.3) + rng.normal(0, 0.002, n) for i, c in enumerate(cols)}, index=idx)


class TestIndices(unittest.TestCase):
    def test_indices_are_in_range_and_deterministic(self):
        a = stationary_indices(100, 400, 10, 50, np.random.default_rng(1))
        b = stationary_indices(100, 400, 10, 50, np.random.default_rng(1))
        self.assertEqual(a.shape, (50, 400))
        self.assertTrue((a >= 0).all() and (a < 100).all())
        self.assertTrue(np.array_equal(a, b))

    def test_blocks_are_consecutive_days_with_the_expected_mean_length(self):
        idx = stationary_indices(5000, 4000, 20, 40, np.random.default_rng(2))
        step = np.diff(idx, axis=1)
        consecutive = (step == 1) | (step == -4999)                    # +1, or wrap-around
        mean_block = 1.0 / (1.0 - consecutive.mean())
        self.assertAlmostEqual(mean_block, 20, delta=2.5)

    def test_block_length_one_is_iid_resampling(self):
        idx = stationary_indices(1000, 2000, 1, 10, np.random.default_rng(3))
        self.assertLess(((np.diff(idx, axis=1)) == 1).mean(), 0.01)

    def test_bad_input_is_rejected(self):
        with self.assertRaises(ValueError):
            stationary_indices(1, 10, 5, 3, np.random.default_rng(0))


class TestMetrics(unittest.TestCase):
    def test_drawdown_and_underwater_match_the_reference_functions(self):
        rng = np.random.default_rng(4)
        r = rng.normal(0.0002, 0.01, (6, 700, 2))
        m = path_metrics(r, 21, -0.10, -0.18, -0.25)
        for p in range(6):
            for s in range(2):
                series = pd.Series(r[p, :, s], index=pd.bdate_range('2020-01-01', periods=700))
                dd = drawdown_series(series)
                self.assertAlmostEqual(m["max_dd"][p, s], dd.min(), places=9)
                self.assertAlmostEqual(m["underwater_years"][p, s], longest_underwater_years(dd), places=9)

    def test_constant_return_has_no_drawdown_and_known_growth(self):
        r = np.full((3, 504, 1), 0.0004)
        m = path_metrics(r, 21, -0.10, -0.18, -0.25)
        self.assertTrue(np.allclose(m["max_dd"], 0.0))
        self.assertTrue(np.allclose(m["underwater_years"], 0.0))
        self.assertTrue(np.allclose(m["twr_ann"], 1.0004 ** 252 - 1))
        self.assertTrue((m["money_multiple"] > 1).all())
        self.assertTrue(np.allclose(m["hit_alert"], 0.0))

    def test_money_multiple_with_zero_returns_is_one(self):
        m = path_metrics(np.zeros((2, 100, 2)), 10, -0.1, -0.18, -0.25)
        self.assertTrue(np.allclose(m["money_multiple"], 1.0))

    def test_threshold_flags_are_ordered(self):
        r = np.random.default_rng(5).normal(0, 0.02, (200, 800, 1))
        m = path_metrics(r, 21, -0.10, -0.18, -0.25)
        self.assertTrue((m["hit_alert"] >= m["hit_review"]).all() and (m["hit_review"] >= m["hit_stop"]).all())


class TestRun(unittest.TestCase):
    def test_run_is_paired_reproducible_and_chunk_independent(self):
        df = fake_returns()
        a = run_bootstrap(df, 504, 21, 120, 21, -0.1, -0.18, -0.25, seed=7, chunk=50)
        b = run_bootstrap(df, 504, 21, 120, 21, -0.1, -0.18, -0.25, seed=7, chunk=50)
        self.assertTrue(np.array_equal(a["max_dd"], b["max_dd"]))
        self.assertEqual(a["max_dd"].shape, (120, 3))
        # strategies built from the same base move together on every path (paired dates)
        self.assertGreater(np.corrcoef(a["twr_ann"][:, 0], a["twr_ann"][:, 2])[0, 1], 0.8)

    def test_missing_values_are_rejected(self):
        df = fake_returns()
        df.iloc[3, 0] = np.nan
        with self.assertRaises(ValueError):
            run_bootstrap(df, 100, 21, 100, 21, -0.1, -0.18, -0.25, seed=1)

    def test_identical_strategies_have_zero_gap(self):
        df = fake_returns(cols=("a", "ref"))
        df["a"] = df["ref"]
        m = run_bootstrap(df, 504, 21, 100, 21, -0.1, -0.18, -0.25, seed=1)
        d = paired_difference(m, ["a", "ref"], "ref")
        self.assertAlmostEqual(d.loc["a", "twr_ann_diff_median"], 0.0, places=12)
        self.assertEqual(d.loc["a", "max_dd_share_positive"], 0.0)

    def test_summary_quantiles_are_ordered(self):
        df = fake_returns()
        m = run_bootstrap(df, 504, 21, 300, 21, -0.1, -0.18, -0.25, seed=2)
        s = summarise_paths(m, list(df.columns))
        self.assertTrue((s["twr_ann_p05"] <= s["twr_ann_p50"]).all() and (s["twr_ann_p50"] <= s["twr_ann_p95"]).all())
        self.assertTrue((s["max_dd_p05"] <= s["max_dd_p95"]).all())          # deeper (more negative) first
        self.assertTrue(((s[["hit_alert", "hit_review", "hit_stop"]] >= 0) & (s[["hit_alert", "hit_review", "hit_stop"]] <= 1)).all().all())


class TestSettings(unittest.TestCase):
    def test_real_file_loads(self):
        cfg = load_bootstrap()
        self.assertIn(cfg.reference, cfg.strategies)
        self.assertGreaterEqual(cfg.n_paths, 100)

    def test_bad_settings_are_rejected(self):
        for text in ("bootstrap: {n_paths: 10, strategies: [a, b], reference: a}",
                     "bootstrap: {strategies: [a], reference: a}",
                     "bootstrap: {strategies: [a, b], reference: c}",
                     "bootstrap: {mean_block_days: 0, strategies: [a, b], reference: a}"):
            path = Path(tempfile.mkdtemp()) / "b.yaml"
            path.write_text(text)
            with self.assertRaises(ValueError, msg=text):
                load_bootstrap(path)


class TestStage07(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.processed = self.tmp / "processed"
        self.processed.mkdir()
        (self.tmp / "settings.yaml").write_text(
            f'data:\n  start_date: "2010-01-01"\n  raw_dir: {self.tmp / "raw"}\n  processed_dir: {self.processed}\n'
            "  max_cache_age_days: 1\nquality:\n  max_daily_move: 0.12\n  max_gap_days: 7\n  max_stale_days: 5\n")
        (self.tmp / "bootstrap.yaml").write_text("bootstrap:\n  n_paths: 200\n  mean_block_days: 21\n  sensitivity_blocks: [10, 63]\n"
                                                "  horizon_years: 3\n  strategies: [a, b, ref]\n  reference: ref\n  seed: 1\n")
        fake_returns(1200).to_csv(self.processed / "backtest_returns_full.csv")

    def run_stage(self, extra=()):
        spec = importlib.util.spec_from_file_location("stage07", Path(__file__).resolve().parents[1] / "pipeline" / "07_bootstrap.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = module.main(["--settings", str(self.tmp / "settings.yaml"), "--bootstrap", str(self.tmp / "bootstrap.yaml"), *extra])
        return code, buf.getvalue()

    def test_end_to_end(self):
        code, out = self.run_stage()
        self.assertEqual(code, 0, out)
        for f in ("bootstrap_summary.csv", "bootstrap_paired.csv", "bootstrap_sensitivity.csv"):
            self.assertTrue((self.processed / f).exists(), f)
        self.assertIn("READ WITH CARE", out)
        self.assertIn("ROBUSTNESS", out)

    def test_errors(self):
        self.assertEqual(self.run_stage(["--profile", "nope"])[0], 1)
        (self.tmp / "bootstrap.yaml").write_text("bootstrap:\n  strategies: [a, zzz]\n  reference: a\n")
        self.assertEqual(self.run_stage()[0], 1)
        (self.processed / "backtest_returns_full.csv").unlink()
        self.assertEqual(self.run_stage()[0], 1)


if __name__ == "__main__":
    unittest.main()
