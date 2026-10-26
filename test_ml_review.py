from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from iris2.ml.readonly_db import database_sha256
from iris2.ml.review import latest_run_directory, load_latest_ml_review


class MLReviewArtifactTest(unittest.TestCase):
    def test_latest_run_can_be_selected_by_required_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            older = root / "run-1"
            newer = root / "run-2"
            (older / "evaluation").mkdir(parents=True)
            (newer / "evaluation").mkdir(parents=True)
            for run in (older, newer):
                (run / "run_summary.json").write_text("{}", encoding="utf-8")
            (older / "evaluation" / "spatial_pilot.json").write_text("{}", encoding="utf-8")
            (newer / "evaluation" / "anomaly_pilot.json").write_text("{}", encoding="utf-8")
            self.assertEqual(
                latest_run_directory(root, "evaluation/spatial_pilot.json"), older
            )
            self.assertEqual(
                latest_run_directory(root, "evaluation/anomaly_pilot.json"), newer
            )

    def test_matching_snapshot_is_available_and_filterable(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); database = root / "data.db"; run = root / "artifacts" / "run-1"; (run / "evaluation").mkdir(parents=True)
            connection = sqlite3.connect(database)
            try:
                connection.execute("CREATE TABLE sample(id INTEGER)"); connection.commit()
            finally:
                connection.close()
            digest = database_sha256(database)
            (run / "run_summary.json").write_text(json.dumps({"run_id": "run-1", "database_sha256_after": digest}), encoding="utf-8")
            (run / "data").mkdir()
            (run / "data" / "dataset_snapshot.json").write_text(json.dumps({"rows_sha256": "not-needed-for-physical-match"}), encoding="utf-8")
            artifact = {"model_version": "test", "row_count": 1, "evaluation": {"status": "PASS_WITH_NOTE", "hard_gate_rows": 1, "review_label_count": 0, "automatic_decision_enabled": False}, "top_30": [{"iris_tube_result_id": 10, "iris_inspection_id": 20, "tube_id": 30, "equipment_code": "E-100", "unit_code": "VCM1", "review_priority_rank": 1, "hard_gate": True}]}
            (run / "evaluation" / "anomaly_pilot.json").write_text(json.dumps(artifact), encoding="utf-8")
            result = load_latest_ml_review(database, root / "artifacts", unit_code="VCM1", hard_only=True)
            self.assertTrue(result["enabled"])
            self.assertEqual(result["rows"][0]["iris_tube_result_id"], 10)

    def test_changed_database_disables_stale_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); database = root / "data.db"; run = root / "artifacts" / "run-1"; (run / "evaluation").mkdir(parents=True)
            connection = sqlite3.connect(database)
            try:
                connection.execute("CREATE TABLE sample(id INTEGER)"); connection.commit()
            finally:
                connection.close()
            (run / "run_summary.json").write_text(json.dumps({"database_sha256_after": "0" * 64}), encoding="utf-8")
            (run / "data").mkdir()
            (run / "data" / "dataset_snapshot.json").write_text(json.dumps({}), encoding="utf-8")
            (run / "evaluation" / "anomaly_pilot.json").write_text("{}", encoding="utf-8")
            result = load_latest_ml_review(database, root / "artifacts")
            self.assertEqual(result["availability"], "STALE")
            self.assertFalse(result["enabled"])


if __name__ == "__main__":
    unittest.main()
