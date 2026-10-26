from __future__ import annotations

import unittest
from pathlib import Path

from iris2.ml.datasets import assert_no_group_leakage, cohort_counts, load_cohort_a, representative_by_tube_date
from iris2.ml.features import model_feature_row, temporal_examples
from iris2.ml.readonly_db import database_sha256
from iris2.ml.snapshots import canonical_rows_sha256


DB_PATH = Path(__file__).resolve().parent / "data" / "heat_exchanger_db3.db"


class MLDatasetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.before = database_sha256(DB_PATH)
        cls.rows = load_cohort_a(DB_PATH, data_root=DB_PATH.parent)

    @classmethod
    def tearDownClass(cls) -> None:
        if database_sha256(DB_PATH) != cls.before:
            raise AssertionError("Operational database hash changed")

    def test_cohort_a_reconciles_and_is_traceable(self) -> None:
        self.assertEqual(len(self.rows), 6084)
        self.assertEqual(cohort_counts(self.rows)["A"], 6084)

    def test_snapshot_hash_is_order_independent(self) -> None:
        self.assertEqual(canonical_rows_sha256(self.rows), canonical_rows_sha256(reversed(self.rows)))

    def test_same_day_representative_is_conservative(self) -> None:
        sample = [dict(self.rows[0], tube_id=999, inspection_date="2025-01-01", wall_loss_percent=10, minimum_wall_thickness_mm=2.0, iris_tube_result_id=1), dict(self.rows[0], tube_id=999, inspection_date="2025-01-01", wall_loss_percent=20, minimum_wall_thickness_mm=1.8, iris_tube_result_id=2)]
        result = representative_by_tube_date(sample)
        self.assertEqual((result[0]["wall_loss_percent"], result[0]["minimum_wall_thickness_mm"]), (20.0, 1.8))
        self.assertEqual(result[0]["represented_result_ids"], [1, 2])

    def test_temporal_features_use_only_prior_values(self) -> None:
        base = dict(self.rows[0], tube_id=777, heat_exchanger_id=88)
        rows = [dict(base, iris_tube_result_id=1, inspection_date="2022-01-01", wall_loss_percent=10, minimum_wall_thickness_mm=2.5), dict(base, iris_tube_result_id=2, inspection_date="2023-01-01", wall_loss_percent=40, minimum_wall_thickness_mm=1.5)]
        example = temporal_examples(rows)[0]
        self.assertEqual(example["prior_wall_loss_percent"], 10)
        self.assertNotIn("target_wall_loss_percent", model_feature_row(example))

    def test_group_leakage_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "heat_exchanger_id"):
            assert_no_group_leakage([{"tube_id": 1, "heat_exchanger_id": 5}], [{"tube_id": 2, "heat_exchanger_id": 5}])


if __name__ == "__main__":
    unittest.main()
