from datetime import date
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2.application.equipment_summary import build_equipment_summary
from iris2.application.text_to_sql_scope import mentioned_units
from iris2.domain.sample_wall_loss import estimate_sample_wall_loss


class CustomerLifeSummaryTests(unittest.TestCase):
    def life(self,**changes):
        return dict(status='INSUFFICIENT_DATA',remaining_life_years=None,total_tube_count=100,
            tube_projections=[],analysis_tube_rows=[],registered_inspection_count=1,**changes)

    def test_uninspected_and_unknown_reasons_and_old_not_reached_are_distinct(self):
        life=self.life();life['registered_inspection_count']=0
        summary=build_equipment_summary(life,date(2026,11,24))
        self.assertEqual(summary['band'],'uninspected')
        life=self.life(sample_wall_loss_estimate=dict(status='SAMPLE_INSUFFICIENT',sample_count=5,measured_max_wall_loss_percent=0))
        summary=build_equipment_summary(life,date(2026,11,24))
        self.assertEqual(summary['band'],'unknown')
        self.assertIn('표본',summary['uncalculable_reason']);self.assertIn('감육 미검출',summary['uncalculable_reason'])
        life['status']='LIMIT_NOT_REACHED'
        self.assertEqual(build_equipment_summary(life,date(2026,11,24))['remaining_display'],'산정 불가')

    def test_actual_count_over_limit_wins_over_sample_and_far_year_is_hidden(self):
        life=self.life(allowable_plugging_count=20,actual_plugged_count=21,
            sample_wall_loss_estimate=dict(status='ESTIMATED',twenty_percent_threshold=dict(status='FORECAST',date='2321-01-01')))
        summary=build_equipment_summary(life,date(2026,11,24))
        self.assertEqual(summary['remaining_life_years'],0)
        life=self.life(life_reached_year=2321);life.update(status='CALCULATED',remaining_life_years=295)
        self.assertEqual(build_equipment_summary(life,date(2026,11,24))['target_display'],'30년 이상')

    def test_actual_operations_reduce_remaining_population_and_allowance(self):
        result=estimate_sample_wall_loss(range(10,25),total_tube_count=100,completed_count=10,
            installation_date='2000-01-01',measurement_date='2025-01-01')
        self.assertEqual(result['remaining_population'],90)
        self.assertEqual(result['additional_tubes_to_exceed_limit'],11)
        self.assertAlmostEqual(result['upper_threshold_percentile'],1-11/90)

    def test_pe_question_scope_does_not_match_other_units(self):
        self.assertEqual(mentioned_units('PE 생산팀 잔여수명 목록'),{'PE'})
        self.assertEqual(mentioned_units('PE와 VCM2 목록'),{'PE','VCM2'})
        with self.assertRaises(ValueError):mentioned_units('VCM3 목록')


if __name__=='__main__':unittest.main()
