"""Tests for prm.risk (metrics, covariance, contributions, stress, dollar beta) and stage 04. No network."""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from prm.risk.contributions import portfolio_vol, risk_contributions
from prm.risk.covariance import annualise, common_window, ewma_cov, ledoit_wolf, sample_cov, to_correlation
from prm.risk.metrics import (annual_return, annual_vol, drawdown_series, gaussian_var_es, hist_var_es,
                              max_drawdown, summarise_returns)
from prm.risk.stress import DEFAULT_SCENARIOS_PATH, load_scenarios, scenario_return, stress_table
from prm.risk.usd import usd_beta, usd_in_eur


def daily(values, start="2020-01-01"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values), name="date"), dtype="float64")


class TestMetrics(unittest.TestCase):
    def test_max_drawdown_known_path(self):
        # 100 -> 120 -> 60 -> 90 : drawdown -50%, not yet recovered
        r = daily([0.2, -0.5, 0.5])
        dd = max_drawdown(r)
        self.assertAlmostEqual(dd["max_dd"], -0.5)
        self.assertEqual(dd["trough"], r.index[1])
        self.assertIsNone(dd["recovery"])
        self.assertAlmostEqual(drawdown_series(r).iloc[-1], (1.2 * 0.5 * 1.5) / 1.2 - 1)

    def test_recovery_date_found(self):
        r = daily([-0.1, 0.0, 0.2])   # 0.9 -> 0.9 -> 1.08 : back above the starting value 1.0 on day 3
        dd = max_drawdown(r)
        self.assertAlmostEqual(dd["max_dd"], -0.1)   # a first-day loss counts
        self.assertEqual(dd["recovery"], r.index[2])

    def test_no_loss_gives_zero_drawdown(self):
        self.assertEqual(max_drawdown(daily([0.01, 0.02, 0.0]))["max_dd"], 0.0)

    def test_annual_return_and_vol(self):
        r = daily([0.001] * 252)
        self.assertAlmostEqual(annual_return(r), 1.001 ** 252 - 1)
        rng = np.random.default_rng(0)
        self.assertAlmostEqual(annual_vol(daily(rng.normal(0, 0.01, 20000))), 0.01 * np.sqrt(252), delta=0.005)

    def test_historical_var_es(self):
        r = daily(list(np.linspace(-0.10, 0.10, 201)))   # uniform losses
        var, es = hist_var_es(r, 0.95)
        self.assertAlmostEqual(var, 0.09, delta=0.002)
        self.assertGreater(es, var)                      # ES is always at least as bad as VaR

    def test_gaussian_var_matches_normal_data(self):
        rng = np.random.default_rng(1)
        r = daily(rng.normal(0, 0.01, 200000))
        g_var, g_es = gaussian_var_es(r, 0.99)
        h_var, h_es = hist_var_es(r, 0.99)
        self.assertAlmostEqual(g_var, 0.01 * 2.326, delta=0.0005)
        self.assertAlmostEqual(g_var, h_var, delta=0.0007)
        self.assertAlmostEqual(g_es, h_es, delta=0.001)

    def test_fat_tails_show_up_in_kurtosis_and_es_gap(self):
        rng = np.random.default_rng(2)
        r = daily(rng.standard_t(3, 50000) * 0.005)
        s = summarise_returns(r)
        self.assertGreater(s["excess_kurtosis"], 3)
        self.assertGreater(s["es99_hist"], s["es99_gauss"])

    def test_summary_keys(self):
        s = summarise_returns(daily([0.01, -0.02, 0.005, 0.0, 0.01] * 10))
        for k in ("ann_vol", "max_dd", "var95_hist", "es99_hist", "worst_day", "current_dd"):
            self.assertIn(k, s)


class TestCovariance(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(3)
        self.x = pd.DataFrame(rng.normal(0, 0.01, (500, 4)), columns=list("abcd"),
                              index=pd.bdate_range("2020-01-01", periods=500))

    def test_missing_values_are_rejected(self):
        bad = self.x.copy()
        bad.iloc[3, 1] = np.nan
        for fn in (sample_cov, ewma_cov, ledoit_wolf):
            with self.assertRaises(ValueError):
                fn(bad)
        self.assertEqual(len(common_window(bad)), 499)

    def test_ewma_with_lambda_one_is_the_second_moment(self):
        cov = ewma_cov(self.x, 1.0)
        expected = (self.x.T @ self.x) / len(self.x)
        self.assertTrue(np.allclose(cov, expected))

    def test_ewma_reacts_to_a_recent_volatility_jump(self):
        calm = pd.DataFrame(np.random.default_rng(4).normal(0, 0.005, (400, 1)), columns=["a"])
        wild = pd.DataFrame(np.random.default_rng(5).normal(0, 0.03, (40, 1)), columns=["a"])
        x = pd.concat([calm, wild], ignore_index=True)
        self.assertGreater(ewma_cov(x, 0.94).iloc[0, 0], 3 * sample_cov(x).iloc[0, 0])

    def test_ledoit_wolf_properties(self):
        cov, shrink = ledoit_wolf(self.x)
        self.assertTrue(0 <= shrink <= 1)
        self.assertTrue(np.allclose(cov, cov.T))
        self.assertGreater(np.linalg.eigvalsh(cov.to_numpy()).min(), 0)
        # trace is preserved (shrinking towards mu*I keeps the average variance)
        s = self.x.cov(ddof=0)
        self.assertAlmostEqual(np.trace(cov), np.trace(s), places=12)

    def test_ledoit_wolf_shrinks_more_with_few_observations(self):
        rng = np.random.default_rng(8)
        factor = rng.normal(0, 0.01, (2000, 1))
        data = pd.DataFrame(factor * np.array([1.0, 0.8, 0.5, 0.2]) + rng.normal(0, 0.004, (2000, 4)) * np.array([1, 2, 3, 4]))
        _, few = ledoit_wolf(data.iloc[:40])
        _, many = ledoit_wolf(data)
        self.assertGreater(few, many)

    def test_ledoit_wolf_matches_sklearn_when_available(self):
        try:
            from sklearn.covariance import LedoitWolf
        except ImportError:
            self.skipTest("scikit-learn not installed (only used as a cross-check)")
        cov, shrink = ledoit_wolf(self.x)
        ref = LedoitWolf().fit(self.x.to_numpy())
        self.assertAlmostEqual(shrink, ref.shrinkage_, places=8)
        self.assertTrue(np.allclose(cov.to_numpy(), ref.covariance_))

    def test_ledoit_wolf_makes_singular_case_invertible(self):
        wide = pd.DataFrame(np.random.default_rng(6).normal(0, 0.01, (20, 30)))   # more assets than days
        cov, _ = ledoit_wolf(wide)
        self.assertGreater(np.linalg.eigvalsh(cov.to_numpy()).min(), 0)

    def test_annualise_and_correlation(self):
        cov = sample_cov(self.x)
        self.assertTrue(np.allclose(annualise(cov), cov * 252))
        corr = to_correlation(cov)
        self.assertTrue(np.allclose(np.diag(corr), 1.0))
        self.assertTrue(np.allclose(corr, self.x.corr()))


class TestContributions(unittest.TestCase):
    def test_contributions_add_up_to_portfolio_vol(self):
        cov = pd.DataFrame([[0.04, 0.01, 0.0], [0.01, 0.09, 0.02], [0.0, 0.02, 0.01]], index=list("abc"), columns=list("abc"))
        w = pd.Series({"a": 0.5, "b": 0.2, "c": 0.3})
        rc = risk_contributions(w, cov)
        self.assertAlmostEqual(rc["risk_contribution"].sum(), portfolio_vol(w, cov))
        self.assertAlmostEqual(rc["risk_share"].sum(), 1.0)

    def test_equal_risk_in_uncorrelated_equal_vol_assets_with_equal_weights(self):
        cov = pd.DataFrame(np.eye(4) * 0.04, index=list("abcd"), columns=list("abcd"))
        rc = risk_contributions(pd.Series(0.25, index=list("abcd")), cov)
        self.assertTrue(np.allclose(rc["risk_share"], 0.25))

    def test_small_weight_can_carry_large_risk(self):
        cov = pd.DataFrame(np.diag([0.0004, 0.09]), index=["bond", "stock"], columns=["bond", "stock"])
        rc = risk_contributions(pd.Series({"bond": 0.8, "stock": 0.2}), cov)
        self.assertGreater(rc.loc["stock", "risk_share"], 0.9)

    def test_zero_vol_portfolio_raises(self):
        cov = pd.DataFrame([[0.0]], index=["a"], columns=["a"])
        with self.assertRaises(ValueError):
            risk_contributions(pd.Series({"a": 1.0}), cov)


class TestStress(unittest.TestCase):
    def test_real_scenario_file_loads(self):
        scenarios = load_scenarios(DEFAULT_SCENARIOS_PATH)
        self.assertGreaterEqual(len(scenarios), 5)
        self.assertTrue(all(s["start"] < s["end"] for s in scenarios))
        self.assertIn("covid_2020", [s["id"] for s in scenarios])

    def test_scenario_return_compounds_and_excludes_start_day(self):
        idx = pd.bdate_range("2020-01-01", periods=10)
        r = pd.Series([0.5] + [0.1] * 9, index=idx)           # huge return on the first day
        out = scenario_return(r, idx[0], idx[3])               # start = close of day 0
        self.assertAlmostEqual(out, 1.1 ** 3 - 1)

    def test_asset_that_did_not_exist_gets_nan(self):
        idx = pd.bdate_range("2020-03-01", periods=30)
        r = pd.Series(0.01, index=idx)
        self.assertTrue(np.isnan(scenario_return(r, pd.Timestamp("2020-02-19"), pd.Timestamp("2020-03-23"))))

    def test_bad_scenario_files_are_rejected(self):
        for text in ("scenarios:\n  - {id: a, start: 2020-05-01, end: 2020-01-01}\n",
                     "scenarios:\n  - {id: a, start: 2020-01-01}\n",
                     "scenarios:\n  - {id: a, start: 2020-01-01, end: 2020-02-01}\n  - {id: a, start: 2020-03-01, end: 2020-04-01}\n"):
            path = Path(tempfile.mkdtemp()) / "s.yaml"
            path.write_text(text)
            with self.assertRaises(ValueError):
                load_scenarios(path)

    def test_stress_table_shape(self):
        idx = pd.bdate_range("2020-01-01", periods=100)
        df = pd.DataFrame({"a": 0.001, "b": 0.002}, index=idx)
        sc = [{"id": "s1", "start": idx[5], "end": idx[20], "description": ""}]
        t = stress_table(df, sc)
        self.assertEqual(list(t.columns), ["s1"])
        self.assertEqual(list(t.index), ["a", "b"])


class TestUsd(unittest.TestCase):
    def test_usd_in_eur(self):
        idx = pd.bdate_range("2020-01-01", periods=3)
        out = usd_in_eur(pd.Series([4.0, 4.0, 4.0], index=idx), pd.Series([4.4, 4.4, 4.4], index=idx))
        self.assertTrue(np.allclose(out, 4.0 / 4.4))

    def test_beta_recovers_the_true_exposure(self):
        rng = np.random.default_rng(7)
        n = 1500
        idx = pd.bdate_range("2018-01-01", periods=n, name="date")
        usd_ret = rng.normal(0, 0.004, n)
        usd = pd.Series(0.9 * np.exp(np.cumsum(usd_ret)), index=idx)
        local = pd.Series(np.expm1(0.8 * usd_ret + rng.normal(0, 0.005, n)), index=idx)   # true beta 0.8
        beta, r2 = usd_beta(local, usd)
        self.assertAlmostEqual(beta, 0.8, delta=0.1)
        self.assertGreater(r2, 0.2)

    def test_short_series_returns_nan(self):
        idx = pd.bdate_range("2018-01-01", periods=20)
        beta, r2 = usd_beta(pd.Series(0.001, index=idx), pd.Series(0.9, index=idx))
        self.assertTrue(np.isnan(beta) and np.isnan(r2))


class TestStage04(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.processed = self.tmp / "processed"
        self.processed.mkdir()
        (self.tmp / "settings.yaml").write_text(
            f'data:\n  start_date: "2018-01-01"\n  raw_dir: {self.tmp / "raw"}\n  processed_dir: {self.processed}\n'
            "  max_cache_age_days: 1\nquality:\n  max_daily_move: 0.12\n  max_gap_days: 7\n  max_stale_days: 5\n")
        rng = np.random.default_rng(0)
        idx = pd.bdate_range("2018-01-01", "2024-12-31", name="date")
        local = pd.DataFrame(rng.normal(0.0003, 0.01, (len(idx), 3)), index=idx, columns=["eq", "bond", "young"])
        local.loc[local.index < "2022-01-01", "young"] = np.nan          # short history
        fx = rng.normal(0, 0.004, len(idx))
        pln = (1 + local).mul(1 + fx, axis=0) - 1
        local.to_csv(self.processed / "returns_local.csv")
        pln.to_csv(self.processed / "returns_pln.csv")
        rates = pd.DataFrame({"EUR": 4.3 * np.exp(np.cumsum(fx)), "USD": 3.9 * np.exp(np.cumsum(rng.normal(0, 0.005, len(idx))))}, index=idx)
        rates.to_csv(self.processed / "fx_rates.csv")
        pd.DataFrame({"asset_id": ["eq", "bond", "young"], "currency": ["EUR"] * 3}).to_csv(self.processed / "fx_decomposition.csv", index=False)

    def run_stage(self, extra=()):
        spec = importlib.util.spec_from_file_location("stage04", Path(__file__).resolve().parents[1] / "pipeline" / "04_risk_analysis.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = module.main(["--settings", str(self.tmp / "settings.yaml"), *extra])
        return code, buf.getvalue()

    def test_end_to_end_with_two_long_assets(self):
        code, out = self.run_stage(["--assets", "eq,bond"])
        self.assertEqual(code, 0)
        summary = pd.read_csv(self.processed / "risk_summary.csv").set_index("asset_id")
        self.assertEqual(list(summary.index), ["eq", "bond"])
        self.assertLess(summary.loc["eq", "max_dd"], 0)
        cov = pd.read_csv(self.processed / "cov_ledoit_wolf.csv", index_col="asset_id")
        self.assertEqual(cov.shape, (2, 2))
        self.assertTrue((self.processed / "stress_scenarios.csv").exists())
        self.assertIn("Ledoit-Wolf shrinkage", out)

    def test_all_assets_use_the_shortest_window(self):
        code, out = self.run_stage()
        self.assertEqual(code, 0)
        self.assertIn("2022-01", out)          # window starts when 'young' starts

    def test_unknown_asset_and_missing_input(self):
        self.assertEqual(self.run_stage(["--assets", "nope"])[0], 1)
        (self.processed / "returns_pln.csv").unlink()
        self.assertEqual(self.run_stage()[0], 1)


if __name__ == "__main__":
    unittest.main()
