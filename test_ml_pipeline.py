from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from iris2.ml.pipeline import run_governed_pipeline


class MLPipelineTest(unittest.TestCase):
    def test_hold_stops_later_stages_and_preserves_database(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = root / "data"
            data.mkdir()
            database = data / "test.db"
            connection = sqlite3.connect(database)
            try:
                connection.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY)")
                connection.commit()
            finally:
                connection.close()
            before = database.read_bytes()
            rows = [{"iris_tube_result_id": 1}]
            with (
                patch("iris2.ml.pipeline.require_ml_environment", return_value={"python": "test"}),
                patch("iris2.ml.pipeline.inspect_environment", return_value={"python": "test"}),
                patch("iris2.ml.pipeline.load_cohort_a", return_value=rows),
                patch("iris2.ml.pipeline.cohort_counts", return_value={"A": 6084, "B_tubes": 1435, "C_tubes": 1134}),
                patch("iris2.ml.pipeline.run_priority_model", return_value={
                    "model_version": "test", "row_count": 1,
                    "evaluation": {"status": "PASS_WITH_NOTE"}, "top_30": [],
                }),
                patch("iris2.ml.pipeline.evaluate_trend_pilot", return_value={
                    "status": "HOLD", "hold_reason_codes": ["TEST_HOLD"], "predictions": [],
                }),
                patch("iris2.ml.pipeline.run_spatial_pilot") as spatial,
            ):
                summary = run_governed_pipeline(
                    database, root / "outputs" / "ml_implementation",
                    verified_test_count=137, run_id="test-run",
                )
            self.assertEqual(summary["status"], "HOLD")
            self.assertEqual(summary["blocked_before_stage"], 5)
            self.assertEqual(summary["stage_statuses"]["4"], "HOLD")
            spatial.assert_not_called()
            self.assertEqual(database.read_bytes(), before)
            self.assertTrue((root / "outputs" / "ml_implementation" / "test-run" / "run_summary.json").is_file())


if __name__ == "__main__":
    unittest.main()
