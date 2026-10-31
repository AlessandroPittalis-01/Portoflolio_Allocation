"""Tests for prm.config.

These tests use the standard ``unittest`` style: pytest runs them without changes,
and they also run with ``python -m unittest``.
"""

import tempfile
import unittest
from pathlib import Path

from prm.config import DEFAULT_PROFILES_PATH, load_profiles

# A minimal valid profile, reused by the tests below.
VALID_PROFILE = """
profiles:
  demo:
    target_vol: 0.08
    dd_alert: -0.10
    dd_review: -0.18
    max_weight_per_etf: 0.40
    equity_cap: 0.60
    rebalance_band_pp: 0.05
    stop_contributing_dd: -0.25
"""


def write_yaml(text: str) -> Path:
    """Write ``text`` to a temporary file and return its path."""
    tmp = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
    tmp.write(text)
    tmp.close()
    return Path(tmp.name)


class TestLoadProfiles(unittest.TestCase):
    def test_real_config_file_is_valid(self):
        """The profiles shipped in config/profiles.yaml must pass every rule."""
        profiles = load_profiles(DEFAULT_PROFILES_PATH)
        self.assertEqual(set(profiles), {"prudent", "balanced", "dynamic", "owner"})

    def test_owner_values(self):
        owner = load_profiles(DEFAULT_PROFILES_PATH)["owner"]
        self.assertEqual(owner.stop_contributing_dd, -0.25)
        self.assertEqual(owner.monthly_contribution_eur_range, (500, 800))

    def test_valid_profile_loads(self):
        profiles = load_profiles(write_yaml(VALID_PROFILE))
        self.assertAlmostEqual(profiles["demo"].target_vol, 0.08)

    def test_unknown_parameter_is_rejected(self):
        """A typo in a parameter name must fail loudly."""
        bad = VALID_PROFILE + "    target_volatility: 0.1\n"
        with self.assertRaises(ValueError):
            load_profiles(write_yaml(bad))

    def test_missing_parameter_is_rejected(self):
        bad = VALID_PROFILE.replace("    equity_cap: 0.60\n", "")
        with self.assertRaises(ValueError):
            load_profiles(write_yaml(bad))

    def test_positive_drawdown_is_rejected(self):
        bad = VALID_PROFILE.replace("dd_alert: -0.10", "dd_alert: 0.10")
        with self.assertRaises(ValueError):
            load_profiles(write_yaml(bad))

    def test_review_less_severe_than_alert_is_rejected(self):
        bad = VALID_PROFILE.replace("dd_review: -0.18", "dd_review: -0.05")
        with self.assertRaises(ValueError):
            load_profiles(write_yaml(bad))

    def test_review_deeper_than_stop_level_is_rejected(self):
        """IPS rule: the review must come before the investor would stop contributing."""
        bad = VALID_PROFILE.replace("dd_review: -0.18", "dd_review: -0.30")
        with self.assertRaises(ValueError):
            load_profiles(write_yaml(bad))

    def test_vol_out_of_range_is_rejected(self):
        bad = VALID_PROFILE.replace("target_vol: 0.08", "target_vol: 8")
        with self.assertRaises(ValueError):
            load_profiles(write_yaml(bad))


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Data settings (config/settings.yaml)
# ---------------------------------------------------------------------------
from prm.config import DEFAULT_SETTINGS_PATH, load_data_settings  # noqa: E402

VALID_SETTINGS = """
data:
  start_date: "2010-01-01"
  raw_dir: data/raw
  processed_dir: data/processed
  max_cache_age_days: 1
quality:
  max_daily_move: 0.12
  max_gap_days: 7
  max_stale_days: 5
"""


class TestDataSettings(unittest.TestCase):
    def test_real_settings_file_is_valid(self):
        settings = load_data_settings(DEFAULT_SETTINGS_PATH)
        self.assertEqual(settings.start_date, "2010-01-01")
        self.assertTrue(settings.raw_dir.is_absolute())  # resolved from the repository root

    def test_unquoted_date_is_accepted(self):
        text = VALID_SETTINGS.replace('"2010-01-01"', "2010-01-01")
        self.assertEqual(load_data_settings(write_yaml(text)).start_date, "2010-01-01")

    def test_missing_key_is_rejected(self):
        with self.assertRaises(ValueError):
            load_data_settings(write_yaml(VALID_SETTINGS.replace("  max_gap_days: 7\n", "")))

    def test_bad_date_is_rejected(self):
        with self.assertRaises(ValueError):
            load_data_settings(write_yaml(VALID_SETTINGS.replace("2010-01-01", "not-a-date")))

    def test_out_of_range_values_are_rejected(self):
        for old, new in [("max_daily_move: 0.12", "max_daily_move: 2"), ("max_stale_days: 5", "max_stale_days: 1")]:
            with self.assertRaises(ValueError):
                load_data_settings(write_yaml(VALID_SETTINGS.replace(old, new)))
