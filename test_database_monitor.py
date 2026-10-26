from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from iris2.database_monitor import (
    database_lock_summary,
    is_database_lock_error,
    lock_event_path,
    record_database_lock,
)


class DatabaseMonitorTest(unittest.TestCase):
    def test_lock_error_detection_and_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            self.assertTrue(is_database_lock_error("database is locked"))
            self.assertTrue(is_database_lock_error("database table is locked: sample"))
            self.assertFalse(is_database_lock_error("no such table"))

            record_database_lock(db_path, "database is locked", "UPDATE sample SET value=1")
            summary = database_lock_summary(db_path)

            self.assertEqual(summary["last_24_hours"], 1)
            self.assertEqual(summary["last_7_days"], 1)
            self.assertEqual(summary["total"], 1)
            self.assertEqual(summary["events"][0]["operation"], "UPDATE")
            self.assertEqual(summary["log_path"], str(lock_event_path(db_path)))


if __name__ == "__main__":
    unittest.main()
