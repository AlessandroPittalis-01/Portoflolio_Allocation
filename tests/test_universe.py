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

    def test_every_asset_has_a_category_and_some_categories_have_several_candidates(self):
        _, assets = load_universe(DEFAULT_UNIVERSE_PATH)
        self.assertTrue(all(a.category for a in assets))
        counts = {}
        for a in assets:
            counts[a.category] = counts.get(a.category, 0) + 1
        self.assertGreater(counts["world_developed"], 1)   # several candidates for one category
        self.assertGreaterEqual(len(counts), 19)           # the reference categories plus ours

    def test_assets_without_isin_can_be_searched_by_text(self):
        _, assets = load_universe(DEFAULT_UNIVERSE_PATH)
        china = {a.id: a for a in assets}["china_tech"]
        self.assertIsNone(china.isin)
        self.assertEqual(china.search_text, "China technology UCITS ETF")

    def test_confirmed_and_unconfirmed_symbols(self):
        _, assets = load_universe(DEFAULT_UNIVERSE_PATH)
        by_id = {a.id: a for a in assets}
        self.assertEqual(by_id["em_equity"].yahoo_symbol, "IS3N.DE")
        # AGGH.DE was tested and does not exist: the asset is still unconfirmed, with new guesses
        self.assertIsNone(by_id["global_bond_hedged"].yahoo_symbol)
        self.assertEqual(by_id["global_bond_hedged"].symbols_to_try, ("AGGH.AS", "AGGH.MI"))

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
