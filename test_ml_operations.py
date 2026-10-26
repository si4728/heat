from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from iris2.ml.operations import run_anomaly_quality_operation


class MLAnomalyQualityOperationsTest(unittest.TestCase):
    def test_operation_writes_versioned_artifacts_and_preserves_database(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = root / "data"
            data.mkdir()
            database = data / "operational.db"
            connection = sqlite3.connect(database)
            try:
                connection.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY)")
                connection.commit()
            finally:
                connection.close()
            before = database.read_bytes()
            source_rows = [{
                "plant_id": 1, "unit_id": 1, "heat_exchanger_id": 1,
                "bundle_id": 1, "tube_id": 1, "iris_inspection_id": 1,
                "iris_tube_result_id": 1, "inspection_date": "2026-01-01",
                "source_document_id": 1, "source_page": 1,
            }]
            anomaly = {
                "model_version": "test-model", "row_count": 1,
                "evaluation": {
                    "status": "PASS_WITH_NOTE", "hard_gate_critical_omissions": 0,
                    "hard_gate_rows": 1, "automatic_decision_enabled": False,
                },
                "quality_detection": {
                    "row_count": 1, "flagged_row_count": 1,
                    "hard_gate_row_count": 1, "ml_anomaly_row_count": 1,
                },
                "top_30": [],
            }
            artifacts = root / "outputs" / "ml_implementation"
            with (
                patch("iris2.ml.operations.load_cohort_a", return_value=source_rows),
                patch("iris2.ml.operations.cohort_counts", return_value={"A": 1, "B_tubes": 0, "C_tubes": 0}),
                patch("iris2.ml.operations.latest_labels_by_result", return_value={}),
                patch("iris2.ml.operations.run_priority_model", return_value=anomaly),
            ):
                result = run_anomaly_quality_operation(
                    database, artifacts, data / "reviews.db", run_id="operation-test",
                )
            self.assertEqual(result["status"], "PASS_WITH_NOTE")
            self.assertFalse(result["operational_database_changed"])
            self.assertEqual(database.read_bytes(), before)
            run = artifacts / "operation-test"
            for relative in (
                "run_summary.json", "stage_2_result.json",
                "data/dataset_snapshot.json", "evaluation/anomaly_pilot.json",
                "evaluation/quality_detection.json",
            ):
                self.assertTrue((run / relative).is_file(), relative)
            quality = json.loads((run / "evaluation" / "quality_detection.json").read_text(encoding="utf-8"))
            self.assertFalse(quality["automatic_engineering_decision_enabled"])

    def test_existing_lock_blocks_duplicate_operation(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = root / "data"
            data.mkdir()
            database = data / "operational.db"
            sqlite3.connect(database).close()
            artifacts = root / "outputs" / "ml_implementation"
            artifacts.mkdir(parents=True)
            lock = artifacts / ".anomaly-quality.lock"
            lock.write_text("running", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "already running"):
                run_anomaly_quality_operation(database, artifacts, data / "reviews.db")
            self.assertEqual(lock.read_text(encoding="utf-8"), "running")


if __name__ == "__main__":
    unittest.main()
