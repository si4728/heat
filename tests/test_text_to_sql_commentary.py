import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2.application import text_to_sql_commentary as commentary
from iris2.llm_integration.text_to_sql import QueryRejected


class CommentaryTests(unittest.TestCase):
    def row(self, identifier, **values):
        row=dict(heat_exchanger_id=identifier,exchanger_code=f'E-{identifier}',unit_code='VCM1',
            team_code='VCM',remaining_life_years=20,remaining_display='20.0년',
            recommendation_date='2030-01-01',calculation_date='2026-11-23',
            analysis_status='CALCULATED',sample_count=20,maximum_loss=15)
        row.update(values)
        return row

    def selection(self, facts):
        return {section:[s['id'] for s in facts['statements'] if s['section']==section]
                for section in ('overview','priorities','limitations')}

    def test_aggregate_and_priority_include_rows_beyond_display_limit(self):
        rows=[self.row(i) for i in range(1,13)]
        rows[-1].update(remaining_life_years=0,remaining_display='0.0년')
        facts=commentary.evidence(dict(rows=rows[:2],matched_count=12),all_rows=rows)
        self.assertTrue(facts['coverage_complete'])
        self.assertEqual(facts['analyzed_count'],12)
        self.assertEqual(facts['total_rows'],2)
        self.assertEqual(facts['stats']['reached'],1)
        self.assertEqual(facts['examples'][0]['heat_exchanger_id'],12)
        self.assertEqual(len(facts['examples']),8)

    def test_reached_overdue_near_due_then_short_life_priority(self):
        rows=[self.row(1,remaining_life_years=3),self.row(2,recommendation_date='2027-03-01'),
              self.row(3,recommendation_date='2026-01-01'),self.row(4,remaining_life_years=0)]
        facts=commentary.evidence(dict(rows=rows))
        self.assertEqual([r['heat_exchanger_id'] for r in facts['examples']],[4,3,2,1])
        self.assertEqual(facts['stats']['overdue'],1)

    def test_unknown_not_reached_and_zero_are_separate(self):
        rows=[self.row(1,remaining_life_years=None,analysis_status='INSUFFICIENT_DATA',recommendation_date=None),
              self.row(2,remaining_life_years=None,analysis_status='LIMIT_NOT_REACHED'),
              self.row(3,remaining_life_years=0)]
        facts=commentary.evidence(dict(rows=rows))
        self.assertEqual(facts['stats']['missing_life'],1)
        self.assertEqual(facts['stats']['not_reached'],1)
        self.assertEqual(facts['stats']['reached'],1)
        self.assertEqual(facts['stats']['missing_recommendation'],1)

    def test_partial_coverage_and_small_sample_require_limitations(self):
        facts=commentary.evidence(dict(rows=[self.row(1,sample_count=5)],matched_count=20))
        self.assertFalse(facts['coverage_complete'])
        ids={s['id'] for s in facts['statements']}
        self.assertTrue({'L_PARTIAL','L_SAMPLE'}<=ids)
        selected=self.selection(facts)
        selected['limitations'].remove('L_PARTIAL')
        with self.assertRaises(QueryRejected):commentary.validate(selected,facts)

    def test_associations_are_copied_from_server_not_generated_by_model(self):
        facts=commentary.evidence(dict(rows=[self.row(1,recommendation_date='2027-01-01'),
                                           self.row(2,recommendation_date='2030-01-01')]))
        sections=commentary.validate(self.selection(facts),facts)
        first=sections[1]['items'][0]
        self.assertEqual(first['equipment_code'],'E-1')
        self.assertIn('2027-01-01',first['text'])
        self.assertNotIn('2030-01-01',first['text'])

    def test_unknown_ids_wrong_sections_duplicates_and_missing_top_priority_fail(self):
        facts=commentary.evidence(dict(rows=[self.row(1),self.row(2)]))
        for priorities in [['P02'],['P01','P01'],['G_SCOPE'],['E-999'],['P01','2030-01-01']]:
            selected=self.selection(facts);selected['priorities']=priorities
            with self.subTest(priorities=priorities),self.assertRaises(QueryRejected):commentary.validate(selected,facts)


if __name__=='__main__':unittest.main()
