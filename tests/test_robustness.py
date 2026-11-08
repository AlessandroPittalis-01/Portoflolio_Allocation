"""Tests for prm.backtest.robustness with the synthetic world of test_backtest."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import pandas as pd

from prm.backtest.robustness import VARIANTS, Variant, apply_variant, excess_over_benchmark, run_variant, spread
from prm.backtest.settings import BacktestSettings
from prm.config import load_profiles
from test_backtest import make_meta, make_world, write_portfolio


class TestVariants(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.spec = write_portfolio(self.tmp / "p.yaml")
        self.bt = BacktestSettings(504, None, 2800.0, 10.0, ("risk_budget", "equal_weight"))

    def test_declared_variants(self):
        names = [v.name for v in VARIANTS]
        self.assertEqual(names[0], "base")
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(VARIANTS), 7)

    def test_apply_changes_only_what_is_asked_and_does_not_mutate(self):
        s, b = apply_variant(self.spec, self.bt, Variant("x", cost_bps=25.0))
        self.assertEqual(b.cost_bps, 25.0)
        self.assertEqual(s, self.spec)
        s, b = apply_variant(self.spec, self.bt, Variant("y", switch_margin=0.05, equity_secondary_share=0.3))
        self.assertEqual(s.rules.switch_margin, 0.05)
        self.assertEqual(s.secondary_share, {"equity": 0.3, "bond": 0.3})
        self.assertEqual(b, self.bt)
        self.assertEqual(self.spec.secondary_share["equity"], 0.2)          # original untouched
        self.assertEqual(self.spec.rules.switch_margin, 0.10)

    def test_bad_share_rejected(self):
        with self.assertRaises(ValueError):
            apply_variant(self.spec, self.bt, Variant("z", equity_secondary_share=1.2))

    def test_run_variant_and_cost_effect(self):
        pln, local = make_world()
        meta, profile = make_meta(), load_profiles()["owner"]
        strat = ("risk_budget", "equal_weight")
        lo = run_variant(pln, local, meta, self.spec, profile, "ledoit_wolf", self.bt, Variant("cost_5bps", cost_bps=5.0), strat)
        hi = run_variant(pln, local, meta, self.spec, profile, "ledoit_wolf", self.bt, Variant("cost_25bps", cost_bps=25.0), strat)
        self.assertEqual(set(lo.index), set(strat))
        self.assertTrue((lo["variant"] == "cost_5bps").all())
        # higher cost -> more money paid in costs, never less
        self.assertGreater(hi.loc["risk_budget", "costs_pln"], lo.loc["risk_budget", "costs_pln"])
        # costs do not change the choice: volatility is almost the same
        self.assertAlmostEqual(hi.loc["risk_budget", "vol_ann"], lo.loc["risk_budget", "vol_ann"], delta=0.01)

    def test_spread_and_gap(self):
        res = pd.DataFrame({"variant": ["a", "b", "a", "b"], "strategy": ["s", "s", "bm", "bm"],
                            "max_dd": [-0.10, -0.14, -0.20, -0.20], "twr_ann": [0.05, 0.03, 0.04, 0.04]})
        sp = spread(res, "s", "max_dd")
        self.assertAlmostEqual(sp["range"], 0.04)
        gap = excess_over_benchmark(res, "s", "bm", "max_dd")
        self.assertAlmostEqual(gap["a"], 0.10)
        self.assertAlmostEqual(gap["b"], 0.06)


if __name__ == "__main__":
    unittest.main()
