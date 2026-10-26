from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path

from iris2.backup_manager import (
    backup_management_data,
    backup_paths,
    backup_schedule_status,
    load_backup_settings,
    read_backup_log,
    run_database_backup,
    run_database_restore,
    run_due_backup,
    save_backup_settings,
)


class BackupManagerTest(unittest.TestCase):
    def test_settings_backup_log_and_retention(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir) / "app"
            db_path = app_dir / "data" / "source.db"
            db_path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(db_path)) as connection:
                connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
                connection.execute("INSERT INTO sample(value) VALUES ('backup-test')")
                connection.commit()

            defaults = load_backup_settings(app_dir)
            self.assertTrue(defaults["enabled"])
            self.assertEqual(defaults["frequency"], "daily")
            settings_path = backup_paths(app_dir)["settings"]
            self.assertEqual(json.loads(settings_path.read_text(encoding="utf-8")), defaults)

            saved = save_backup_settings(app_dir, {
                **defaults,
                "frequency": "weekly",
                "scheduled_time": "03:15",
                "weekday": 6,
                "retention_count": 1,
            })
            self.assertEqual(saved["weekday"], 6)

            first = run_database_backup(app_dir, db_path, requested_by="unit-test")
            second = run_database_backup(app_dir, db_path, requested_by="unit-test")
            self.assertEqual(first["status"], "SUCCESS")
            self.assertEqual(second["status"], "SUCCESS")
            self.assertEqual(first["integrity_check"], "ok")
            self.assertTrue(first["sha256"])
            self.assertEqual(len(list(backup_paths(app_dir)["files"].glob("*.db"))), 1)

            records = read_backup_log(app_dir)
            self.assertEqual(len(records), 2)
            self.assertEqual(set(records[0]), set(records[1]))
            self.assertEqual(records[0]["backup_content"], ["sqlite_database"])
            data = backup_management_data(app_dir, db_path)
            self.assertEqual(len(data["files"]), 1)
            self.assertEqual(data["last_success"]["status"], "SUCCESS")

    def test_daily_schedule_slot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir)
            save_backup_settings(app_dir, {
                "enabled": True,
                "frequency": "daily",
                "scheduled_time": "02:00",
                "weekday": 0,
                "retention_count": 30,
            })
            now = datetime.now().astimezone().replace(hour=3, minute=0, second=0, microsecond=0)
            status = backup_schedule_status(app_dir, now=now)
            self.assertTrue(status["due"])
            self.assertIn("T02:00:00", status["scheduled_for"])

    def test_due_backup_catches_up_once_and_clears_due_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir) / "app"
            db_path = app_dir / "data" / "source.db"
            db_path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(db_path)) as connection:
                connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
                connection.commit()
            save_backup_settings(app_dir, {
                "enabled": True, "frequency": "daily", "scheduled_time": "00:00",
                "weekday": 0, "retention_count": 30,
            })
            first = run_due_backup(app_dir, db_path)
            second = run_due_backup(app_dir, db_path)
            self.assertIsNotNone(first)
            self.assertEqual(first["status"], "SUCCESS")
            self.assertEqual(first["trigger"], "scheduled")
            self.assertIsNone(second)
            self.assertFalse(backup_schedule_status(app_dir)["due"])

    def test_restore_validates_candidate_and_keeps_pre_restore_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir) / "app"
            db_path = app_dir / "data" / "source.db"
            db_path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(db_path)) as connection:
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
                connection.execute("INSERT INTO sample(value) VALUES ('before')")
                connection.commit()

            backup = run_database_backup(app_dir, db_path, requested_by="unit-test")
            backup_name = Path(backup["backup_file"]).name
            with closing(sqlite3.connect(db_path)) as connection:
                connection.execute("UPDATE sample SET value='after'")
                connection.commit()

            restored = run_database_restore(
                app_dir, db_path, backup_name,
                requested_by="unit-test", reason="정상 복구 시험",
            )
            self.assertEqual(restored["status"], "SUCCESS")
            self.assertTrue(Path(restored["pre_restore_file"]).is_file())
            self.assertTrue(restored["restored_sha256"])
            self.assertTrue(restored["sha256"])
            with closing(sqlite3.connect(db_path)) as connection:
                self.assertEqual(connection.execute("SELECT value FROM sample").fetchone()[0], "before")

            damaged = backup_paths(app_dir)["files"] / "iris_db_damaged.db"
            damaged.write_bytes(b"not a sqlite database")
            blocked = run_database_restore(
                app_dir, db_path, damaged.name,
                requested_by="unit-test", reason="손상 파일 차단 시험",
            )
            self.assertEqual(blocked["status"], "FAILED")
            with closing(sqlite3.connect(db_path)) as connection:
                self.assertEqual(connection.execute("SELECT value FROM sample").fetchone()[0], "before")


if __name__ == "__main__":
    unittest.main()
