import sys
import unittest
from pathlib import Path
from datetime import date

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2.domain.short_term_corrosion import short_term_corrosion_rate


class ShortTermCorrosionTests(unittest.TestCase):
    def calculate(self,current=2.01,previous=2.06,**kwargs):
        return short_term_corrosion_rate(dict(date='2025-10-29',thickness_mm=current),
            [dict(date='2023-11-17',thickness_mm=previous)],**kwargs)

    def test_two_actual_measurements_and_day_based_years(self):
        r=self.calculate()
        years=(date(2025,10,29)-date(2023,11,17)).days/365.2425
        self.assertAlmostEqual(r['short_term_rate_mm_per_year'],.05/years)
        self.assertEqual(r['short_term_status'],'POSITIVE')
        self.assertEqual(r['short_term_previous_date'],'2023-11-17')

    def test_non_positive_result_is_preserved_not_changed_to_zero(self):
        r=self.calculate(current=2.30)
        self.assertLess(r['short_term_rate_mm_per_year'],0)
        self.assertEqual(r['short_term_status'],'NON_POSITIVE')
        self.assertEqual(self.calculate(current=2.06)['short_term_rate_mm_per_year'],0)

    def test_missing_invalid_and_same_date_do_not_invent_rate(self):
        for value in [None,float('nan'),float('inf'),-1,True]:
            self.assertIsNone(self.calculate(current=value)['short_term_rate_mm_per_year'])
        r=short_term_corrosion_rate(dict(date='2025-10-29',thickness_mm=2),
            [dict(date='2025-10-29',thickness_mm=2.2)])
        self.assertIsNone(r['short_term_rate_mm_per_year'])

    def test_replacement_cutoff_excludes_old_measurements(self):
        self.assertIsNone(self.calculate(installed_at='2024-01-01')['short_term_rate_mm_per_year'])
        self.assertIsNone(self.calculate(installed_at='2026-01-01')['short_term_rate_mm_per_year'])

    def test_previous_date_duplicates_use_minimum_and_record_count(self):
        r=short_term_corrosion_rate(dict(date='2025-10-29',thickness_mm=2.01),
            [dict(date='2023-11-17',thickness_mm=2.06),dict(date='2023-11-17',thickness_mm=2.1),
             dict(date='2020-01-01',thickness_mm=3)])
        self.assertEqual(r['short_term_previous_thickness_mm'],2.06)
        self.assertEqual(r['short_term_previous_duplicate_count'],2)

    def test_zero_thickness_is_a_measurement_not_missing(self):
        self.assertGreater(self.calculate(current=0)['short_term_rate_mm_per_year'],0)

    def test_overflow_does_not_escape_as_nonfinite_rate(self):
        r=short_term_corrosion_rate(dict(date='2025-01-02',thickness_mm=0),
            [dict(date='2025-01-01',thickness_mm=1e308)])
        self.assertIsNone(r['short_term_rate_mm_per_year'])

    def test_analysis_content_is_visible_without_tabs_or_dialogs(self):
        source=(Path(__file__).resolve().parents[1]/'templates/precision_analysis.html').read_text(encoding='utf-8')
        for tag in ['<dialog','<details','role="tab','showModal']:
            self.assertNotIn(tag,source)
        self.assertIn('thickness-trend',source)
        self.assertIn('precision_measurement_table.html',source)
