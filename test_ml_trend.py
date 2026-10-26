from __future__ import annotations

import unittest

from iris2.ml.trend import (
    baseline_prediction,
    directional_shift_diagnostics,
    model_predictions,
    validation_samples,
)


class MLTrendTest(unittest.TestCase):
    def test_baseline_uses_more_conservative_positive_rate(self) -> None:
        history = [
            {"inspection_date": "2020-01-01", "minimum_wall_thickness_mm": 3.0},
            {"inspection_date": "2021-01-01", "minimum_wall_thickness_mm": 2.9},
            {"inspection_date": "2022-01-01", "minimum_wall_thickness_mm": 2.7},
        ]
        prediction = baseline_prediction(history, "2023-01-01")
        self.assertAlmostEqual(prediction, 2.5, places=2)

    def test_negative_corrosion_rate_is_not_promoted(self) -> None:
        history = [
            {"inspection_date": "2020-01-01", "minimum_wall_thickness_mm": 2.0},
            {"inspection_date": "2022-01-01", "minimum_wall_thickness_mm": 2.1},
        ]
        self.assertIsNone(baseline_prediction(history, "2023-01-01"))

    def test_candidate_models_do_not_require_future_target_value(self) -> None:
        history = [
            {"inspection_date": "2020-01-01", "minimum_wall_thickness_mm": 3.0},
            {"inspection_date": "2021-01-01", "minimum_wall_thickness_mm": 2.9},
            {"inspection_date": "2022-01-01", "minimum_wall_thickness_mm": 2.8},
        ]
        result = model_predictions(history, "2025-01-01")
        self.assertTrue({"linear", "huber", "theil_sen", "last_observation"}.issubset(result))
        self.assertAlmostEqual(result["linear"], 2.5, places=2)

    def test_validation_sample_records_known_forecast_horizon(self) -> None:
        # The interval scaling input is derived exclusively from dates, not the
        # held-out target measurement.
        from pathlib import Path
        database = Path(__file__).resolve().parent / "data" / "heat_exchanger_db3.db"
        samples = validation_samples(database, 2023)
        self.assertTrue(samples)
        self.assertTrue(all(row["forecast_horizon_years"] > 0 for row in samples))

    def test_directional_shift_blocks_non_transportable_calibration(self) -> None:
        def sample(tube_id: int, target_id: int, source_id: int, actual: float, predicted: float) -> dict:
            return {
                "unit_code": "VCM1",
                "heat_exchanger_id": 1,
                "bundle_id": 1,
                "bundle_lifecycle_no": 1,
                "tube_lifecycle_no": 1,
                "tube_id": tube_id,
                "target_result_id": target_id,
                "source_result_ids": [source_id],
                "actual_thickness_mm": actual,
                "candidate_predictions_mm": {"last_observation": predicted},
            }

        calibration = [sample(i, 100 + i, 10 + i, 1.9 if i < 9 else 2.1, 2.0) for i in range(10)]
        final = [sample(i, 200 + i, 100 + i, 2.0, 1.9 if i < 9 else 2.1) for i in range(10)]
        result = directional_shift_diagnostics(calibration, final)
        self.assertFalse(result["stable"])
        self.assertAlmostEqual(result["calibration_2023"]["measured_increase_fraction"], 0.1)
        self.assertAlmostEqual(result["final_2025"]["measured_increase_fraction"], 0.9)


if __name__ == "__main__":
    unittest.main()
