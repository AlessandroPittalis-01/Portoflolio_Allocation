"""Tests for prm.risk.limits (and stage 14 in test_report.py)."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from prm.risk.limits import (
    AMBER, DEFAULT_LIMITS_PATH, GREEN, NA, RED, LimitsConfigError, drawdown_status, evaluate, load_limits, worst_status, zone_status,
)


class TestEvaluate(unittest.TestCase):
    def test_upper_limit(self):
        self.assertEqual(evaluate(0.20, upper=0.30, amber_margin=0.03), GREEN)
        self.assertEqual(evaluate(0.28, upper=0.30, amber_margin=0.03), AMBER)
        self.assertEqual(evaluate(0.30, upper=0.30, amber_margin=0.03), AMBER)       # exactly at the limit: still inside
        self.assertEqual(evaluate(0.35, upper=0.30, amber_margin=0.03), RED)

    def test_range(self):
        kw = dict(lower=0.08, upper=0.10, amber_margin=0.005)
        self.assertEqual(evaluate(0.09, **kw), GREEN)
        self.assertEqual(evaluate(0.0805, **kw), AMBER)
        self.assertEqual(evaluate(0.0995, **kw), AMBER)
        self.assertEqual(evaluate(0.07, **kw), RED)
        self.assertEqual(evaluate(0.11, **kw), RED)

    def test_lower_only_for_a_negative_move(self):
        self.assertEqual(evaluate(-0.10, lower=-0.25, amber_margin=0.05), GREEN)
        self.assertEqual(evaluate(-0.22, lower=-0.25, amber_margin=0.05), AMBER)
        self.assertEqual(evaluate(-0.30, lower=-0.25, amber_margin=0.05), RED)

    def test_missing_values(self):
        self.assertEqual(evaluate(None, upper=1.0), NA)
        self.assertEqual(evaluate(float("nan"), upper=1.0), NA)

    def test_drawdown_levels(self):
        args = (-0.15, -0.20, -0.25)
        self.assertEqual(drawdown_status(-0.05, *args), GREEN)
        self.assertEqual(drawdown_status(-0.15, *args), AMBER)
        self.assertEqual(drawdown_status(-0.18, *args), AMBER)
        self.assertEqual(drawdown_status(-0.20, *args), RED)
        self.assertEqual(drawdown_status(-0.30, *args), RED)
        self.assertEqual(drawdown_status(None, *args), NA)

    def test_zone_and_worst(self):
        self.assertEqual([zone_status(z) for z in ("green", "yellow", "red", None)], [GREEN, AMBER, RED, NA])
        self.assertEqual(worst_status([GREEN, AMBER, NA]), AMBER)
        self.assertEqual(worst_status([GREEN, RED, AMBER]), RED)
        self.assertEqual(worst_status([NA, NA]), NA)
        self.assertEqual(worst_status([GREEN]), GREEN)


class TestConfig(unittest.TestCase):
    def test_real_file(self):
        lim = load_limits(DEFAULT_LIMITS_PATH)
        self.assertEqual((lim["portfolio_vol"].lower, lim["portfolio_vol"].upper), (0.08, 0.10))
        self.assertEqual(lim["fx_share"].upper, 0.30)
        self.assertEqual(lim["fx_share"].status, "decided")
        self.assertEqual(lim["var99_1d"].status, "decided")
        self.assertIn("decision 45", lim["fx_share"].accepted_exception)
        self.assertIsNone(lim["portfolio_vol"].accepted_exception)

    def test_bad_files(self):
        for text in ["limits: {}\n", "limits: {a: {lower: 1, upper: 0, status: decided}}\n",
                     "limits: {a: {upper: x, status: decided}}\n", "limits: {a: {upper: 1, amber_margin: -1, status: decided}}\n",
                     "limits: {a: {upper: 1, status: maybe}}\n"]:
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "l.yaml"
                p.write_text(text)
                with self.assertRaises(LimitsConfigError):
                    load_limits(p)


if __name__ == "__main__":
    unittest.main()
