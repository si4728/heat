import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from iris2.backfill_reported_total_tube_counts import prepare_backfill
from iris2.iris_json_validator import report_parts
from iris2.iris_v2_importer import reported_total_tube_count


def report(total_summary=None, total_map=None, equipment="E-100"):
    value = {
        "report": {
            "equipment_id": equipment,
            "iris_report_details": {"inspection_summary": {}},
        },
        "summary_reference": {},
        "tube_map": {},
    }
    if total_summary is not None:
        value["summary_reference"]["total_tubes_summary"] = total_summary
    if total_map is not None:
        value["tube_map"]["total_tubes"] = total_map
    return json.dumps(value)


class ReportedTotalTubeBackfillTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "test.db"
        connection = sqlite3.connect(self.db)
        connection.executescript(
            """
            CREATE TABLE source_document (
                source_document_id INTEGER PRIMARY KEY,
                source_file TEXT NOT NULL
            );
            CREATE TABLE iris_inspection (
                iris_inspection_id INTEGER PRIMARY KEY,
                source_document_id INTEGER NOT NULL,
                total_tube_count_reported INTEGER,
                raw_report_json TEXT NOT NULL
            );
            INSERT INTO source_document VALUES (1, 'test.json');
            """
        )
        rows = [
            (1, 1, None, report(100, 100, "E-100")),
            (2, 1, None, report(None, 80, "E-200")),
            (3, 1, None, report(120, 60, "E-300")),
            (4, 1, None, report(None, None, "E-400")),
            (5, 1, 55, report(55, 55, "E-500")),
        ]
        connection.executemany(
            "INSERT INTO iris_inspection VALUES (?, ?, ?, ?)", rows
        )
        connection.commit()
        connection.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_dry_run_classifies_without_writing(self):
        result = prepare_backfill(self.db)
        self.assertEqual(result["db_null_count"], 4)
        self.assertEqual(result["eligible_update_count"], 1)
        self.assertEqual(result["classification_counts"], {
            "MAP_ONLY_REVIEW": 1,
            "NO_SOURCE": 1,
            "SAFE_SUMMARY_AGREED": 1,
            "SOURCE_CONFLICT_REVIEW": 1,
        })
        connection = sqlite3.connect(self.db)
        try:
            self.assertIsNone(connection.execute(
                "SELECT total_tube_count_reported FROM iris_inspection WHERE iris_inspection_id=1"
            ).fetchone()[0])
        finally:
            connection.close()

    def test_importer_reads_detail_summary_before_tube_map(self):
        value = json.loads(report(None, 74, "E-581A"))
        value["report"]["iris_report_details"]["inspection_summary"] = {
            "total_tube_count": 148,
        }
        self.assertEqual(reported_total_tube_count(report_parts(value)), 148)

    def test_apply_only_updates_safe_candidates_and_creates_backup(self):
        backup_dir = Path(self.temp.name) / "backups"
        result = prepare_backfill(self.db, apply=True, backup_dir=backup_dir)
        self.assertEqual(result["applied_update_count"], 1)
        self.assertTrue(Path(result["backup_path"]).exists())
        connection = sqlite3.connect(self.db)
        try:
            values = dict(connection.execute(
                "SELECT iris_inspection_id, total_tube_count_reported FROM iris_inspection"
            ))
        finally:
            connection.close()
        self.assertEqual(values, {1: 100, 2: None, 3: None, 4: None, 5: 55})


if __name__ == "__main__":
    unittest.main()
