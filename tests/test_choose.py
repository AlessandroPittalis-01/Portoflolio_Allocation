"""Tests for the rule-based ETF choice (prm.allocation.choose)."""

import unittest

import numpy as np
import pandas as pd

from prm.allocation.choose import ChoiceRules, _pick_class, choose_etfs, eligibility

RULES = ChoiceRules(rho_max=0.90, max_etfs={"equity": 2, "bond": 3, "real": 1}, min_overlap_days=300, min_history_years=5)


def make(n=1500, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2019-01-01", periods=n, name="date")
    mkt, rates, credit = (rng.normal(0, s, n) for s in (0.010, 0.004, 0.004))
    r = pd.DataFrame(index=idx)
    r["world_a"] = mkt + rng.normal(0, 0.001, n)           # three versions of the same market
    r["world_b"] = mkt + rng.normal(0, 0.002, n)
    r["world_c"] = mkt + rng.normal(0, 0.003, n)
    r["europe"] = 0.6 * mkt + rng.normal(0, 0.008, n)      # related, but a different exposure
    r["govt"] = rates + rng.normal(0, 0.0005, n)
    r["govt2"] = rates + rng.normal(0, 0.0008, n)          # the same bet as govt
    r["corp"] = 0.5 * rates + credit
    r["linker"] = 0.4 * rates + rng.normal(0, 0.004, n)
    r["gold"] = rng.normal(0, 0.009, n)
    r["cash1"] = rng.normal(0, 0.0003, n)
    r["cash2"] = rng.normal(0, 0.0010, n)
    cls = {"world_a": "equity", "world_b": "equity", "world_c": "equity", "europe": "equity", "govt": "bond", "govt2": "bond",
           "corp": "bond", "linker": "bond", "gold": "real", "cash1": "cash", "cash2": "cash"}
    meta = pd.DataFrame({"asset_class": pd.Series(cls), "core": True, "selected": True, "currency": "EUR",
                         "history_years": 6.0, "excluded_because": ""})
    return r, meta


class TestChoose(unittest.TestCase):
    def setUp(self):
        self.r, self.meta = make()

    def decisions(self, meta=None, rules=RULES, r=None):
        out = choose_etfs(self.r if r is None else r, self.r if r is None else r, self.meta if meta is None else meta, rules)
        return out.set_index("asset_id")

    def test_clones_of_the_same_market_give_one_etf(self):
        d = self.decisions()
        self.assertEqual(int((d.loc[["world_a", "world_b", "world_c"], "decision"] == "chosen").sum()), 1)
        self.assertEqual(d.loc["world_a", "decision"], "chosen")             # the most central one (lowest noise)

    def test_second_equity_is_the_different_one(self):
        d = self.decisions()
        self.assertEqual(d.loc["europe", "decision"], "chosen")
        self.assertIn("most different", d.loc["europe", "reason"])

    def test_class_limit_is_respected_and_extras_are_explained(self):
        d = self.decisions()
        self.assertEqual(int(((d["asset_class"] == "bond") & (d["decision"] == "chosen")).sum()), 3)   # govt, corp, linker
        self.assertEqual(d.loc["govt2", "decision"], "rejected")
        self.assertIn("same exposure as govt", d.loc["govt2", "reason"])
        tight = ChoiceRules(0.9, {"equity": 1, "bond": 1, "real": 1}, 300, 5)
        d = self.decisions(rules=tight)
        self.assertEqual(int(((d["asset_class"] == "bond") & (d["decision"] == "chosen")).sum()), 1)
        self.assertIn("already has 1", d.loc["corp", "reason"] + d.loc["linker", "reason"])

    def test_first_etf_is_the_most_representative_not_the_first_in_alphabetical_order(self):
        rng = np.random.default_rng(5)
        n = 1200
        idx = pd.bdate_range("2019-01-01", periods=n, name="date")
        rates = rng.normal(0, 0.004, n)
        r = pd.DataFrame({"a_odd": 0.3 * rates + rng.normal(0, 0.005, n),          # alphabetically first, but atypical
                          "m_core": rates + rng.normal(0, 0.0015, n),
                          "z_other": 0.7 * rates + rng.normal(0, 0.003, n)}, index=idx)
        meta = pd.DataFrame({"asset_class": "bond", "core": True, "selected": True, "currency": "EUR",
                             "history_years": 6.0, "excluded_because": ""}, index=r.columns)
        d = choose_etfs(r, r, meta, ChoiceRules(0.9, {"bond": 2}, 300, 5)).set_index("asset_id")
        self.assertEqual(d.loc["m_core", "order"], 1)
        self.assertIn("most representative", d.loc["m_core", "reason"])
        self.assertNotEqual(d.loc["a_odd", "order"], 1)

    def test_order_column_gives_the_core_holding_first(self):
        d = self.decisions()
        eq = d[(d["asset_class"] == "equity") & (d["decision"] == "chosen")].sort_values("order")
        self.assertEqual(list(eq["order"]), [1, 2])
        self.assertEqual(eq.index[0], "world_a")

    def test_cash_is_the_one_with_lowest_volatility(self):
        d = self.decisions()
        self.assertEqual(d.loc["cash1", "decision"], "cash")
        self.assertEqual(d.loc["cash2", "decision"], "rejected")

    def test_not_core_wrong_currency_short_history_and_lost_category_are_rejected(self):
        meta = self.meta.copy()
        meta.loc["europe", "core"] = False
        meta.loc["corp", "currency"] = "USD"
        meta.loc["linker", "history_years"] = 3.0
        meta.loc["govt2", "selected"] = False
        d = self.decisions(meta)
        for a, text in (("europe", "not core"), ("corp", "USD"), ("linker", "history"), ("govt2", "stage 02")):
            self.assertEqual(d.loc[a, "decision"], "rejected", a)
            self.assertIn(text, d.loc[a, "reason"])

    def test_result_does_not_depend_on_column_order_or_on_returns_level(self):
        a = self.decisions()
        b = choose_etfs(self.r[self.r.columns[::-1]] + 0.001, self.r, self.meta.iloc[::-1], RULES).set_index("asset_id")
        self.assertEqual(a["decision"].sort_index().tolist(), b["decision"].sort_index().tolist())

    def test_short_common_window_drops_the_shortest_history(self):
        r = self.r.copy()
        r.loc[r.index[:1400], "govt"] = np.nan                  # only 100 days of govt
        meta = self.meta.copy()
        meta.loc["govt", "history_years"] = 5.5
        d = self.decisions(meta, r=r)
        self.assertEqual(d.loc["govt", "decision"], "rejected")
        self.assertIn("common window", d.loc["govt", "reason"])

    def test_class_with_no_candidate_is_simply_absent(self):
        meta = self.meta.copy()
        meta.loc["gold", "core"] = False
        d = self.decisions(meta)
        self.assertNotIn("chosen", set(d.loc[d["asset_class"] == "real", "decision"]))

    def test_eligibility_is_empty_for_good_assets(self):
        self.assertTrue((eligibility(self.meta, RULES) == "").all())


def corr_matrix(ids, pairs):
    c = pd.DataFrame(np.eye(len(ids)), index=ids, columns=ids)
    for (a, b), v in pairs.items():
        c.loc[a, b] = c.loc[b, a] = v
    return c


class TestStability(unittest.TestCase):
    RULES = ChoiceRules(0.90, {"bond": 2}, 300, 5, "EUR", 0.10)

    def pick(self, corr, incumbents=None, rules=None):
        return _pick_class(corr, rules or self.RULES, 2, incumbents)[0]

    def test_incumbent_second_etf_is_kept_when_the_challenger_is_only_slightly_better(self):
        c = corr_matrix(["A", "B", "C"], {("A", "B"): 0.75, ("A", "C"): 0.80, ("B", "C"): 0.40})
        self.assertEqual(self.pick(c), ["A", "B"])                                   # one-off choice: lowest correlation
        self.assertEqual(self.pick(c, ["A", "C"]), ["A", "C"])                       # 0.80 is within 0.10 of 0.75

    def test_incumbent_is_replaced_when_the_challenger_is_clearly_better(self):
        c = corr_matrix(["A", "B", "C"], {("A", "B"): 0.60, ("A", "C"): 0.80, ("B", "C"): 0.40})
        self.assertEqual(self.pick(c, ["A", "C"]), ["A", "B"])

    def test_margin_zero_switches_the_stability_rule_off(self):
        c = corr_matrix(["A", "B", "C"], {("A", "B"): 0.75, ("A", "C"): 0.80, ("B", "C"): 0.40})
        off = ChoiceRules(0.90, {"bond": 2}, 300, 5, "EUR", 0.0)
        self.assertEqual(self.pick(c, ["A", "C"], off), ["A", "B"])

    def test_incumbent_represents_its_group_even_if_a_clone_is_more_central(self):
        c = corr_matrix(["A", "A2", "B"], {("A", "A2"): 0.99, ("A", "B"): 0.80, ("A2", "B"): 0.70})
        self.assertEqual(self.pick(c)[0], "A")                                       # A is more central
        self.assertEqual(self.pick(c, ["A2"])[0], "A2")                              # but A2 is held: no switch for a clone

    def test_incumbent_core_is_kept_when_representativeness_is_close(self):
        c = corr_matrix(["A", "B", "C"], {("A", "B"): 0.80, ("A", "C"): 0.50, ("B", "C"): 0.55})
        self.assertEqual(self.pick(c)[0], "B")                                       # B has the highest average correlation
        self.assertEqual(self.pick(c, ["A"])[0], "A")                                # A is within 0.10 of B and is held

    def test_ineligible_incumbent_is_ignored(self):
        c = corr_matrix(["A", "B"], {("A", "B"): 0.6})
        self.assertEqual(sorted(self.pick(c, ["gone"])), ["A", "B"])


if __name__ == "__main__":
    unittest.main()
