import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from iris2.life_prediction import calculate_latest_installation_projection


class LatestInstallationPredictionTest(unittest.TestCase):
    def calculate(self, **overrides):
        inputs = dict(installation_date="2010-01-01", measurement_date="2020-01-01",
                      nominal_thickness_mm=2, wall_loss_percent=20,
                      plugging_wall_loss_percent=40)
        return calculate_latest_installation_projection(**(inputs | overrides))

    def test_prediction_is_anchored_to_inspection_not_today(self):
        r = self.calculate()
        self.assertEqual(r["projection_origin_date"], "2020-01-01")
        self.assertAlmostEqual(r["years_from_measurement"], r["elapsed_service_years"])
        self.assertEqual(r["plugging_date"], "2029-12-31")

    def test_zero_loss_is_not_infinite_or_immediate_prediction(self):
        self.assertEqual(self.calculate(wall_loss_percent=0)["status"], "NO_POSITIVE_WALL_LOSS")
        self.assertNotIn("plugging_date", self.calculate(wall_loss_percent=0))

    def test_limit_already_reached_uses_measurement_date(self):
        r = self.calculate(wall_loss_percent=45)
        self.assertEqual(r["plugging_date"], "2020-01-01")
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

    def test_invalid_numeric_input_is_rejected(self):
        for v in (-1, 101, float("nan")):
            self.assertNotIn("plugging_date", self.calculate(wall_loss_percent=v))


if __name__ == "__main__":
    unittest.main()
