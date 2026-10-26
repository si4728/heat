from __future__ import annotations

import unittest

from iris2.ml.quality_gates import evaluate_pair


def row(**updates):
    value = {
        "plant_id": 1, "unit_id": 2, "heat_exchanger_id": 3, "bundle_id": 4,
        "bundle_lifecycle_no": 1, "tube_id": 5, "inspection_date": "2023-01-01",
        "minimum_wall_thickness_mm": 2.7, "wall_loss_depth_mm": 0.3,
        "wall_loss_percent": 10.0, "calculated_nominal_thickness_mm": 3.0,
    }
    value.update(updates)
    return value


class MLQualityGateGoldenCaseTest(unittest.TestCase):
    def test_valid_pair_passes_all_gates(self) -> None:
        current = row(inspection_date="2025-01-01", minimum_wall_thickness_mm=2.4, wall_loss_depth_mm=0.6, wall_loss_percent=20.0)
        self.assertTrue(evaluate_pair(row(), current)["passed"])

    def test_e105_pattern_fails_g4_and_g6(self) -> None:
        current = row(inspection_date="2025-01-01", minimum_wall_thickness_mm=2.8, wall_loss_depth_mm=0.3, wall_loss_percent=20.0, calculated_nominal_thickness_mm=3.1)
        result = evaluate_pair(row(), current)
        self.assertEqual(result["disposition"], "DQ-BLOCK")
        self.assertEqual({failure["gate"] for failure in result["failed_gates"]}, {"G4", "G5", "G6"})

    def test_missing_thickness_and_short_interval_retain_all_reasons(self) -> None:
        current = row(inspection_date="2023-03-01", minimum_wall_thickness_mm=None, calculated_nominal_thickness_mm=None)
        result = evaluate_pair(row(), current)
        self.assertEqual(result["disposition"], "DQ-HOLD")
        self.assertTrue({"G3", "G4", "G7"}.issubset({failure["gate"] for failure in result["failed_gates"]}))

    def test_identity_and_date_failures_block(self) -> None:
        current = row(tube_id=99, inspection_date="2022-12-31")
        result = evaluate_pair(row(), current)
        self.assertEqual(result["disposition"], "DQ-BLOCK")
        self.assertTrue({"G1", "G2"}.issubset({failure["gate"] for failure in result["failed_gates"]}))


if __name__ == "__main__":
    unittest.main()
