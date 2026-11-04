"""Tests for prm.allocation (weights, targeting, spec) and stage 05. No network."""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from prm.allocation.spec import DEFAULT_PORTFOLIO_PATH, load_portfolio
from prm.allocation.targeting import enforce_limits, portfolio_vol, scale_to_target_vol
from prm.allocation.weights import cap_weights, equal_weight, hrp, inverse_vol, min_variance, risk_parity
from prm.data.universe import DEFAULT_UNIVERSE_PATH, load_universe
from prm.risk.contributions import risk_contributions


def make_cov(n=5, seed=0):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(3000, n)) @ rng.normal(size=(n, n)) * 0.01
    ids = [f"a{i}" for i in range(n)]
    return pd.DataFrame(np.cov(x.T), index=ids, columns=ids)


def diag_cov(vols):
    ids = [f"a{i}" for i in range(len(vols))]
    return pd.DataFrame(np.diag(np.square(vols)), index=ids, columns=ids)


class TestWeights(unittest.TestCase):
    def test_all_methods_are_long_only_and_sum_to_one(self):
        cov = make_cov()
        for w in (equal_weight(cov), inverse_vol(cov), risk_parity(cov), hrp(cov), min_variance(cov, 0.4)):
            self.assertAlmostEqual(w.sum(), 1.0, places=8)
            self.assertTrue((w >= -1e-12).all())
            self.assertEqual(list(w.index), list(cov.index))

    def test_inverse_vol_on_uncorrelated_assets(self):
        w = inverse_vol(diag_cov([0.10, 0.20, 0.40]))
        self.assertTrue(np.allclose(w, np.array([4, 2, 1]) / 7))

    def test_risk_parity_gives_equal_risk_shares(self):
        cov = make_cov(6, seed=3)
        shares = risk_contributions(risk_parity(cov), cov)["risk_share"]
        self.assertTrue(np.allclose(shares, 1 / 6, atol=1e-4))

    def test_risk_parity_equals_inverse_vol_when_uncorrelated(self):
        cov = diag_cov([0.05, 0.10, 0.20])
        self.assertTrue(np.allclose(risk_parity(cov), inverse_vol(cov), atol=1e-5))

    def test_min_variance_two_uncorrelated_assets_has_closed_form(self):
        cov = diag_cov([0.10, 0.20])
        w = min_variance(cov)
        self.assertAlmostEqual(w.iloc[0], 0.04 / (0.01 + 0.04), places=5)

    def test_min_variance_respects_the_cap_and_is_never_worse_than_equal_weight(self):
        cov = make_cov(5, seed=4)
        w = min_variance(cov, 0.3)
        self.assertLessEqual(w.max(), 0.3 + 1e-9)
        self.assertLessEqual(portfolio_vol(w, cov), portfolio_vol(equal_weight(cov), cov) + 1e-9)

    def test_min_variance_with_impossible_cap_raises(self):
        with self.assertRaises(ValueError):
            min_variance(make_cov(5), 0.1)

    def test_hrp_handles_one_and_two_assets_and_identical_copies(self):
        self.assertEqual(hrp(diag_cov([0.1])).iloc[0], 1.0)
        self.assertAlmostEqual(hrp(diag_cov([0.1, 0.1])).iloc[0], 0.5)
        v = np.array([[0.04, 0.04, 0.0], [0.04, 0.04, 0.0], [0.0, 0.0, 0.04]])
        cov = pd.DataFrame(v, index=list("abc"), columns=list("abc")) + np.eye(3) * 1e-9
        w = hrp(cov)
        self.assertAlmostEqual(w["a"], w["b"], places=6)       # identical assets get identical weights
        self.assertAlmostEqual(w["c"], 0.5, places=3)          # the independent asset gets half

    def test_hrp_gives_more_weight_to_the_calmer_independent_asset(self):
        w = hrp(diag_cov([0.05, 0.30]))
        self.assertGreater(w.iloc[0], w.iloc[1])

    def test_bad_covariance_is_rejected(self):
        bad = diag_cov([0.1, 0.0])
        for fn in (equal_weight, inverse_vol, risk_parity, hrp):
            with self.assertRaises(ValueError):
                fn(bad)

    def test_cap_weights(self):
        w = cap_weights(pd.Series({"a": 0.7, "b": 0.2, "c": 0.1}), 0.5)
        self.assertAlmostEqual(w.sum(), 1.0)
        self.assertLessEqual(w.max(), 0.5 + 1e-9)
        self.assertGreater(w["c"], 0.1)                        # the excess went to the others
        with self.assertRaises(ValueError):
            cap_weights(pd.Series({"a": 0.5, "b": 0.5}), 0.4)

    def test_cap_weights_does_nothing_when_not_needed(self):
        w = pd.Series({"a": 0.4, "b": 0.35, "c": 0.25})
        self.assertTrue(np.allclose(cap_weights(w, 0.5), w))


class TestTargeting(unittest.TestCase):
    def setUp(self):
        # one risky asset with 20% vol and a cash-like asset with zero vol, uncorrelated
        self.cov = pd.DataFrame(np.diag([0.04, 0.0]), index=["risky", "cash"], columns=["risky", "cash"])

    def test_hits_the_target_with_cash(self):
        w, k, status = scale_to_target_vol(pd.Series({"risky": 1.0}), self.cov, "cash", 0.10)
        self.assertAlmostEqual(k, 0.5, places=2)
        self.assertEqual(status, "on_target")
        self.assertAlmostEqual(w.sum(), 1.0)
        self.assertLessEqual(portfolio_vol(w, self.cov), 0.10 + 1e-9)

    def test_no_leverage_when_target_is_above_the_risky_mix(self):
        w, k, status = scale_to_target_vol(pd.Series({"risky": 1.0}), self.cov, "cash", 0.30)
        self.assertEqual((k, status), (1.0, "below_target"))
        self.assertAlmostEqual(w["risky"], 1.0)

    def test_cash_with_its_own_volatility_is_handled(self):
        cov = pd.DataFrame([[0.04, 0.0], [0.0, 0.0036]], index=["risky", "cash"], columns=["risky", "cash"])   # cash vol 6%
        w, k, status = scale_to_target_vol(pd.Series({"risky": 1.0}), cov, "cash", 0.09)
        self.assertLessEqual(portfolio_vol(w, cov), 0.09 + 1e-9)
        self.assertGreater(portfolio_vol(w, cov), 0.085)       # close to the target, not far under it

    def test_target_below_what_is_possible_uses_the_lowest_risk_mix(self):
        cov = pd.DataFrame([[0.04, 0.0], [0.0, 0.0036]], index=["risky", "cash"], columns=["risky", "cash"])
        w, k, status = scale_to_target_vol(pd.Series({"risky": 1.0}), cov, "cash", 0.01)
        self.assertEqual(status, "above_floor")
        self.assertLess(portfolio_vol(w, cov), 0.06)           # better than 100% cash (diversification)

    def test_missing_cash_raises(self):
        with self.assertRaises(ValueError):
            scale_to_target_vol(pd.Series({"risky": 1.0}), self.cov, "nope", 0.1)

    def test_enforce_limits_moves_the_excess_to_cash(self):
        roles = {"eq": "equity", "bd": "bond", "cash": "cash"}
        w = enforce_limits(pd.Series({"eq": 0.7, "bd": 0.2, "cash": 0.1}), roles, max_weight=0.6, equity_cap=0.5, cash_id="cash")
        self.assertAlmostEqual(w["eq"], 0.5)
        self.assertAlmostEqual(w["cash"], 0.3)
        self.assertAlmostEqual(w.sum(), 1.0)

    def test_enforce_limits_exempts_cash_from_the_per_etf_cap(self):
        roles = {"eq": "equity", "cash": "cash"}
        w = enforce_limits(pd.Series({"eq": 0.2, "cash": 0.8}), roles, max_weight=0.4, equity_cap=0.5, cash_id="cash")
        self.assertAlmostEqual(w["cash"], 0.8)


class TestSpec(unittest.TestCase):
    def test_real_file_loads_and_ids_exist_in_the_universe(self):
        spec = load_portfolio(DEFAULT_PORTFOLIO_PATH)
        _, assets = load_universe(DEFAULT_UNIVERSE_PATH)
        known = {a.id for a in assets}
        self.assertTrue(set(spec.roles) <= known)
        self.assertLessEqual(len(spec.risky_ids), 6)           # IPS decision 9
        self.assertEqual(spec.roles[spec.cash_id], "cash")

    def test_bad_specs_are_rejected(self):
        base = ("allocation:\n  universe:\n    - {id: a, role: equity}\n    - {id: b, role: bond}\n    - {id: c, role: bond}\n"
                "    - {id: d, role: real}\n    - {id: cash, role: cash}\n  benchmark_60_40: {equity: a, bond: b}\n")
        bads = [base.replace("role: cash}", "role: bond}"),            # no cash
                base.replace("role: real", "role: magic"),             # unknown role
                base.replace("{id: d, role: real}", "{id: a, role: real}"),   # duplicate id
                base.replace("equity: a, bond: b", "equity: b, bond: b"),     # benchmark legs wrong
                base + "  covariance: nope\n",
                base.replace("    - {id: c, role: bond}\n    - {id: d, role: real}\n", "")]   # too few risky
        for text in bads:
            path = Path(tempfile.mkdtemp()) / "p.yaml"
            path.write_text(text)
            with self.assertRaises(ValueError, msg=text):
                load_portfolio(path)


class TestStage05(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.processed = self.tmp / "processed"
        self.processed.mkdir()
        (self.tmp / "settings.yaml").write_text(
            f'data:\n  start_date: "2018-01-01"\n  raw_dir: {self.tmp / "raw"}\n  processed_dir: {self.processed}\n'
            "  max_cache_age_days: 1\nquality:\n  max_daily_move: 0.12\n  max_gap_days: 7\n  max_stale_days: 5\n")
        (self.tmp / "portfolio.yaml").write_text(
            "allocation:\n  universe:\n    - {id: eq, role: equity}\n    - {id: b1, role: bond}\n    - {id: b2, role: bond}\n"
            "    - {id: gld, role: real}\n    - {id: cash, role: cash}\n  benchmark_60_40: {equity: eq, bond: b1}\n")
        rng = np.random.default_rng(0)
        idx = pd.bdate_range("2019-01-01", "2024-12-31", name="date")
        vols = {"eq": 0.010, "b1": 0.004, "b2": 0.005, "gld": 0.009, "cash": 0.0003}
        local = pd.DataFrame({k: rng.normal(0.0002, v, len(idx)) for k, v in vols.items()}, index=idx)
        fx = rng.normal(0, 0.0035, len(idx))
        pln = (1 + local).mul(1 + fx, axis=0) - 1
        local.to_csv(self.processed / "returns_local.csv")
        pln.to_csv(self.processed / "returns_pln.csv")

    def run_stage(self, extra=()):
        spec = importlib.util.spec_from_file_location("stage05", Path(__file__).resolve().parents[1] / "pipeline" / "05_allocation.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = module.main(["--settings", str(self.tmp / "settings.yaml"), "--portfolio", str(self.tmp / "portfolio.yaml"), *extra])
        return code, buf.getvalue()

    def test_end_to_end_respects_limits_and_target(self):
        code, out = self.run_stage(["--profile", "owner"])
        self.assertEqual(code, 0, out)
        w = pd.read_csv(self.processed / "allocation_weights.csv", index_col="method")
        s = pd.read_csv(self.processed / "allocation_summary.csv").set_index("method")
        self.assertEqual(set(w.index), {"equal_weight", "inverse_vol", "risk_parity", "min_variance", "hrp", "benchmark_60_40"})
        self.assertTrue(np.allclose(w.sum(axis=1), 1.0))
        self.assertTrue((w >= -1e-9).all().all())                            # long only, no leverage
        for method in ("equal_weight", "inverse_vol", "risk_parity", "min_variance", "hrp"):
            self.assertLessEqual(s.loc[method, "vol_model"], 0.09 + 1e-6, method)   # never above the owner target
            self.assertLessEqual(s.loc[method, "equity_w"], 0.50 + 1e-9)              # equity cap
            self.assertLessEqual(w.loc[method].drop("cash").max(), 0.40 + 1e-9)       # max weight per ETF
        self.assertAlmostEqual(w.loc["benchmark_60_40", "eq"], 0.6)                   # benchmark left untouched
        shares = pd.read_csv(self.processed / "allocation_risk_shares.csv", index_col="method")
        self.assertTrue(np.allclose(shares.sum(axis=1), 1.0))

    def test_no_returns_are_reported(self):
        _, out = self.run_stage()
        s = pd.read_csv(self.processed / "allocation_summary.csv")
        self.assertFalse([c for c in s.columns if "return" in c.lower()])

    def test_other_profile_and_estimator_and_errors(self):
        self.assertEqual(self.run_stage(["--profile", "prudent", "--cov", "ewma"])[0], 0)
        self.assertEqual(self.run_stage(["--profile", "nope"])[0], 1)
        (self.processed / "returns_pln.csv").unlink()
        self.assertEqual(self.run_stage()[0], 1)


if __name__ == "__main__":
    unittest.main()


class TestRiskBudget(unittest.TestCase):
    def test_equal_budgets_equal_risk_parity(self):
        from prm.allocation.weights import risk_budget
        cov = make_cov(5, seed=11)
        equal = pd.Series(1.0, index=cov.index)
        self.assertTrue(np.allclose(risk_budget(cov, equal), risk_parity(cov), atol=1e-6))

    def test_risk_shares_match_the_budgets(self):
        from prm.allocation.weights import risk_budget
        cov = make_cov(4, seed=12)
        budgets = pd.Series([0.5, 0.2, 0.2, 0.1], index=cov.index)
        shares = risk_contributions(risk_budget(cov, budgets), cov)["risk_share"]
        self.assertTrue(np.allclose(shares, budgets, atol=1e-4))

    def test_budgets_are_rescaled_and_weights_stay_long_only(self):
        from prm.allocation.weights import risk_budget
        cov = make_cov(3, seed=13)
        w = risk_budget(cov, pd.Series([5.0, 3.0, 2.0], index=cov.index))     # 5/3/2 means 50/30/20 %
        shares = risk_contributions(w, cov)["risk_share"]
        self.assertTrue(np.allclose(shares, [0.5, 0.3, 0.2], atol=1e-4))
        self.assertAlmostEqual(w.sum(), 1.0)
        self.assertTrue((w > 0).all())

    def test_bad_budgets_are_rejected(self):
        from prm.allocation.weights import risk_budget
        cov = make_cov(3, seed=14)
        for bad in (pd.Series([1.0, 0.0, 1.0], index=cov.index), pd.Series([1.0, -1.0, 1.0], index=cov.index),
                    pd.Series([1.0, 1.0], index=cov.index[:2])):
            with self.assertRaises(ValueError):
                risk_budget(cov, bad)

    def test_class_budgets_are_split_inside_the_class(self):
        from prm.allocation.budgets import asset_budgets
        roles = {"eq1": "equity", "eq2": "equity", "bd": "bond", "gld": "real"}
        b = asset_budgets(roles, {"equity": 0.5, "bond": 0.3, "real": 0.2})
        self.assertAlmostEqual(b["eq1"], 0.25)
        self.assertAlmostEqual(b["bd"], 0.3)
        self.assertAlmostEqual(b.sum(), 1.0)

    def test_absent_class_is_dropped_and_rest_rescaled(self):
        from prm.allocation.budgets import asset_budgets
        b = asset_budgets({"eq": "equity", "bd": "bond"}, {"equity": 0.5, "bond": 0.3, "real": 0.2})
        self.assertAlmostEqual(b["eq"], 0.5 / 0.8)
        self.assertAlmostEqual(b.sum(), 1.0)

    def test_class_without_budget_or_nonpositive_budget_is_rejected(self):
        from prm.allocation.budgets import asset_budgets
        with self.assertRaises(ValueError):
            asset_budgets({"x": "crypto"}, {"equity": 1.0})
        with self.assertRaises(ValueError):
            asset_budgets({"x": "equity"}, {"equity": 0.0})
