"""Tests for prm.selection.selector and stage 02 (synthetic data, no network)."""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from prm.data.universe import Asset, DEFAULT_UNIVERSE_PATH, load_universe
from prm.selection.selector import (
    build_candidates, explain_choice, high_correlation_pairs, select_per_category,
)

CRITERIA = {"min_history_years": 5, "listing_currency": "EUR"}


def asset(id_, category="cat", acc=True, ter=0.20, symbol=None):
    return Asset(id=id_, name=id_, tier="research_only", risk_driver="r", category=category,
                 yahoo_symbol=symbol or id_.upper(), symbols_to_try=(), isin=None, base_currency=None,
                 search_text=None, use_from=None, accumulating=acc, ter_pct=ter)


def report(rows):
    """rows: (asset_id, status, currency, history_years, issues)"""
    return pd.DataFrame(rows, columns=["asset_id", "status", "currency", "history_years", "issues"])


def winner(assets, rep):
    table = select_per_category(build_candidates(assets, rep), CRITERIA)
    return table, table[table["selected"]]["asset_id"].tolist()


class TestSelector(unittest.TestCase):
    def test_accumulating_beats_cheaper_distributing(self):
        a, b = asset("acc", acc=True, ter=0.20), asset("dist", acc=False, ter=0.05)
        rep = report([("acc", "ok", "EUR", 10, ""), ("dist", "ok", "EUR", 10, "")])
        self.assertEqual(winner([a, b], rep)[1], ["acc"])

    def test_fewer_warnings_beat_lower_cost(self):
        a, b = asset("clean", ter=0.20), asset("cheap", ter=0.10)
        rep = report([("clean", "ok", "EUR", 10, ""), ("cheap", "warning", "EUR", 10, "stale_prices")])
        self.assertEqual(winner([a, b], rep)[1], ["clean"])

    def test_lower_ter_wins_and_small_ter_gap_is_a_tie_broken_by_history(self):
        a, b, c = asset("a", ter=0.20), asset("b", ter=0.10), asset("c", ter=0.12)
        rep = report([("a", "ok", "EUR", 12, ""), ("b", "ok", "EUR", 8, ""), ("c", "ok", "EUR", 12, "")])
        self.assertEqual(winner([a, b], rep)[1], ["b"])           # 0.10 vs 0.20: clear gap
        self.assertEqual(winner([b, c], rep)[1], ["c"])           # 0.10 vs 0.12: tie, longer history wins

    def test_unknown_ter_ranks_after_known(self):
        a, b = asset("known", ter=0.30), asset("unknown", ter=None)
        rep = report([("known", "ok", "EUR", 10, ""), ("unknown", "ok", "EUR", 10, "")])
        self.assertEqual(winner([a, b], rep)[1], ["known"])

    def test_error_and_short_history_are_excluded_with_a_reason(self):
        a, b, c = asset("good"), asset("broken"), asset("young")
        rep = report([("good", "ok", "EUR", 10, ""), ("broken", "error", "EUR", 10, "duplicate_dates"),
                      ("young", "ok", "EUR", 2.0, "")])
        table, chosen = winner([a, b, c], rep)
        self.assertEqual(chosen, ["good"])
        reasons = table.set_index("asset_id")["excluded_because"]
        self.assertIn("error", reasons["broken"])
        self.assertIn("history", reasons["young"])

    def test_category_without_eligible_candidate_has_no_winner(self):
        a = asset("only")
        table, chosen = winner([a], report([("only", "error", "EUR", 10, "")]))
        self.assertEqual(chosen, [])
        self.assertEqual(explain_choice(table, "cat"), "no eligible candidate")

    def test_missing_from_report_is_not_downloaded_and_excluded(self):
        a = asset("ghost")
        table, chosen = winner([a], report([]))
        self.assertEqual(chosen, [])
        self.assertIn("not_downloaded", table.iloc[0]["excluded_because"])

    def test_one_winner_per_category_and_result_is_deterministic(self):
        assets = [asset("x1", "c1"), asset("x2", "c1"), asset("y1", "c2")]
        rep = report([(i, "ok", "EUR", 10, "") for i in ("x1", "x2", "y1")])
        t1, w1 = winner(assets, rep)
        t2, w2 = winner(list(reversed(assets)), rep)
        self.assertEqual(sorted(w1), ["x1", "y1"])
        self.assertEqual(sorted(w1), sorted(w2))

    def test_high_correlation_pairs(self):
        rng = np.random.default_rng(1)
        base = rng.normal(size=500)
        df = pd.DataFrame({"a": base, "b": base + rng.normal(scale=0.01, size=500), "c": rng.normal(size=500)})
        pairs = high_correlation_pairs(df)
        self.assertEqual([(p[0], p[1]) for p in pairs], [("a", "b")])

    def test_real_universe_loads_accumulating_and_ter(self):
        _, assets = load_universe(DEFAULT_UNIVERSE_PATH)
        by_id = {a.id: a for a in assets}
        self.assertTrue(all(a.accumulating is not None for a in assets))
        self.assertIs(by_id["eur_corp_bonds"].accumulating, False)
        self.assertIs(by_id["dev_equity"].accumulating, True)
        self.assertEqual(by_id["dev_equity"].ter_pct, 0.20)
        self.assertIsNone(by_id["eur_govt_bond"].ter_pct)


class TestStage02(unittest.TestCase):
    def test_end_to_end_writes_outputs(self):
        tmp = Path(tempfile.mkdtemp())
        processed = tmp / "processed"
        processed.mkdir()
        (tmp / "settings.yaml").write_text(
            f'data:\n  start_date: "2018-01-01"\n  raw_dir: {tmp / "raw"}\n  processed_dir: {processed}\n'
            "  max_cache_age_days: 1\nquality:\n  max_daily_move: 0.12\n  max_gap_days: 7\n  max_stale_days: 5\n")
        (tmp / "universe.yaml").write_text(
            "criteria:\n  min_history_years: 5\n  listing_currency: EUR\nimplementable:\n"
            "  - {id: a1, category: c, name: A1, risk_driver: r, yahoo_symbol: A1, accumulating: true, ter_pct: 0.2}\n"
            "  - {id: a2, category: c, name: A2, risk_driver: r, yahoo_symbol: A2, accumulating: true, ter_pct: 0.1}\n"
            "  - {id: b1, category: d, name: B1, risk_driver: r, yahoo_symbol: B1, accumulating: false}\n")
        idx = pd.bdate_range("2018-01-01", "2026-10-28", name="date")
        rng = np.random.default_rng(0)
        prices = pd.DataFrame({k: 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx)))) for k in ("a1", "a2", "b1")}, index=idx)
        prices.to_csv(processed / "prices_adj_close.csv")
        report(  # only the winners' columns matter here
            [("a1", "ok", "EUR", 8.8, ""), ("a2", "ok", "EUR", 8.8, ""), ("b1", "warning", "EUR", 8.8, "stale_prices")]
        ).to_csv(processed / "quality_report.csv", index=False)

        spec = importlib.util.spec_from_file_location("stage02", Path(__file__).resolve().parents[1] / "pipeline" / "02_selection.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = module.main(["--settings", str(tmp / "settings.yaml"), "--universe", str(tmp / "universe.yaml")])
        self.assertEqual(code, 0)
        chosen = pd.read_csv(processed / "selected_assets.csv")
        self.assertEqual(sorted(chosen["asset_id"]), ["a2", "b1"])
        self.assertEqual(sorted(pd.read_csv(processed / "prices_selected.csv", index_col=0).columns), ["a2", "b1"])
        self.assertIn("NOT confirmed accumulating", buf.getvalue())   # b1 is distributing

    def test_missing_stage_01_output_returns_error(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "settings.yaml").write_text(
            f'data:\n  start_date: "2018-01-01"\n  raw_dir: {tmp / "raw"}\n  processed_dir: {tmp / "p"}\n'
            "  max_cache_age_days: 1\nquality:\n  max_daily_move: 0.12\n  max_gap_days: 7\n  max_stale_days: 5\n")
        spec = importlib.util.spec_from_file_location("stage02b", Path(__file__).resolve().parents[1] / "pipeline" / "02_selection.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(["--settings", str(tmp / "settings.yaml")]), 1)


if __name__ == "__main__":
    unittest.main()
