import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2.life_prediction import calculate_api510_inspection_interval
from iris2.pressure_vessel_calculations import calculate_asme_viii_internal_pressure, SUPPORTED_COMPONENT_TYPES


class Api510NumericSafetyTests(unittest.TestCase):
    def test_overflowed_remaining_life_is_not_a_storable_result(self):
        with self.assertRaises(ValueError):
            calculate_api510_inspection_interval(actual_thickness_mm=10,
                required_thickness_mm=1,corrosion_rate_mm_per_year=1e-320,
                last_inspection_date='2025-01-01')

    def test_unrepresentable_next_date_has_validation_error(self):
        with self.assertRaises(ValueError):
            calculate_api510_inspection_interval(actual_thickness_mm=10,
                required_thickness_mm=1,corrosion_rate_mm_per_year=.1,
                last_inspection_date='9999-12-31')

    def test_asme_finite_inputs_cannot_produce_nan_or_infinity(self):
        for kind in SUPPORTED_COMPONENT_TYPES:
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                calculate_asme_viii_internal_pressure(component_type=kind,
                    inside_diameter_mm=1000,design_pressure_mpa=1,
                    allowable_stress_mpa=1e308,joint_efficiency=1,actual_thickness_mm=10)

    def test_pressure_thickness_and_mawp_are_inverse_at_required_thickness(self):
        for kind in SUPPORTED_COMPONENT_TYPES:
            for pressure in (.1,1,3):
                with self.subTest(kind=kind,pressure=pressure):
                    inputs=dict(component_type=kind,inside_diameter_mm=1000,
                        design_pressure_mpa=pressure,static_head_mpa=.05,
                        allowable_stress_mpa=120,joint_efficiency=.85,supplemental_thickness_mm=.5)
                    original=calculate_asme_viii_internal_pressure(**inputs,actual_thickness_mm=20)
                    boundary=calculate_asme_viii_internal_pressure(**inputs,actual_thickness_mm=original['required_thickness_mm'])
                    self.assertAlmostEqual(boundary['mawp_mpa'],pressure+.05,places=10)
                    self.assertTrue(math.isfinite(boundary['required_thickness_mm']))

    def test_underflowed_geometry_does_not_return_zero_or_divide_by_zero(self):
        for kind in SUPPORTED_COMPONENT_TYPES:
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                calculate_asme_viii_internal_pressure(component_type=kind,
                    inside_diameter_mm=5e-324,design_pressure_mpa=1,
                    allowable_stress_mpa=100,joint_efficiency=1,actual_thickness_mm=5e-324)


if __name__=='__main__':unittest.main()
