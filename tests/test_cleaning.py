"""Tests for prm.data.cleaning and the bad_prints field of the universe file."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from prm.data.cleaning import repair_bad_prints
from prm.data.universe import load_universe


def frame():
    idx = pd.bdate_range("2025-10-20", periods=6)
    return pd.DataFrame({"adj_close": [63.0, 63.3, 63.5, 73.2, 63.1, 62.8]}, index=idx)


class TestRepair(unittest.TestCase):
    def test_bad_print_gets_previous_price_and_true_move_goes_to_next_day(self):
        df = frame()
        out, notes = repair_bad_prints(df, ("2025-10-23",))
        self.assertEqual(out.loc["2025-10-23", "adj_close"], 63.5)
        r = out["adj_close"].pct_change()
        self.assertAlmostEqual(r.loc["2025-10-23"], 0.0)
        self.assertAlmostEqual(r.loc["2025-10-24"], 63.1 / 63.5 - 1)          # the whole true move, nothing lost
        self.assertEqual(len(notes), 1)

    def test_input_is_not_modified(self):
        df = frame()
        repair_bad_prints(df, ("2025-10-23",))
        self.assertEqual(df.loc["2025-10-23", "adj_close"], 73.2)

    def test_missing_date_and_first_row_are_reported_not_guessed(self):
        df = frame()
        out, notes = repair_bad_prints(df, ("2020-01-01", "2025-10-20"))
        pd.testing.assert_frame_equal(out, df)
        self.assertEqual(len(notes), 2)
        self.assertTrue(all("nothing repaired" in n for n in notes))

    def test_no_dates_is_identity(self):
        df = frame()
        out, notes = repair_bad_prints(df, ())
        pd.testing.assert_frame_equal(out, df)
        self.assertEqual(notes, [])

    def test_two_dates(self):
        df = frame()
        df.loc["2025-10-21", "adj_close"] = 90.0
        out, _ = repair_bad_prints(df, ("2025-10-21", "2025-10-23"))
        self.assertEqual(out.loc["2025-10-21", "adj_close"], 63.0)
        self.assertEqual(out.loc["2025-10-23", "adj_close"], 63.5)


class TestUniverseField(unittest.TestCase):
    def write(self, text):
        d = tempfile.mkdtemp()
        p = Path(d) / "u.yaml"
        p.write_text(text)
        return p

    def test_real_file_has_the_declared_dates(self):
        _, assets = load_universe()
        by = {a.id: a for a in assets}
        self.assertEqual(by["world_low_vol"].bad_prints, ("2017-06-05", "2025-10-24"))
        self.assertEqual(by["em_xtrackers"].bad_prints, ("2025-10-24",))
        self.assertEqual(by["dev_equity"].bad_prints, ())

    def test_validation(self):
        ok = self.write('implementable:\n  - {id: a, name: A, risk_driver: r, bad_prints: ["2020-01-02", "2020-01-02"]}\n')
        self.assertEqual(load_universe(ok)[1][0].bad_prints, ("2020-01-02",))
        for bad in ('bad_prints: "2020-01-02"', 'bad_prints: ["x"]'):
            with self.assertRaises(ValueError):
                load_universe(self.write("implementable:\n  - {id: a, name: A, risk_driver: r, %s}\n" % bad))


if __name__ == "__main__":
    unittest.main()
