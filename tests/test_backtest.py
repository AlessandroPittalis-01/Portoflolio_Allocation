"""Tests for prm.backtest (simulation, walk-forward engine) and stage 06. No network."""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from prm.allocation.build import build_meta
from prm.allocation.spec import load_portfolio
from prm.backtest.engine import BENCHMARK, BENCHMARK_LONG, history_years_asof, month_ends, walk_forward
from prm.backtest.report import longest_underwater_years
from prm.backtest.settings import BacktestSettings, load_backtest
from prm.backtest.simulate import irr, simulate
from prm.config import load_profiles
from prm.data.universe import load_universe


def flat_returns(n=300, cols=("a", "b"), r=0.0):
    idx = pd.bdate_range("2022-01-03", periods=n, name="date")
    return pd.DataFrame(r, index=idx, columns=list(cols))


class TestSimulate(unittest.TestCase):
    def test_first_contribution_follows_the_target_weights(self):
        ret = flat_returns()
        d0 = ret.index[10]
        res = simulate(ret, {d0: pd.Series({"a": 0.6, "b": 0.4})}, 1000.0, 0.0, 0.05)
        self.assertAlmostEqual(res.holdings.loc[d0, "a"], 0.6)
        self.assertAlmostEqual(res.value.iloc[-1], 1000.0)

    def test_costs_are_paid_on_purchases_and_reduce_the_return(self):
        ret = flat_returns()
        d0 = ret.index[10]
        free = simulate(ret, {d0: pd.Series({"a": 1.0})}, 1000.0, 0.0, 0.05)
        paid = simulate(ret, {d0: pd.Series({"a": 1.0})}, 1000.0, 10.0, 0.05)
        self.assertAlmostEqual(paid.value.iloc[-1], 1000.0 / 1.001, places=6)       # 10 bps on the purchase
        self.assertAlmostEqual(paid.trades["cost"].sum(), 1000.0 / 1.001 * 0.001, places=6)
        self.assertLess(paid.value.iloc[-1], free.value.iloc[-1])

    def test_contribution_goes_to_the_underweight_etf_without_selling(self):
        ret = flat_returns(60)
        ret.loc[ret.index[21:25], "a"] = 0.02            # "a" runs up, so it becomes overweight
        d1, d2 = ret.index[5], ret.index[40]
        res = simulate(ret, {d1: pd.Series({"a": 0.5, "b": 0.5}), d2: pd.Series({"a": 0.5, "b": 0.5})}, 1000.0, 0.0, 0.20)
        self.assertEqual(res.trades.loc[d2, "sold"], 0.0)      # inside the band: no sale
        self.assertGreater(res.holdings.loc[d2, "b"], 0.5 - 1e-9 - 0.0)

    def test_overweight_beyond_the_band_is_sold(self):
        ret = flat_returns(80)
        ret.loc[ret.index[21:40], "a"] = 0.10
        d1, d2 = ret.index[5], ret.index[60]
        res = simulate(ret, {d1: pd.Series({"a": 0.5, "b": 0.5}), d2: pd.Series({"a": 0.5, "b": 0.5})}, 100.0, 0.0, 0.05)
        self.assertGreater(res.trades.loc[d2, "sold"], 0.0)
        self.assertAlmostEqual(res.holdings.loc[d2, "a"], 0.5, places=6)

    def test_etf_that_leaves_the_portfolio_is_sold(self):
        ret = flat_returns(60)
        d1, d2 = ret.index[5], ret.index[30]
        res = simulate(ret, {d1: pd.Series({"a": 1.0}), d2: pd.Series({"b": 1.0})}, 100.0, 0.0, 0.05)
        self.assertEqual(res.trades.loc[d2, "n_sold"], 1)
        self.assertAlmostEqual(res.holdings.loc[d2, "a"], 0.0, places=9)

    def test_weights_stay_long_only_and_money_is_conserved_without_costs(self):
        rng = np.random.default_rng(1)
        ret = pd.DataFrame(rng.normal(0, 0.01, (400, 3)), index=pd.bdate_range("2022-01-03", periods=400), columns=list("abc"))
        dates = list(ret.index[::21][1:])
        sched = {d: pd.Series({"a": 0.3, "b": 0.3, "c": 0.4}) for d in dates}
        res = simulate(ret, sched, 500.0, 0.0, 0.05)
        self.assertTrue((res.holdings >= -1e-12).all().all())
        self.assertTrue(np.allclose(res.holdings.sum(axis=1), 1.0))
        self.assertAlmostEqual(res.trades["cost"].sum(), 0.0)

    def test_twr_ignores_the_size_of_contributions(self):
        rng = np.random.default_rng(2)
        ret = pd.DataFrame(rng.normal(0.0003, 0.01, (300, 2)), index=pd.bdate_range("2022-01-03", periods=300), columns=list("ab"))
        sched = {d: pd.Series({"a": 0.5, "b": 0.5}) for d in ret.index[::21][1:]}
        small = simulate(ret, sched, 100.0, 0.0, 0.5).twr
        big = simulate(ret, sched, 5000.0, 0.0, 0.5).twr
        self.assertTrue(np.allclose(small.iloc[22:], big.iloc[22:], atol=1e-9))

    def test_closed_exchange_day_leaves_the_etf_unchanged(self):
        ret = flat_returns(40)
        ret.loc[ret.index[10], "a"] = np.nan                 # holiday of the exchange of "a"
        ret.loc[ret.index[11], "a"] = 0.02                   # the next return contains the gap
        res = simulate(ret, {ret.index[5]: pd.Series({"a": 1.0})}, 100.0, 0.0, 0.05)
        self.assertEqual(res.twr.iloc[10 - 5], 0.0)
        self.assertAlmostEqual(res.value.iloc[-1], 102.0)

    def test_held_etf_without_history_is_an_error(self):
        ret = flat_returns(40)
        ret["a"] = np.nan                                    # never listed
        with self.assertRaises(ValueError):
            simulate(ret, {ret.index[5]: pd.Series({"a": 1.0})}, 100.0, 0.0, 0.05)

    def test_irr_matches_a_known_case(self):
        c = pd.Series([100.0], index=[pd.Timestamp("2020-01-01")])
        self.assertAlmostEqual(irr(c, 110.0, pd.Timestamp("2021-01-01")), 0.10, delta=0.002)
        self.assertTrue(np.isnan(irr(pd.Series(dtype=float), 100.0, pd.Timestamp("2021-01-01"))))

    def test_empty_schedule_is_rejected(self):
        with self.assertRaises(ValueError):
            simulate(flat_returns(), {}, 100.0, 0.0, 0.05)


class TestUnderwater(unittest.TestCase):
    def test_longest_stretch_below_a_peak(self):
        dd = pd.Series([0, -0.01, -0.02, 0, 0, -0.01, -0.01, -0.01, -0.01, 0.0])
        self.assertAlmostEqual(longest_underwater_years(dd), 4 / 252)
        self.assertEqual(longest_underwater_years(pd.Series([0.0, 0.0])), 0.0)
        self.assertTrue(np.isnan(longest_underwater_years(pd.Series(dtype=float))))


class TestSettings(unittest.TestCase):
    def test_real_file_loads(self):
        bt = load_backtest()
        self.assertGreaterEqual(bt.min_train_days, 252)
        self.assertIn("risk_budget", bt.methods)

    def test_bad_values_are_rejected(self):
        for text in ("backtest: {min_train_days: 100}", "backtest: {min_train_days: 504, lookback_days: 300}",
                     "backtest: {cost_bps: -1}", "backtest: {methods: [magic]}", "backtest: {monthly_contribution_pln: 0}"):
            path = Path(tempfile.mkdtemp()) / "b.yaml"
            path.write_text(text)
            with self.assertRaises(ValueError, msg=text):
                load_backtest(path)


def make_world(years=8, seed=0, young_from="2017-01-01"):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2012-01-02", periods=252 * years, name="date")
    mkt = rng.normal(0.0003, 0.009, len(idx))
    rates = rng.normal(0.0001, 0.003, len(idx))
    local = pd.DataFrame(index=idx)
    local["eq_old"] = mkt + rng.normal(0, 0.002, len(idx))
    local["eq_young"] = mkt + rng.normal(0, 0.0012, len(idx))
    local["eq_em"] = 0.7 * mkt + rng.normal(0, 0.008, len(idx))
    local["bd1"] = rates + rng.normal(0, 0.0007, len(idx))
    local["bd2"] = 0.4 * rates + rng.normal(0, 0.004, len(idx))
    local["gld"] = rng.normal(0.0002, 0.008, len(idx))
    local["cash"] = rng.normal(0.0001, 0.0003, len(idx))
    local.loc[local.index < young_from, "eq_young"] = np.nan
    local.loc[local.index < "2016-06-01", "gld"] = np.nan
    fx = rng.normal(0, 0.0035, len(idx))
    pln = (1 + local).mul(1 + fx, axis=0) - 1
    return pln, local


CLASSES = {"eq_old": "equity", "eq_young": "equity", "eq_em": "equity", "bd1": "bond", "bd2": "bond", "gld": "real", "cash": "cash"}


SCOPES = {"eq_old": "broad", "eq_young": "broad", "eq_em": "regional"}


def make_meta():
    return pd.DataFrame({"asset_class": pd.Series(CLASSES), "scope": pd.Series(SCOPES), "core": True, "selected": True, "currency": "EUR",
                         "history_years": 9.0, "excluded_because": "", "category": pd.Series({k: f"c_{k}" for k in CLASSES})})


def write_portfolio(path: Path, bench=("eq_old", "bd1"), long_bench=None, margin=0.10):
    path.write_text("allocation:\n  class_budgets: {equity: 0.5, bond: 0.35, real: 0.15}\n  max_etfs: {equity: 2, bond: 2, real: 1}\n"
                    f"  selection: {{rho_max: 0.9, min_overlap_days: 500, min_history_years: 5, switch_margin: {margin}}}\n  secondary_share: {{equity: 0.2, bond: 0.3}}\n"
                    f"  benchmark_60_40: {{equity: {bench[0]}, bond: {bench[1]}}}\n"
                    + (f"  benchmark_60_40_long: {{equity: {long_bench[0]}, bond: {long_bench[1]}}}\n" if long_bench else ""))
    return load_portfolio(path)


class TestWalkForward(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.spec = write_portfolio(self.tmp / "p.yaml")
        self.profile = load_profiles()["owner"]
        self.bt = BacktestSettings(504, None, 2800.0, 10.0, ("equity_placeholder",)[:0] or ("risk_budget", "equal_weight"))
        self.pln, self.local = make_world()
        self.meta = make_meta()

    def run_wf(self, pln=None, local=None):
        return walk_forward(self.pln if pln is None else pln, self.local if local is None else local, self.meta,
                            self.spec, self.profile, "ledoit_wolf", self.bt)

    def test_month_ends_are_last_trading_days(self):
        idx = pd.bdate_range("2022-01-03", "2022-03-31")
        me = month_ends(idx)
        self.assertEqual([d.month for d in me], [1, 2, 3])
        self.assertEqual(me[0], pd.Timestamp("2022-01-31"))

    def test_history_years_are_measured_as_of_the_date(self):
        h = history_years_asof(self.local.loc[:"2017-06-30"])
        self.assertAlmostEqual(h["eq_young"], 0.5, delta=0.02)
        self.assertGreater(h["eq_old"], 5)

    def test_weights_are_valid_and_start_only_when_data_allows(self):
        wf = self.run_wf()
        sched = wf.schedules["risk_budget"]
        self.assertGreater(len(sched), 50)
        self.assertGreaterEqual(min(sched), pd.Timestamp("2012-01-02") + pd.Timedelta(days=360 * 2))     # needs 2 years
        for d, w in sched.items():
            self.assertAlmostEqual(w.sum(), 1.0, places=6, msg=str(d))
            self.assertTrue((w > 0).all())
            self.assertLessEqual(w.drop("cash", errors="ignore").max(), 0.40 + 1e-9)

    def test_young_etf_is_not_used_before_it_has_enough_history(self):
        wf = self.run_wf()
        early = wf.choices.loc[:"2018-11-30"]
        self.assertFalse(early["risky"].str.contains("eq_young").any())
        self.assertFalse(wf.choices.loc[:"2017-12-31", "risky"].str.contains("gld").any())     # gold class absent early

    def test_no_look_ahead_future_data_do_not_change_past_weights(self):
        wf1 = self.run_wf()
        cut = pd.Timestamp("2016-12-30")
        pln2, local2 = self.pln.copy(), self.local.copy()
        rng = np.random.default_rng(99)
        after = pln2.index > cut
        noise = rng.normal(0, 0.02, (after.sum(), pln2.shape[1]))
        pln2.loc[after] = np.where(pln2.loc[after].isna(), np.nan, noise)
        local2.loc[after] = np.where(local2.loc[after].isna(), np.nan, noise)
        wf2 = self.run_wf(pln2, local2)
        for d, w in wf1.schedules["risk_budget"].items():
            if d <= cut:
                pd.testing.assert_series_equal(w, wf2.schedules["risk_budget"][d], check_exact=False, atol=1e-9)
        self.assertGreater(sum(1 for d in wf1.schedules["risk_budget"] if d <= cut), 5)

    def test_benchmark_is_fixed_and_starts_with_its_own_history(self):
        wf = self.run_wf()
        b = wf.schedules[BENCHMARK]
        self.assertTrue(b)
        self.assertTrue(all(abs(w["eq_old"] - 0.6) < 1e-12 and abs(w["bd1"] - 0.4) < 1e-12 for w in b.values()))
        young = write_portfolio(self.tmp / "p2.yaml", ("eq_young", "bd1"))
        wf2 = walk_forward(self.pln, self.local, self.meta, young, self.profile, "ledoit_wolf", self.bt)
        self.assertGreaterEqual(wf2.benchmark_start, pd.Timestamp("2018-12-01"))             # young ETF + 2 years

    def test_long_benchmark_starts_earlier_than_the_young_etf_benchmark(self):
        spec = write_portfolio(self.tmp / "p3.yaml", ("eq_young", "bd1"), ("eq_old", "bd1"))
        wf = walk_forward(self.pln, self.local, self.meta, spec, self.profile, "ledoit_wolf", self.bt)
        self.assertLess(min(wf.schedules[BENCHMARK_LONG]), min(wf.schedules[BENCHMARK]))
        self.assertTrue(all(abs(w["eq_old"] - 0.6) < 1e-12 for w in wf.schedules[BENCHMARK_LONG].values()))

    def test_the_regional_equity_etf_is_never_the_core(self):
        wf = self.run_wf()
        for d, row in wf.choices.iterrows():
            equity = [a for a in row["risky"].split() if a.startswith("eq_")]       # listed in order of choice
            self.assertNotEqual(equity[0], "eq_em", str(d.date()))

    def test_stability_rule_reduces_changes_of_the_chosen_set(self):
        def changes(margin):
            spec = write_portfolio(self.tmp / f"m{margin}.yaml", margin=margin)
            wf = walk_forward(self.pln, self.local, self.meta, spec, self.profile, "ledoit_wolf", self.bt)
            return int((wf.choices["risky"] != wf.choices["risky"].shift()).sum() - 1)
        self.assertLessEqual(changes(0.10), changes(0.0))

    def test_too_little_data_skips_every_date(self):
        wf = walk_forward(self.pln.iloc[:300], self.local.iloc[:300], self.meta, self.spec, self.profile, "ledoit_wolf", self.bt)
        self.assertEqual(len(wf.schedules["risk_budget"]), 0)
        self.assertTrue(wf.skipped)


class TestStage06(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.processed = self.tmp / "processed"
        self.processed.mkdir()
        (self.tmp / "settings.yaml").write_text(
            f'data:\n  start_date: "2010-01-01"\n  raw_dir: {self.tmp / "raw"}\n  processed_dir: {self.processed}\n'
            "  max_cache_age_days: 1\nquality:\n  max_daily_move: 0.12\n  max_gap_days: 7\n  max_stale_days: 5\n")
        write_portfolio(self.tmp / "portfolio.yaml", long_bench=("eq_old", "bd1"))
        (self.tmp / "backtest.yaml").write_text("backtest:\n  min_train_days: 504\n  monthly_contribution_pln: 2800\n  cost_bps: 10\n"
                                                "  methods: [equal_weight, risk_budget]\n")
        lines = ["criteria: {}", "implementable:"]
        for i, c in CLASSES.items():
            lines += [f"  - id: {i}", f"    name: {i}", f"    risk_driver: {c}", f"    asset_class: {c}", "    core: true",
                      f"    category: c_{i}", f"    yahoo_symbol: {i.upper()}.DE"]
        (self.tmp / "universe.yaml").write_text("\n".join(lines) + "\n")
        pd.DataFrame({"asset_id": list(CLASSES), "selected": True, "currency": "EUR", "n_warnings": 0, "history_years": 9.0,
                      "excluded_because": ""}).to_csv(self.processed / "selection.csv", index=False)
        pln, local = make_world(seed=3)
        pln.to_csv(self.processed / "returns_pln.csv")
        local.to_csv(self.processed / "returns_local.csv")

    def run_stage(self, extra=()):
        spec = importlib.util.spec_from_file_location("stage06", Path(__file__).resolve().parents[1] / "pipeline" / "06_backtest.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = module.main(["--settings", str(self.tmp / "settings.yaml"), "--portfolio", str(self.tmp / "portfolio.yaml"),
                                "--backtest", str(self.tmp / "backtest.yaml"), "--universe", str(self.tmp / "universe.yaml"), *extra])
        return code, buf.getvalue()

    def test_end_to_end_writes_the_files_and_respects_limits(self):
        code, out = self.run_stage()
        self.assertEqual(code, 0, out)
        for name in ("backtest_summary_full.csv", "backtest_summary_common.csv", "backtest_returns.csv",
                     "backtest_choices.csv", "backtest_weights.csv", "backtest_class_weights.csv"):
            self.assertTrue((self.processed / name).exists(), name)
        full = pd.read_csv(self.processed / "backtest_summary_full.csv", index_col="strategy")
        self.assertEqual(set(full.index), {"equal_weight", "risk_budget", "benchmark_60_40", "benchmark_60_40_long"})
        self.assertTrue((full["max_underwater_years"] >= 0).all())
        cw = pd.read_csv(self.processed / "backtest_class_weights.csv")
        self.assertTrue(np.allclose(cw.groupby(["date", "method"])["weight"].sum(), 1.0))
        self.assertIn("AVERAGE TARGET WEIGHT BY CLASS", out)
        self.assertTrue((full["costs_pln"] > 0).all())
        self.assertTrue((full["max_dd"] <= 0).all())
        self.assertTrue((full["final_value_pln"] > 0).all())
        w = pd.read_csv(self.processed / "backtest_weights.csv")
        self.assertTrue((w["weight"] > 0).all())
        self.assertLessEqual(w[w["asset"] != "cash"]["weight"].max(), 0.40 + 1e-9)
        self.assertIn("READ WITH CARE", out)

    def test_cost_override_and_errors(self):
        a = self.run_stage(["--cost-bps", "0"])[0]
        free = pd.read_csv(self.processed / "backtest_summary_full.csv", index_col="strategy")
        self.assertEqual(a, 0)
        self.assertTrue((free["costs_pln"] == 0).all())
        self.assertEqual(self.run_stage(["--profile", "nope"])[0], 1)
        (self.processed / "selection.csv").unlink()
        self.assertEqual(self.run_stage()[0], 1)


if __name__ == "__main__":
    unittest.main()
