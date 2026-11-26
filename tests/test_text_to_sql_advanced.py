from datetime import date
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2.application.text_to_sql_equipment_intents import parse
from iris2.application.text_to_sql_equipment_history import cohorts,latest_pair,cumulative_completed
from iris2.application.text_to_sql_advanced import assemble,aggregate_evidence
from iris2.application.text_to_sql_commentary import validate
from iris2.application.equipment_summary import build_equipment_summary
from iris2.llm_integration.text_to_sql import QueryRejected


class AdvancedEquipmentTests(unittest.TestCase):
    def base(self,identifier=1,team='PE'):
        row=dict(heat_exchanger_id=identifier,team_code=team,unit_code='PE' if team=='PE' else 'VCM1',
            exchanger_code=f'E-{identifier}',equipment_name='test',latest_inspection_date='2025-11-01',
            sample_count=5,maximum_loss=35,remaining_life_years=4,remaining_display='4.0년')
        detail=dict(spec=SimpleNamespace(tube_material='Cu - Ni'),remaining_life=dict(
            analysis_tube_rows=[dict(corrosion_rate_mm_per_year=value) for value in (None,0,-.1,.05,.1,.2)],
            sample_wall_loss_estimate=dict(inspection_id=9,sample_count=5,minimum_sample_count=10),
            equipment_overview=dict(band='unknown',target_date='2030-03-01'),total_tube_count=100))
        return row,detail

    def history(self):
        data=dict(masters={1:dict(equipment_install_date='2010-01-01',iris_applicability='REQUIRED')},
            inspections=[],results=[],reports=[],operations=[],tubes=[])
        for iid,when,loss in [(1,'2020-01-01',25.1),(2,'2025-01-01',30.1)]:
            data['inspections'].append(dict(heat_exchanger_id=1,iris_inspection_id=iid,inspection_date=when,report_date=None,
                bundle_id=4,original_equipment_id='E-1',superseded_by_inspection_id=None,report_number=f'IRIS-{iid}'))
            data['results'].append(dict(iris_inspection_id=iid,tube_id=10,tube_bundle_id=4,tube_installed_at='2010-01-01',
                bundle_retired_at=None,wall_loss_percent=loss,result_status='VALID',quality_status='VALID'))
        return data

    def test_explicit_parser_rejects_unimplemented_combinations_and_bad_units(self):
        for q in ['감육속도 0.1 이상인 열교환기','최근 3번 검사 감육률 5%p 이상 증가',
                  'Tube 재질 Cu-Ni 평균 감육률','Shell 재질 Cu-Ni 상위 10대',
                  '감육속도 0.1 mm/년 이상이고 표본 10본 미만',
                  'Plugging 30% 도달까지 10년 이내 생산팀별',
                  '감육속도 0.1 mm/년 이상 잔여수명 5년 이하']:
            with self.subTest(q=q),self.assertRaises(QueryRejected):parse(q)

    def test_rate_matching_count_uses_positive_analysis_rates(self):
        row,detail=self.base();settings=parse('감육속도가 0.1 mm/년 이상인 튜브가 있는 열교환기')
        result,_=assemble([row],{1:detail},settings,as_of=date(2026,11,26))
        self.assertEqual(result['rows'][0]['matching_tube_count'],2)
        self.assertEqual(result['rows'][0]['maximum_corrosion_rate_mm_per_year'],.2)

    def test_sample_rule_excludes_uninspected_and_explains_review(self):
        row,detail=self.base();settings=parse('검사 표본이 10본 미만인 열교환기')
        result,_=assemble([row],{1:detail},settings)
        self.assertIn('검토',result['rows'][0]['sample_review_reason'])
        detail['remaining_life']['sample_wall_loss_estimate']={}
        result,_=assemble([row],{1:detail},settings)
        self.assertEqual(result['rows'],[])
        self.assertIn('최근 유효 검사 집단 없음',result['diagnostics'])

    def test_material_uses_current_spec_only_and_preserves_ranking_limit(self):
        row,detail=self.base();settings=parse('Tube 재질이 Cu-Ni인 열교환기 중 최대 감육률 상위 10대')
        result,_=assemble([row],{1:detail},settings)
        self.assertEqual(result['rows'][0]['tube_material'],'Cu - Ni')
        detail['spec']=SimpleNamespace(tube_material=None)
        detail['remaining_life']['equipment_summary']={'tube_material':'Cu-Ni'}
        self.assertEqual(assemble([row],{1:detail},settings)[0]['rows'],[])

    def test_latest_pair_is_distinct_unambiguous_same_installation_and_bundle(self):
        data=self.history();pair,reason=latest_pair(data,1,date(2026,11,26))
        self.assertIsNone(reason);self.assertEqual(pair[0]['date'],date(2020,1,1))
        data['inspections'].append(dict(data['inspections'][-1],iris_inspection_id=3))
        data['results'].append(dict(data['results'][-1],iris_inspection_id=3))
        self.assertIn('복수',latest_pair(data,1,date(2026,11,26))[1])
        data=self.history();data['results'][-1]['tube_bundle_id']=5
        self.assertIn('번들',latest_pair(data,1,date(2026,11,26))[1])

    def test_increase_is_percentage_points_not_relative_percent(self):
        row,detail=self.base();settings=parse('최근 두 번의 검사 사이 최대 감육률이 5%p 이상 증가한 열교환기는?')
        result,_=assemble([row],{1:detail},settings,data=self.history(),as_of=date(2026,11,26))
        self.assertEqual(result['rows'][0]['wall_loss_increase_percent_points'],5)
        self.assertEqual(result['rows'][0]['previous_maximum_loss'],25.1)
        self.assertEqual(result['rows'][0]['latest_maximum_loss'],30.1)

    def test_invalid_future_superseded_and_partial_cohorts_are_not_compared(self):
        for change in [dict(inspection_date='2030-01-01'),dict(superseded_by_inspection_id=1)]:
            data=self.history();data['inspections'][-1].update(change)
            self.assertIsNone(latest_pair(data,1,date(2026,11,26))[0])
        data=self.history();data['results'][-1]['quality_status']='INVALID'
        self.assertIsNone(latest_pair(data,1,date(2026,11,26))[0])
        data=self.history();data['masters'][100]=data['masters'].pop(1)
        for i in data['inspections']:i.update(heat_exchanger_id=100,original_equipment_id='E-111')
        data['inspections'][-1].update(inspection_date='2021-01-01',source_scope_code='TOPSOUTH')
        self.assertEqual(len(cohorts(data,100,date(2026,11,26))),1)
        self.assertEqual(len(cohorts(data,100,date(2026,11,26),current=False)),2)

    def test_no_inspection_window_requires_confirmed_applicability_and_known_dates(self):
        row,detail=self.base();settings=parse('IRIS 적용 대상인데 최근 5년간 검사 이력이 없는 열교환기')
        data=self.history();data['inspections']=data['inspections'][:1]
        result,_=assemble([row],{1:detail},settings,data=data,as_of=date(2026,11,26))
        self.assertEqual(result['rows'][0]['inspection_cutoff_date'],'2021-11-26')
        data['inspections'][0]['inspection_date']='2021-11-26'
        self.assertEqual(assemble([row],{1:detail},settings,data=data,as_of=date(2026,11,26))[0]['rows'],[])
        data['inspections'][0]['inspection_date']=None
        self.assertIn('날짜 미상',str(assemble([row],{1:detail},settings,data=data)[0]['diagnostics']))
        data['masters'][1]['iris_applicability']='UNKNOWN'
        self.assertEqual(assemble([row],{1:detail},settings,data=data)[0]['rows'],[])

    def test_team_counts_and_earliest_calendar_year_and_fact_units(self):
        row,detail=self.base();other,other_detail=self.base(2,'VCM')
        rows=[row,other,dict(row,heat_exchanger_id=3,remaining_life_years=None)]
        settings=parse('Plugging 20% 도달까지 10년 이내인 열교환기를 생산팀별로 세어줘')
        result,all_rows=assemble(rows,{1:detail,2:other_detail,3:detail},settings,as_of=date(2026,11,26))
        self.assertEqual(sum(r['exchanger_count'] for r in result['rows']),2)
        self.assertEqual(result['rows'][0]['earliest_limit_year'],2030)
        self.assertEqual(result['matched_equipment_count'],2)
        facts=aggregate_evidence(result,all_rows)
        self.assertIn('생산팀',facts['scope_label'])
        selected={key:[r['id'] for r in facts['statements'] if r['section']==key] for key in ('overview','priorities','limitations')}
        self.assertEqual(len(validate(selected,facts)),3)

    def test_history_preserves_report_zero_and_missing_actual_data(self):
        row,detail=self.base();data=self.history()
        data['reports']=[dict(iris_inspection_id=1,plugged_tube_count_before=0,plugged_tube_count_after=0)]
        result,all_rows=assemble([row],{1:detail},parse('E-1 검사 회차별 최대 감육률과 Plugging 수량 추이'),data=data,as_of=date(2026,11,26))
        self.assertEqual(result['result_unit'],'inspection')
        self.assertEqual(result['rows'][0]['reported_plugging_after'],0)
        self.assertIsNone(result['rows'][0]['cumulative_actual_plugging_count'])
        self.assertNotIn('remaining_life_years',result['rows'][0])
        self.assertEqual(aggregate_evidence(result,all_rows)['analyzed_count'],2)

    def test_cancelled_and_future_operations_never_become_reported_actuals(self):
        data=self.history();data['tubes']=[dict(tube_id=10,heat_exchanger_id=1,bundle_id=4,current_status='IN_SERVICE',plugging_date=None)]
        data['operations']=[dict(heat_exchanger_id=1,tube_id=10,plugging_event_id=1,operation='COMPLETE',effective_date='2025-01-01'),
            dict(heat_exchanger_id=1,tube_id=10,plugging_event_id=2,operation='CANCEL',cancelled_event_id=1)]
        self.assertIsNone(cumulative_completed(data,1,{4},date(2026,1,1))[0])
        data['operations']=data['operations'][:1]
        self.assertIsNone(cumulative_completed(data,1,{4},date(2024,1,1))[0])
        self.assertEqual(cumulative_completed(data,1,{4},date(2025,1,1))[0],1)

    def test_known_measured_limit_cannot_be_overwritten_and_no_iris_classification_is_kept(self):
        from iris2.domain.sample_wall_loss import estimate_sample_wall_loss
        sample=estimate_sample_wall_loss([0]*79+[40]*21,total_tube_count=100,installation_date='2010-01-01',measurement_date='2025-01-01')
        life=dict(status='CALCULATED',remaining_life_years=0,total_tube_count=100,allowable_plugging_count=20,
            actual_plugged_count=0,threshold_reached_count=21,registered_inspection_count=1,tube_projections=[],
            analysis_tube_rows=[],life_reached_year=2026,sample_wall_loss_estimate=sample)
        self.assertEqual(build_equipment_summary(life,date(2026,11,26))['remaining_life_years'],0)
        life.update(registered_inspection_count=0,actual_plugged_count=21,threshold_reached_count=0)
        self.assertEqual(build_equipment_summary(life,date(2026,11,26))['band'],'uninspected')


if __name__=='__main__':unittest.main()
