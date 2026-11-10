from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iris2.application.api510_service import _float
from iris2.life_prediction import calculate_api510_inspection_interval, calculate_tube_plugging_year, summarize_remaining_life
from iris2.pressure_vessel_calculations import calculate_asme_viii_internal_pressure


class CalculationBoundaryTest(unittest.TestCase):
    def test_subday_rounding_does_not_cross_midnight(self):
        # Less than a day must remain on the basis date even when timedelta's
        # fractional-microsecond rounding would otherwise produce the next day.
        result = calculate_tube_plugging_year(
            measurement_date='2026-01-01', nominal_thickness_mm=2,
            current_wall_loss_mm=0, plugging_wall_loss_percent=40,
            corrosion_rate_mm_per_year=0.8 * 365.2425 / (1 - 1e-12))
        self.assertEqual(result['plugging_date'], '2026-01-01')

    def test_invalid_speed_multipliers_are_rejected(self):
        for multiplier in (0,-1,float('inf'),float('nan')):
            with self.subTest(multiplier=multiplier), self.assertRaises(ValueError):
                calculate_tube_plugging_year(measurement_date='2026-01-01',
                    nominal_thickness_mm=2,current_wall_loss_mm=0.1,
                    corrosion_rate_mm_per_year=0.1,rate_multiplier=multiplier)

    def test_normal_and_critical_limits_and_strict_exceedance(self):
        rows = [2026] * 10 + [2030]
        critical = summarize_remaining_life(plugging_years=rows, total_tube_count=100,
                                           is_critical=True, current_year=2026)
        normal = summarize_remaining_life(plugging_years=rows, total_tube_count=100,
                                         is_critical=False, current_year=2026)
        self.assertEqual(critical['limit_percent'], 10)
        self.assertEqual(critical['life_reached_year'], 2030)
        self.assertEqual(critical['remaining_life_years'], 4)
        self.assertEqual(normal['limit_percent'], 20)
        self.assertIsNone(normal['life_reached_year'])

    def test_already_exceeded_limit_does_not_return_negative_life(self):
        result = summarize_remaining_life(plugging_years=[2020] * 11,
            total_tube_count=100, is_critical=True, current_year=2026)
        self.assertEqual(result['remaining_life_years'], 0)

    def test_unit_bearing_text_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "단위와 분리"):
            _float("1.2 MPa")

    def test_nonfinite_service_values_are_rejected(self):
        for value in ("NaN", "Infinity", float("-inf"), True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _float(value)

    def test_plugging_limit_exactly_reached_is_immediate(self):
        result = calculate_tube_plugging_year(
            measurement_date="2026-01-01", nominal_thickness_mm=2,
            current_wall_loss_mm=1, corrosion_rate_mm_per_year=0.1,
            plugging_wall_loss_percent=50,
        )
        self.assertEqual(result["years_from_measurement"], 0)
        self.assertEqual(result["plugging_date"], "2026-01-01")

    def test_plugging_nonfinite_inputs_are_rejected(self):
        cases = [
            {"nominal_thickness_mm": float("inf"), "current_wall_loss_mm": 0, "corrosion_rate_mm_per_year": 0.1},
            {"nominal_thickness_mm": 2, "current_wall_loss_mm": float("nan"), "corrosion_rate_mm_per_year": 0.1},
            {"nominal_thickness_mm": 2, "current_wall_loss_mm": 0, "corrosion_rate_mm_per_year": float("inf")},
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                calculate_tube_plugging_year(measurement_date="2026-01-01", **case)

    def test_zero_corrosion_rate_has_no_projection(self):
        self.assertIsNone(calculate_tube_plugging_year(
            measurement_date="2026-01-01", nominal_thickness_mm=2,
            current_wall_loss_mm=0.1, corrosion_rate_mm_per_year=0,
        ))

    def test_tiny_positive_corrosion_rate_reports_date_range(self):
        for rate in (1e-12, 1e-300, 1e-320):
            with self.subTest(rate=rate), self.assertRaisesRegex(ValueError, "날짜 범위"):
                calculate_tube_plugging_year(
                    measurement_date="2026-01-01", nominal_thickness_mm=2,
                    current_wall_loss_mm=0.1, corrosion_rate_mm_per_year=rate,
                )

    def test_decimal_year_matches_projected_calendar_date(self):
        result = calculate_tube_plugging_year(
            measurement_date="2026-01-01", nominal_thickness_mm=2,
            current_wall_loss_mm=0.1, corrosion_rate_mm_per_year=0.1,
            plugging_wall_loss_percent=40,
        )
        self.assertEqual(result["plugging_date"], "2032-12-31")
        self.assertEqual(result["years_from_measurement"], 7)
        self.assertEqual(int(result["exact_year"]), result["plugging_year"])
        self.assertAlmostEqual(result["exact_year"], 2032 + 365 / 366)

    def test_projection_supports_last_calendar_year(self):
        for origin in ("9999-01-01", "9999-12-31"):
            with self.subTest(origin=origin):
                result = calculate_tube_plugging_year(
                    measurement_date=origin, nominal_thickness_mm=2,
                    current_wall_loss_mm=1, corrosion_rate_mm_per_year=0.1,
                    plugging_wall_loss_percent=40,
                )
                self.assertEqual(result["plugging_date"], origin)
                self.assertEqual(int(result["exact_year"]), 9999)

    def test_future_projection_near_date_max_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "날짜 범위"):
            calculate_tube_plugging_year(
                measurement_date="9999-12-31", nominal_thickness_mm=2,
                current_wall_loss_mm=0.1, corrosion_rate_mm_per_year=0.1,
            )

    def test_api510_equal_required_is_action_required(self):
        result = calculate_api510_inspection_interval(
            actual_thickness_mm=5, required_thickness_mm=5,
            corrosion_rate_mm_per_year=0.1, last_inspection_date="2026-01-01",
            as_of_date=date(2026, 1, 1),
        )
        self.assertEqual(result["status"], "ACTION_REQUIRED")
        self.assertEqual(result["inspection_interval_years"], 0)

    def test_api510_interval_caps_by_inspection_type(self):
        internal = calculate_api510_inspection_interval(
            actual_thickness_mm=20, required_thickness_mm=1,
            corrosion_rate_mm_per_year=0.01, last_inspection_date="2026-01-01",
            inspection_type="INTERNAL_ON_STREAM", as_of_date="2026-01-01",
        )
        external = calculate_api510_inspection_interval(
            actual_thickness_mm=20, required_thickness_mm=1,
            corrosion_rate_mm_per_year=0.01, last_inspection_date="2026-01-01",
            inspection_type="EXTERNAL", as_of_date="2026-01-01",
        )
        self.assertLessEqual(internal["inspection_interval_years"], internal["maximum_interval_years"])
        self.assertLessEqual(external["inspection_interval_years"], external["maximum_interval_years"])

    def test_asme_all_supported_geometries_at_valid_boundary(self):
        for component_type in (
            "CYLINDRICAL_SHELL", "SPHERICAL_SHELL",
            "ELLIPSOIDAL_HEAD_2_1", "HEMISPHERICAL_HEAD",
        ):
            with self.subTest(component_type=component_type):
                result = calculate_asme_viii_internal_pressure(
                    component_type=component_type, inside_diameter_mm=1000,
                    design_pressure_mpa=1, allowable_stress_mpa=100,
                    joint_efficiency=1, actual_thickness_mm=10,
                    supplemental_thickness_mm=0,
                )
                self.assertGreater(result["required_thickness_mm"], 0)

    def test_asme_denominator_and_supplemental_boundaries(self):
        with self.assertRaises(ValueError):
            calculate_asme_viii_internal_pressure(
                component_type="CYLINDRICAL_SHELL", inside_diameter_mm=1000,
                design_pressure_mpa=100, allowable_stress_mpa=60,
                joint_efficiency=1, actual_thickness_mm=10,
            )
        with self.assertRaises(ValueError):
            calculate_asme_viii_internal_pressure(
                component_type="CYLINDRICAL_SHELL", inside_diameter_mm=1000,
                design_pressure_mpa=1, allowable_stress_mpa=100,
                joint_efficiency=1, actual_thickness_mm=10,
                supplemental_thickness_mm=10,
            )

    def test_asme_rejects_negative_static_head_and_nonpositive_design_pressure(self):
        for design_pressure, static_head in ((1, -0.1), (0, 1), (-1, 2)):
            with self.subTest(design_pressure=design_pressure, static_head=static_head), self.assertRaises(ValueError):
                calculate_asme_viii_internal_pressure(
                    component_type="CYLINDRICAL_SHELL", inside_diameter_mm=1000,
                    design_pressure_mpa=design_pressure, static_head_mpa=static_head,
                    allowable_stress_mpa=100, joint_efficiency=1,
                    actual_thickness_mm=10,
                )


if __name__ == "__main__":
    unittest.main()
