import sys
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2.domain.inspection_lifecycle import current_installation_date, is_current_installation_inspection


class InstallationHistoryTests(unittest.TestCase):
    def test_preinstallation_history_is_read_only(self):
        self.assertFalse(is_current_installation_inspection(date(2020, 10, 27), date(2023, 12, 29)))

    def test_installation_day_is_current(self):
        self.assertTrue(is_current_installation_inspection(datetime(2023, 12, 29, 8), datetime(2023, 12, 29, 12)))

    def test_latest_known_installation_is_cutoff(self):
        self.assertFalse(is_current_installation_inspection(date(2023, 1, 1), date(2020, 1, 1), date(2024, 1, 1)))
        self.assertFalse(is_current_installation_inspection(date(2023, 1, 1), date(2024, 1, 1), date(2020, 1, 1)))

    def test_missing_installation_does_not_discard_dated_history(self):
        self.assertTrue(is_current_installation_inspection(date(2020, 1, 1), None))
        self.assertFalse(is_current_installation_inspection(None, date(2020, 1, 1)))
        self.assertEqual(current_installation_date(None, datetime(2023, 1, 1)), date(2023, 1, 1))


if __name__ == '__main__':
    unittest.main()
