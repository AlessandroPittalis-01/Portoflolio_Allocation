"""Tests for prm.data.universe."""

import tempfile
import unittest
from pathlib import Path

from prm.data.universe import DEFAULT_UNIVERSE_PATH, load_universe


def write_yaml(text: str) -> Path:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
    tmp.write(text)
    tmp.close()
    return Path(tmp.name)


class TestUniverse(unittest.TestCase):
    def test_real_file_loads(self):
        criteria, assets = load_universe(DEFAULT_UNIVERSE_PATH)
        by_id = {a.id: a for a in assets}
        self.assertEqual(criteria["min_history_years"], 5)
        self.assertEqual(by_id["dev_equity"].yahoo_symbol, "EUNL.DE")
        self.assertEqual(by_id["dev_equity"].tier, "implementable")
        self.assertEqual(len(by_id), len(assets))  # ids are unique

    def test_factor_etfs_skip_their_bad_first_months(self):
        _, assets = load_universe(DEFAULT_UNIVERSE_PATH)
        by_id = {a.id: a for a in assets}
        for asset_id in ("world_momentum", "world_quality", "world_value", "world_low_vol"):
            self.assertIsNotNone(by_id[asset_id].use_from, asset_id)
        self.assertEqual(by_id["world_low_vol"].use_from, "2013-05-01")

    def test_every_asset_has_a_category_and_some_categories_have_several_candidates(self):
        _, assets = load_universe(DEFAULT_UNIVERSE_PATH)
        self.assertTrue(all(a.category for a in assets))
        counts = {}
        for a in assets:
            counts[a.category] = counts.get(a.category, 0) + 1
        self.assertGreater(counts["world_developed"], 1)   # several candidates for one category
        self.assertGreaterEqual(len(counts), 19)           # the reference categories plus ours

    def test_symbols_confirmed_with_find_are_in_the_file(self):
        _, assets = load_universe(DEFAULT_UNIVERSE_PATH)
        by_id = {a.id: a for a in assets}
        expected = {"global_bond_unhedged": "EUNU.DE", "europe_equity": "VWCG.DE", "world_amundi": "CW8.PA",
                    "eur_inflation_linked": "IBCI.AS", "china_tech": "UIC2.DE", "eur_govt_bond": "EUNH.DE"}
        for asset_id, symbol in expected.items():
            self.assertEqual(by_id[asset_id].yahoo_symbol, symbol, asset_id)

    def test_use_from_is_read_as_iso_date_and_validated(self):
        path = write_yaml("implementable:\n  - {id: a, name: A, risk_driver: r, use_from: 2012-04-03}\n")
        _, assets = load_universe(path)
        self.assertEqual(assets[0].use_from, "2012-04-03")
        bad = write_yaml("implementable:\n  - {id: a, name: A, risk_driver: r, use_from: not-a-date}\n")
        with self.assertRaises(ValueError):
            load_universe(bad)

    def test_assets_without_isin_can_be_searched_by_text(self):
        _, assets = load_universe(DEFAULT_UNIVERSE_PATH)
        china = {a.id: a for a in assets}["china_tech"]
        self.assertIsNone(china.isin)
        self.assertEqual(china.search_text, "China technology UCITS ETF")

    def test_confirmed_and_unconfirmed_symbols(self):
        _, assets = load_universe(DEFAULT_UNIVERSE_PATH)
        by_id = {a.id: a for a in assets}
        self.assertEqual(by_id["em_equity"].yahoo_symbol, "IS3N.DE")
        # EUNA.DE is the XETRA line of the global aggregate EUR-hedged fund (it was wrongly given to eur_govt_bond)
        self.assertEqual(by_id["global_bond_hedged"].yahoo_symbol, "EUNA.DE")
        self.assertEqual(by_id["eur_govt_bond"].yahoo_symbol, "EUNH.DE")
        self.assertEqual(by_id["acwi_ishares"].yahoo_symbol, "IUSQ.DE")
        self.assertEqual(by_id["acwi_ishares"].use_from, "2012-04-03")   # provisional trim of a frozen start
        self.assertEqual(by_id["us_short_treasury"].use_from, "2019-02-22")
        self.assertIsNone(by_id["europe_rafi"].yahoo_symbol)             # the only asset still without a symbol

    def test_same_symbol_on_two_assets_is_rejected(self):
        item = "  - {id: %s, name: N, risk_driver: r, yahoo_symbol: SAME.DE}\n"
        path = write_yaml("implementable:\n" + item % "a" + item % "b")
        with self.assertRaises(ValueError):
            load_universe(path)

    def test_verify_becomes_none(self):
        path = write_yaml("implementable:\n  - id: a\n    name: A\n    risk_driver: r\n    isin: verify\n")
        _, assets = load_universe(path)
        self.assertIsNone(assets[0].isin)

    def test_missing_field_is_rejected(self):
        path = write_yaml("implementable:\n  - id: a\n    name: A\n")
        with self.assertRaises(ValueError):
            load_universe(path)

    def test_duplicate_id_is_rejected(self):
        item = "  - id: a\n    name: A\n    risk_driver: r\n"
        path = write_yaml("implementable:\n" + item + "research_only:\n" + item)
        with self.assertRaises(ValueError):
            load_universe(path)


if __name__ == "__main__":
    unittest.main()


class TestAssetClassAndCore(unittest.TestCase):
    def test_every_real_asset_has_a_class_and_core_assets_are_labelled(self):
        _, assets = load_universe(DEFAULT_UNIVERSE_PATH)
        self.assertTrue(all(a.asset_class in ("equity", "bond", "real", "cash") for a in assets))
        core = [a for a in assets if a.core]
        for cls in ("equity", "bond", "real", "cash"):
            self.assertTrue(any(a.asset_class == cls for a in core), cls)
        self.assertFalse(any(a.core for a in assets if a.id.startswith("world_momentum")))

    def test_unknown_class_is_rejected(self):
        import tempfile
        from pathlib import Path
        path = Path(tempfile.mkdtemp()) / "u.yaml"
        path.write_text("criteria: {}\nimplementable:\n  - id: x\n    asset_class: magic\n    category: c\n")
        with self.assertRaises(ValueError):
            load_universe(path)


class TestScope(unittest.TestCase):
    def test_equity_scopes_are_declared_for_core_equity_etfs(self):
        _, assets = load_universe(DEFAULT_UNIVERSE_PATH)
        by_id = {a.id: a for a in assets}
        for a in assets:
            if a.core and a.asset_class == "equity":
                self.assertIn(a.scope, ("broad", "regional"), a.id)
        self.assertEqual(by_id["allworld_vanguard"].scope, "broad")
        self.assertEqual(by_id["world_xtrackers"].scope, "broad")
        self.assertEqual(by_id["em_equity"].scope, "regional")

    def test_unknown_scope_is_rejected(self):
        import tempfile
        from pathlib import Path
        path = Path(tempfile.mkdtemp()) / "u.yaml"
        path.write_text("criteria: {}\nimplementable:\n  - id: x\n    name: x\n    risk_driver: r\n    scope: huge\n    category: c\n")
        with self.assertRaises(ValueError):
            load_universe(path)
