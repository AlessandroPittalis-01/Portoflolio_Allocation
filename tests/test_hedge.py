"""Tests for prm.fx.hedge (synthetic data, no network)."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from prm.fx.hedge import (
    DEFAULT_HEDGE_PATH, HedgeConfigError, daily_net_carry, fx_component, hedge_effect, hedge_ratios,
    hedged_pln_returns, load_hedge_config,
)


def make_data(n=500, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    fx = pd.Series(rng.normal(0, 0.004, n), index=idx)
    local = pd.DataFrame({"eq": rng.normal(0.0004, 0.01, n), "bd": rng.normal(0.0001, 0.003, n)}, index=idx)
    pln = (1 + local).mul(1 + fx, axis=0) - 1
    return pln, local, fx


class TestHedge(unittest.TestCase):
    def test_fx_component_recovers_the_currency_return(self):
        pln, local, fx = make_data()
        got = fx_component(pln, local)
        for c in got.columns:
            np.testing.assert_allclose(got[c].values, fx.values, atol=1e-12)

    def test_no_hedge_gives_back_pln(self):
        pln, local, _ = make_data()
        out = hedged_pln_returns(pln, local, pd.Series({"eq": 0.0, "bd": 0.0}), daily_net_carry(0.03, 0.003))
        np.testing.assert_allclose(out.values, pln.values, atol=1e-12)

    def test_full_hedge_removes_the_currency(self):
        pln, local, _ = make_data()
        out = hedged_pln_returns(pln, local, pd.Series({"eq": 1.0, "bd": 1.0}), 0.0)
        np.testing.assert_allclose(out.values, local.values, atol=1e-12)
        self.assertLess(out["eq"].std(), pln["eq"].std())

    def test_carry_shifts_the_mean_by_the_net_carry_on_the_hedged_share(self):
        pln, local, _ = make_data()
        c = daily_net_carry(0.04, 0.003)
        h = pd.Series({"eq": 0.5, "bd": 0.0})
        out = hedged_pln_returns(pln, local, h, c)
        expected = (1 + local["eq"]) * (1 + 0.5 * fx_component(pln, local)["eq"] + 0.5 * c) - 1
        np.testing.assert_allclose(out["eq"].values, expected.values, atol=1e-12)
        np.testing.assert_allclose(out["bd"].values, pln["bd"].values, atol=1e-12)

    def test_missing_returns_stay_missing(self):
        pln, local, _ = make_data()
        pln.iloc[5, 0] = np.nan
        out = hedged_pln_returns(pln, local, pd.Series({"eq": 1.0, "bd": 1.0}), 0.0)
        self.assertTrue(np.isnan(out.iloc[5, 0]))
        self.assertFalse(np.isnan(out.iloc[6, 0]))

    def test_ratios_by_class_cash_and_unknown_unhedged(self):
        meta = pd.DataFrame({"asset_class": ["equity", "bond", "cash", None]}, index=["a", "b", "c", "d"])
        r = hedge_ratios(meta, {"equity": 0.5, "bond": 1.0, "real": 0.0}, ["a", "b", "c", "d", "zz"])
        self.assertEqual(r.to_dict(), {"a": 0.5, "b": 1.0, "c": 0.0, "d": 0.0, "zz": 0.0})

    def test_hedge_effect(self):
        w = pd.Series({"a": 0.4, "b": 0.5, "c": 0.1})
        e = hedge_effect(w, pd.Series({"a": 0.5, "b": 1.0, "c": 0.0}), 0.03, 0.003)
        self.assertAlmostEqual(e["hedged_notional"], 0.7)
        self.assertAlmostEqual(e["carry_minus_cost_pa"], 0.7 * 0.027)

    def test_real_config_loads(self):
        cfg = load_hedge_config(DEFAULT_HEDGE_PATH)
        self.assertIn("none", cfg["scenarios"])
        self.assertTrue(all(h == 0 for h in cfg["scenarios"]["none"].values()))

    def test_bad_configs_are_rejected(self):
        bads = ["carry_annual: []\ncost_annual: 0.0\nscenarios: {a: {equity: 0, bond: 0, real: 0}}\n",
                "carry_annual: [0.0]\ncost_annual: -1\nscenarios: {a: {equity: 0, bond: 0, real: 0}}\n",
                "carry_annual: [0.0]\ncost_annual: 0.0\nscenarios: {a: {equity: 2, bond: 0, real: 0}}\n",
                "carry_annual: [0.0]\ncost_annual: 0.0\nscenarios: {a: {equity: 0, bond: 0}}\n"]
        for text in bads:
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "h.yaml"
                p.write_text(text)
                with self.assertRaises(HedgeConfigError):
                    load_hedge_config(p)


if __name__ == "__main__":
    unittest.main()


# ---- stage 08, on the synthetic data of the stage-05 tests ---------------------------------------------
import contextlib  # noqa: E402
import importlib.util  # noqa: E402
import io  # noqa: E402

from test_allocation import TestStage05 as _Stage05Base  # noqa: E402


class TestStage08(unittest.TestCase):
    VOLS = _Stage05Base.VOLS
    setUp = _Stage05Base.setUp          # same synthetic ETFs; only the setup is borrowed, not the tests

    def run_stage(self, extra=()):
        path = Path(__file__).resolve().parents[1] / "pipeline" / "08_fx_hedge.py"
        spec = importlib.util.spec_from_file_location("stage08", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = module.main(["--settings", str(self.tmp / "settings.yaml"), "--portfolio", str(self.tmp / "portfolio.yaml"),
                                "--universe", str(self.tmp / "universe.yaml"), *extra])
        return code, buf.getvalue()

    def test_end_to_end(self):
        code, out = self.run_stage()
        self.assertEqual(code, 0, out)
        s = pd.read_csv(self.processed / "fx_hedge_summary.csv")
        cfg = load_hedge_config(DEFAULT_HEDGE_PATH)
        self.assertEqual(set(s["scenario"]), set(cfg["scenarios"]))
        self.assertEqual(len(s[s["scenario"] == "none"]), 1)                              # no hedge: one row, carry irrelevant
        self.assertEqual(len(s[s["scenario"] == "all_full"]), len(cfg["carry_annual"]))
        self.assertTrue((s["vol_model"] <= 0.09 + 1e-6).all())                            # target and limits still hold
        self.assertTrue((s["equity_w"] <= 0.50 + 1e-9).all())
        none = s[s["scenario"] == "none"].iloc[0]
        full = s[(s["scenario"] == "all_full") & (s["carry_assumed"] == 0.0)].iloc[0]
        self.assertAlmostEqual(none["hedged_notional"], 0.0)
        self.assertLess(abs(full["fx_share"]), abs(none["fx_share"]))                      # the hedge removes FX variance
        self.assertGreater(full["hedged_notional"], 0.5)
        a = pd.read_csv(self.processed / "fx_hedge_assets.csv")
        self.assertIn("corr_local_fx", a.columns)

    def test_missing_input_is_reported(self):
        (self.processed / "returns_local.csv").unlink()
        code, out = self.run_stage()
        self.assertEqual(code, 1)
        self.assertIn("Missing", out)
