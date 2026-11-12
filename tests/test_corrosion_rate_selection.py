import math
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace as Obj
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2.domain.corrosion_rate_selection import select_corrosion_rate
from iris2.life_prediction import calculate_history_projection, summarize_remaining_life
from iris2 import services


class CorrosionSelectionTests(unittest.TestCase):
    def select(self, values, long=.02, **kwargs):
        rows = [dict(date=f'{2020+i}-01-01', thickness_mm=value) for i, value in enumerate(values)]
        return select_corrosion_rate(rows[-1], rows, long_term_rate=long, **kwargs)

    def test_three_inspections_use_regression_even_when_long_rate_is_larger(self):
        result = self.select([2.5, 2.4, 2.3], long=.3)
        self.assertEqual(result['selection_label'], '추세(3회)')
        self.assertAlmostEqual(result['selected_rate_mm_per_year'], .1, places=3)
        self.assertEqual(result['measurement_count'], 3)

    def test_two_inspections_use_larger_positive_rate_and_one_uses_long(self):
        for long, expected in [(.05, '단기'), (.3, '장기'), (None, '단기'), (0, '단기')]:
            with self.subTest(long=long):
                self.assertEqual(self.select([2.5, 2.4], long)['selection_label'], expected)
        self.assertEqual(self.select([2.4])['selection_label'], '장기')

    def test_nonpositive_short_uses_long_without_clamping_the_measured_rate(self):
        for values in ([2.4, 2.5], [2.4, 2.4]):
            result = self.select(values)
            self.assertEqual(result['selection_label'], '단기 0 이하 → 장기')
            self.assertEqual(result['selected_rate_mm_per_year'], .02)
            self.assertLessEqual(result['short_term_rate_mm_per_year'], 0)

    def test_nonpositive_regression_uses_long_even_when_last_pair_is_positive(self):
        for values in ([2.0, 2.5, 2.4], [2.4, 2.4, 2.4]):
            result = self.select(values)
            self.assertEqual(result['selection_label'], '추세 0 이하 → 장기')
            self.assertEqual(result['selected_rate_mm_per_year'], .02)

    def test_regression_averages_a_positive_trend_despite_last_measurement_noise(self):
        result = self.select([3, 2, 2.1])
        self.assertLess(result['short_term_rate_mm_per_year'], 0)
        self.assertEqual(result['selection_label'], '추세(3회)')
        self.assertGreater(result['selected_rate_mm_per_year'], 0)

    def test_missing_or_nonpositive_long_cannot_be_used_as_fallback(self):
        for long in (None, 0, -1, float('nan'), float('inf'), True):
            result = self.select([2, 2.1, 2.2], long)
            self.assertIsNone(result['selected_rate_mm_per_year'])
            self.assertEqual(result['selection_label'], '산정 불가')

    def test_duplicates_invalid_future_and_previous_installation_do_not_inflate_count(self):
        current = dict(date='2025-01-01', thickness_mm=2)
        history = [dict(date='2023-01-01', thickness_mm=2.1),
                   dict(date='2023-01-01', thickness_mm=2.2),
                   dict(date='2025-01-01', thickness_mm=2),
                   dict(date='2026-01-01', thickness_mm=1),
                   dict(date='2020-01-01', thickness_mm=3)]
        history += [dict(date='2024-01-01', thickness_mm=v) for v in (None, -1, True, float('inf'))]
        result = select_corrosion_rate(current, history, long_term_rate=.02, installed_at='2022-01-01')
        self.assertEqual(result['measurement_count'], 2)
        self.assertIsNone(result['regression_rate_mm_per_year'])
        self.assertEqual(result['short_term_previous_thickness_mm'], 2.1)

    def test_regression_overflow_never_returns_nonfinite_rate(self):
        result = self.select([1e308, 1e308, 0])
        self.assertTrue(all(v is None or math.isfinite(v) for v in
            [result['selected_rate_mm_per_year'], result['regression_rate_mm_per_year']]))


class SelectedProjectionTests(unittest.TestCase):
    def calculate(self, **kwargs):
        return calculate_history_projection(**(dict(installation_date='1971-12-01',
            measurement_date='2025-10-29', nominal_thickness_mm=2.77,
            wall_loss_percent=27.4, plugging_wall_loss_percent=40,
            current_thickness_mm=2.01, as_of_date='2026-11-12',
            history=[dict(date='2023-11-17', thickness_mm=2.06)]) | kwargs))

    def test_e111_two_measurements_choose_short_and_projection_uses_it(self):
        result = self.calculate()
        self.assertEqual(result['corrosion_rate_selection_label'], '단기')
        self.assertAlmostEqual(result['corrosion_rate_mm_per_year'], .02564905196629227)
        self.assertLess(result['long_term_corrosion_rate_mm_per_year'], result['corrosion_rate_mm_per_year'])
        expected = 2.77 * (.4 - .274) / result['corrosion_rate_mm_per_year']
        self.assertAlmostEqual(result['years_from_measurement'], expected)
        self.assertEqual(result['projection_origin_date'], '2026-11-12')

    def test_multiplier_changes_selected_rate_and_date_without_changing_basis(self):
        baseline, twice = self.calculate(), self.calculate(rate_multiplier=2)
        self.assertEqual(twice['corrosion_rate_mm_per_year'], baseline['corrosion_rate_mm_per_year'] * 2)
        for field in ['short_term_corrosion_rate_mm_per_year', 'long_term_corrosion_rate_mm_per_year',
                      'selected_base_corrosion_rate_mm_per_year', 'corrosion_rate_selection_label']:
            self.assertEqual(baseline[field], twice[field])
        self.assertEqual(twice['years_from_measurement'], baseline['years_from_measurement'] / 2)

    def test_history_can_predict_without_installation_but_single_measurement_cannot(self):
        self.assertIn('plugging_date', self.calculate(installation_date=None))
        self.assertNotIn('plugging_date', self.calculate(installation_date=None, history=[]))

    def test_threshold_already_reached_and_zero_loss_with_positive_trend(self):
        self.assertEqual(self.calculate(wall_loss_percent=45)['plugging_date'], '2026-11-12')
        self.assertIn('plugging_date', self.calculate(wall_loss_percent=0))

    def test_invalid_values_or_date_overflow_do_not_produce_forecasts(self):
        for kwargs in [dict(wall_loss_percent=float('nan')), dict(rate_multiplier=float('inf')),
                       dict(rate_multiplier=None), dict(rate_multiplier='bad'),
                       dict(nominal_thickness_mm=0), dict(as_of_date='9999-12-31')]:
            with self.subTest(kwargs=kwargs):
                self.assertNotIn('plugging_date', self.calculate(**kwargs))


class PopulationAndLimitTests(unittest.TestCase):
    def projection(self, spec):
        session = Mock()
        session.scalars.return_value.all.return_value = []
        session.scalar.return_value = spec
        session.get.return_value = Obj(unit_code='VCM1')
        equipment = Obj(unit_id=1, install_date=date(2000, 1, 1), is_critical=True)
        bundle = Obj(bundle_id=1, retired_at=None, expected_tube_count=9999)
        result = services._remaining_life_projection(session, 1, equipment, [bundle], None,
            as_of_date=date(2026, 11, 12), forecast_end_year=2050)
        self.assertIn('is_current IS true', str(session.scalar.call_args.args[0]))
        return result

    def test_missing_approved_spec_does_not_fall_back_to_bundle_or_zero_allowance(self):
        result = self.projection(None)
        self.assertIsNone(result['total_tube_count'])
        self.assertIsNone(result['allowable_plugging_count'])
        self.assertEqual(result['status'], 'INSUFFICIENT_DATA')
        self.assertIsNone(result['life_reached_year'])

    def test_current_spec_defines_denominator_and_both_importance_defaults_are_twenty(self):
        result = self.projection(Obj(tube_count=52, shell_fluid=None, tube_fluid=None, tube_material=None))
        self.assertEqual(result['total_tube_count'], 52)
        self.assertEqual(result['allowable_plugging_count'], 10)
        self.assertEqual(result['limit_percent'], 20)
        for critical in (True, False):
            result = summarize_remaining_life(plugging_years=[2030]*20+[2031],
                total_tube_count=100, is_critical=critical, current_year=2026)
            self.assertEqual(result['life_reached_year'], 2031)

    def test_future_importance_settings_and_explicit_simulation_remain_supported(self):
        with patch('iris2.life_prediction.REMAINING_LIFE_CRITICAL_ALLOWABLE_PLUGGING_PERCENT', 12):
            result = summarize_remaining_life(plugging_years=[], total_tube_count=100,
                is_critical=True, current_year=2026)
            self.assertEqual(result['allowable_plugging_count'], 12)
            result = summarize_remaining_life(plugging_years=[], total_tube_count=100,
                is_critical=True, current_year=2026, allowable_plugging_percent=15)
            self.assertEqual(result['allowable_plugging_count'], 15)


if __name__ == '__main__':
    unittest.main()
