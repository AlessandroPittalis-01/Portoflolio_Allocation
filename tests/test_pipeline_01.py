"""End-to-end test of stage 01 with a fake source (no network)."""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from helpers import make_prices
from prm.data.sources import PriceSource

STAGE_PATH = Path(__file__).resolve().parents[1] / "pipeline" / "01_sourcing.py"


def load_stage():
    """The file name starts with a digit, so it cannot be imported with a normal import."""
    spec = importlib.util.spec_from_file_location("stage01", STAGE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeSource(PriceSource):
    name = "fake"

    def fetch(self, symbol, start, end=None):
        df = make_prices(start="2018-01-01")
        if symbol == "BAD":  # a series with duplicated dates: the pipeline must reject it
            df = pd.concat([df, df.iloc[[5]]])
        return df

    def search(self, query, max_results=10):
        return [{"symbol": "FOUND.DE", "exchDisp": "XETRA", "quoteType": "ETF", "longname": f"Fund for {query}"}]


SETTINGS = """
data:
  start_date: "2018-01-01"
  raw_dir: {raw}
  processed_dir: {processed}
  max_cache_age_days: 1
quality:
  max_daily_move: 0.12
  max_gap_days: 7
  max_stale_days: 5
"""

UNIVERSE = """
criteria:
  min_history_years: 5
implementable:
  - {id: good, name: Good, risk_driver: r, yahoo_symbol: GOOD}
  - {id: bad, name: Bad, risk_driver: r, yahoo_symbol: BAD}
  - {id: nosym, name: NoSym, risk_driver: r, yahoo_symbol: verify, yahoo_symbol_try: [TRY1]}
"""


class TestStage01(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.processed = root / "processed"
        (root / "settings.yaml").write_text(SETTINGS.format(raw=root / "raw", processed=self.processed))
        (root / "universe.yaml").write_text(UNIVERSE)
        self.base_args = ["--settings", str(root / "settings.yaml"), "--universe", str(root / "universe.yaml")]

    def tearDown(self):
        self.tmp.cleanup()

    def run_stage(self, extra):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = load_stage().main(self.base_args + extra, source=FakeSource())
        return code, buffer.getvalue()

    def test_normal_run_writes_clean_tables_only_for_valid_series(self):
        code, _ = self.run_stage([])
        self.assertEqual(code, 0)
        prices = pd.read_csv(self.processed / "prices_adj_close.csv", index_col="date", parse_dates=True)
        self.assertEqual(list(prices.columns), ["good"])  # 'bad' has errors, 'nosym' has no symbol

        report = pd.read_csv(self.processed / "quality_report.csv").set_index("asset_id")
        self.assertEqual(report.loc["bad", "status"], "error")
        self.assertEqual(report.loc["nosym", "status"], "no_symbol")
        self.assertIn(report.loc["good", "status"], ("ok", "warning"))

    def test_probe_writes_nothing_to_processed(self):
        code, output = self.run_stage(["--probe"])
        self.assertEqual(code, 0)
        self.assertIn("TRY1", output)
        self.assertFalse(self.processed.exists())

    def test_find_lists_listings_for_unconfirmed_assets_only(self):
        code, output = self.run_stage(["--find"])
        self.assertEqual(code, 0)
        self.assertIn("FOUND.DE", output)
        self.assertIn("nosym", output)
        self.assertNotIn("[good]", output)  # confirmed assets are skipped
        self.assertFalse(self.processed.exists())

    def test_unknown_asset_id_returns_error_code(self):
        code, _ = self.run_stage(["--assets", "does_not_exist"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
