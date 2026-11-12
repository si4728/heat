import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from iris2.life_prediction import calculate_latest_installation_projection


class LatestInstallationPredictionTest(unittest.TestCase):
    def calculate(self, **overrides):
        inputs = dict(installation_date="2010-01-01", measurement_date="2020-01-01",
                      nominal_thickness_mm=2, wall_loss_percent=20,
                      plugging_wall_loss_percent=40, as_of_date="2026-01-01")
        return calculate_latest_installation_projection(**(inputs | overrides))

    def test_prediction_is_anchored_to_current_basis_date(self):
        r = self.calculate()
        self.assertEqual(r["projection_origin_date"], "2026-01-01")
        self.assertEqual(r["measurement_date"], "2020-01-01")
        self.assertAlmostEqual(r["years_from_measurement"], r["elapsed_service_years"])
        self.assertEqual(r["plugging_date"], "2036-01-01")

    def test_zero_loss_is_not_infinite_or_immediate_prediction(self):
        self.assertEqual(self.calculate(wall_loss_percent=0)["status"], "NO_POSITIVE_WALL_LOSS")
        self.assertNotIn("plugging_date", self.calculate(wall_loss_percent=0))

    def test_changed_basis_moves_projection_but_not_corrosion_rate(self):
        first = self.calculate(as_of_date='2026-01-01')
        second = self.calculate(as_of_date='2027-01-01')
        self.assertEqual(first['corrosion_rate_mm_per_year'], second['corrosion_rate_mm_per_year'])
        self.assertEqual(first['years_from_measurement'], second['years_from_measurement'])
        self.assertEqual(second['projection_origin_date'], '2027-01-01')
        self.assertNotEqual(first['plugging_date'], second['plugging_date'])

    def test_extremely_slow_projection_has_explicit_unavailable_status(self):
        result = self.calculate(rate_multiplier=1e-12)
        self.assertEqual(result["status"], "PROJECTION_OUT_OF_DATE_RANGE")
        self.assertNotIn("plugging_date", result)

    def test_underflowed_rate_is_unavailable_instead_of_crashing(self):
        result = self.calculate(rate_multiplier=5e-324)
        self.assertEqual(result['status'], 'NO_POSITIVE_CORROSION_RATE')
        self.assertNotIn('plugging_date', result)

    def test_overflowed_derived_rate_does_not_escape_as_nonfinite_json(self):
        result = self.calculate(nominal_thickness_mm=1e308, rate_multiplier=1e308)
        self.assertEqual(result['status'], 'INVALID_DERIVED_CORROSION_RATE')

    def test_overflowed_percent_rate_is_not_serialized(self):
        result = self.calculate(installation_date='2019-12-31', nominal_thickness_mm=1e-300,
                                wall_loss_percent=90, rate_multiplier=1e308)
        self.assertEqual(result['status'], 'INVALID_DERIVED_CORROSION_RATE')


    def test_limit_already_reached_uses_basis_date(self):
        r = self.calculate(wall_loss_percent=45)
        self.assertEqual(r["plugging_date"], "2026-01-01")
        self.assertEqual(r["years_from_measurement"], 0)

    def test_invalid_installation_does_not_generate_rate(self):
        for v in (None, "2020-01-01", "2021-01-01"):
            self.assertNotIn("plugging_date", self.calculate(installation_date=v))

    def test_year_only_is_explicit_estimate(self):
        r = self.calculate(installation_date="2010-12-31", installation_precision="YEAR")
        self.assertEqual(r["installation_date_used"], "2010-07-01")
        self.assertEqual(r["status"], "ESTIMATED_INSTALLATION_YEAR")

    def test_multiplier_halves_remaining_time(self):
        self.assertAlmostEqual(self.calculate(rate_multiplier=2)["years_from_measurement"],
                               self.calculate()["years_from_measurement"] / 2)

    def test_fractional_multiplier_preserves_whole_day_projection(self):
        result = calculate_latest_installation_projection(
            installation_date='1990-08-22', measurement_date='2025-11-04',
            nominal_thickness_mm=1,wall_loss_percent=8,plugging_wall_loss_percent=40,
            rate_multiplier=1.5,as_of_date='2026-10-28')
        self.assertEqual(result['plugging_date'], '2120-09-13')

    def test_invalid_numeric_input_is_rejected(self):
        for v in (-1, 101, float("nan")):
            self.assertNotIn("plugging_date", self.calculate(wall_loss_percent=v))


if __name__ == "__main__":
    unittest.main()
