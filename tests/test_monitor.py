"""Tests for prm.risk.monitor (stage 14 logic) with small synthetic tables."""

import unittest

import numpy as np
import pandas as pd

from prm.config import Profile
from prm.risk.limits import AMBER, DEFAULT_LIMITS_PATH, GREEN, NA, RED, load_limits
from prm.risk.monitor import build_checks, class_risk_gap, current_drawdown, render_markdown

PROFILE = Profile(name="t", target_vol=0.09, dd_alert=-0.15, dd_review=-0.20, max_weight_per_etf=0.40, equity_cap=0.50,
                  rebalance_band_pp=0.05, stop_contributing_dd=-0.25)


class TestPieces(unittest.TestCase):
    def test_current_drawdown(self):
        r = pd.Series([0.10, -0.10, -0.10, 0.05])
        cur, mx = current_drawdown(r)
        w = np.array([1.1, 0.99, 0.891, 0.93555])
        self.assertAlmostEqual(cur, w[-1] / w.max() - 1)
        self.assertAlmostEqual(mx, w[2] / w[0] - 1)
        self.assertTrue(np.isnan(current_drawdown(pd.Series(dtype=float))[0]))

    def test_class_gap_ignores_cash_and_rescales(self):
        shares = pd.Series({"a": 0.5, "b": 0.3, "c": 0.15, "cash": 0.05})
        classes = {"a": "equity", "b": "bond", "c": "real", "cash": "cash"}
        gap = class_risk_gap(shares, classes, {"equity": 0.5, "bond": 0.3, "real": 0.2})
        # risky shares 0.5/0.95, 0.3/0.95, 0.15/0.95 against 0.5, 0.3, 0.2
        self.assertAlmostEqual(gap["equity"], abs(0.5 / 0.95 - 0.5))
        self.assertAlmostEqual(gap["real"], abs(0.15 / 0.95 - 0.2))

    def test_class_gap_missing_class_counts_as_zero(self):
        gap = class_risk_gap(pd.Series({"a": 1.0}), {"a": "equity"}, {"equity": 0.6, "bond": 0.4})
        self.assertAlmostEqual(gap["bond"], 0.4)


class TestChecks(unittest.TestCase):
    def setUp(self):
        self.limits = load_limits(DEFAULT_LIMITS_PATH)
        self.row = pd.Series({"vol_model": 0.09, "fx_share": 0.35, "equity_w": 0.30, "max_weight": 0.25})
        self.var = pd.DataFrame({"model": ["fhs_ewma", "historical"], "level": [0.99, 0.99], "var": [0.012, 0.020]})
        self.bt = pd.DataFrame({"model": ["fhs_ewma"], "level": [0.99], "zone": ["green"]})
        self.hyp = pd.DataFrame({"portfolio_move": [-0.08, -0.116]}, index=["a", "b"])

    def _checks(self, **over):
        kw = dict(summary_row=self.row, weights=None, class_gap=pd.Series({"equity": 0.03}), var_table=self.var,
                  var_backtest=self.bt, hypothetical=self.hyp, twr=pd.Series([0.01] * 10))
        kw.update(over)
        return build_checks(self.limits, PROFILE, **kw).set_index("id")

    def test_statuses(self):
        c = self._checks()
        self.assertEqual(c.loc["portfolio_vol", "status"], GREEN)
        self.assertEqual(c.loc["fx_share", "status"], RED)                 # 35% > 30%
        self.assertEqual(c.loc["equity_cap", "status"], GREEN)
        self.assertEqual(c.loc["var99_1d", "status"], GREEN)               # reference model, not the historical one
        self.assertEqual(c.loc["var_model_zone", "status"], GREEN)
        self.assertEqual(c.loc["worst_hypothetical", "status"], GREEN)     # -11.6% vs -25%
        self.assertEqual(c.loc["drawdown_now", "status"], GREEN)

    def test_missing_inputs_are_na(self):
        c = self._checks(var_table=None, var_backtest=None, hypothetical=None, twr=None, class_gap=None)
        for cid in ("var99_1d", "var_model_zone", "worst_hypothetical", "drawdown_now", "class_risk_share"):
            self.assertEqual(c.loc[cid, "status"], NA)

    def test_drawdown_red_and_worst_amber(self):
        twr = pd.Series([0.0] * 5 + [-0.1] * 3)                             # about -27% from the peak
        hyp = pd.DataFrame({"portfolio_move": [-0.22]}, index=["a"])
        c = self._checks(twr=twr, hypothetical=hyp)
        self.assertEqual(c.loc["drawdown_now", "status"], RED)
        self.assertEqual(c.loc["worst_hypothetical", "status"], AMBER)     # within 5 points of -25%

    def test_render(self):
        md = render_markdown(self._checks().reset_index(), PROFILE, "risk_budget", "2026-11-02")
        self.assertIn("Overall status: **RED**", md)
        self.assertIn("## To look at", md)
        md2 = render_markdown(self._checks().reset_index(), PROFILE, "risk_budget", "2026-11-02", {"fx_share": "knowingly accepted"})
        self.assertIn("ACCEPTED EXCEPTION: knowingly accepted", md2)


if __name__ == "__main__":
    unittest.main()
