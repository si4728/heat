from __future__ import annotations

import unittest

from iris2.ml.patterns import MODEL_FEATURES, build_tube_pattern_features, cluster_tube_patterns


def history_row(tube_id, date, loss, thickness=2.5):
    return {
        "plant_id": 1, "unit_id": 1, "heat_exchanger_id": tube_id // 10 + 1,
        "bundle_id": tube_id // 10 + 1, "tube_id": tube_id, "unit_code": "VCM1",
        "equipment_code": f"E-{tube_id // 10 + 1}", "tube_no": str(tube_id),
        "iris_inspection_id": tube_id * 10 + int(date[:4]),
        "iris_tube_result_id": tube_id * 10000 + int(date[:4]),
        "inspection_date": date, "source_document_id": 1, "source_page": 1,
        "wall_loss_percent": loss, "minimum_wall_thickness_mm": thickness,
    }


class MLPatternGroupingTest(unittest.TestCase):
    def test_single_inspection_tube_is_excluded(self) -> None:
        rows = [history_row(1, "2023-01-01", 10), history_row(2, "2023-01-01", 10), history_row(2, "2025-01-01", 12)]
        result = build_tube_pattern_features(rows)
        self.assertEqual([row["tube_id"] for row in result], [2])

    def test_identifiers_are_not_model_features(self) -> None:
        self.assertFalse(any(field.endswith("_id") for field in MODEL_FEATURES))

    def test_three_separated_patterns_are_stable(self) -> None:
        members = []
        for group, (level, slope, volatility) in enumerate(((5, 0.1, 0.2), (20, 4.0, 5.0), (55, 0.5, 2.0))):
            for index in range(20):
                value = level + index * 0.03
                members.append({
                    "tube_id": group * 100 + index, "latest_wall_loss_percent": value,
                    "maximum_wall_loss_percent": value + volatility,
                    "mean_wall_loss_percent": value - slope / 2,
                    "wall_loss_slope_pp_per_year": slope,
                    "wall_loss_volatility_pp": volatility,
                    "maximum_interval_change_pp": volatility * 2,
                    "inspection_count": 3, "latest_minimum_thickness_mm": 3.0 - value / 100,
                })
        result = cluster_tube_patterns(members)
        self.assertGreater(result["stability_ari"], 0.95)
        self.assertEqual({profile["pattern_code"] for profile in result["profiles"]}, {"STABLE_OR_LOW_CHANGE", "HIGH_VARIABILITY_OR_REVERSAL", "HIGH_WALL_LOSS"})


if __name__ == "__main__":
    unittest.main()
