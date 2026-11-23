import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2.application import text_to_sql_equipment as query
from iris2.application import text_to_sql_commentary as commentary
from iris2.llm_integration.text_to_sql import QueryRejected
from iris2.tests.test_text_to_sql_web import TextToSqlWebTests


class EquipmentOptionsTests(unittest.TestCase):
    def test_missing_life_is_excluded_and_zero_is_preserved(self):
        class Rows:
            def __init__(self,rows):self.rows=rows
            def fetchall(self):return self.rows
        class Connection:
            def execute(self,sql,parameters=()):
                return Rows([('GRANT SELECT ON iris2.* TO reader',)]) if sql=='SHOW GRANTS' else Rows([dict(heat_exchanger_id=i) for i in [1,2]])
            def rollback(self):pass
            def close(self):pass
        def detail(identifier):
            return dict(remaining_life=dict(analysis_tube_rows=[],equipment_summary={},
                equipment_overview=dict(remaining_life_years=None if identifier==1 else 0,
                    remaining_display='산정 불가' if identifier==1 else '0.0년',source='통계 추정',recommendation_date=None)))
        with patch.object(query.dbapi,'connect',return_value=Connection()),patch.object(query.services,'exchanger_detail',side_effect=detail):
            result=query.execute([1,2],query.options('잔여수명 5년 이하 열교환기'),query.proposal([1,2]),{1,2})
        self.assertEqual([r['heat_exchanger_id'] for r in result['rows']],[2])
        self.assertEqual(result['rows'][0]['remaining_display'],'0.0년')

    def test_filters_and_missing_are_explicit(self):
        self.assertEqual(query.options('잔여수명 5년 이하인 열교환기')['conditions'],[['remaining_life_years','이하',5]])
        self.assertEqual(query.options('감육이 심한 열교환기 5대')['sort'],'loss')
        for text in ['평균 감육률 교환기','2025년 검사 결과','차기 검사일 이전 설비','hello']:
            with self.subTest(text=text),self.assertRaises(QueryRejected):query.options(text)

    def test_tampered_sql_or_revoked_scope_never_connect(self):
        settings=query.options('열교환기 목록')
        with patch.object(query.dbapi,'connect') as connect:
            with self.assertRaises(PermissionError):query.execute([1],settings,query.proposal([1]),set())
            with self.assertRaises(QueryRejected):query.execute([1],settings,dict(sql='DELETE',parameters=[]),{1})
            connect.assert_not_called()

    def test_commentary_grounding_and_no_fake_fallback(self):
        facts=dict(total_rows=1,examples=[dict(remaining_display='5.0년',recommendation_date='2028-01-01')])
        self.assertEqual(commentary.validate(dict(text='잔여기간은 5.0년으로 표시됩니다.'),facts),'잔여기간은 5.0년으로 표시됩니다.')
        for text in ['2030년 검사하세요.','안전합니다.']:
            with self.assertRaises(QueryRejected):commentary.validate(dict(text=text),facts)


class EquipmentWebTests(TextToSqlWebTests):
    def permit_equipment(self):
        for key in ('EXCHANGERS','REMAINING_LIFE'):
            self.profile['permissions'][key]=dict(can_view=True,can_edit=False)

    def test_equipment_requires_underlying_screen_permissions(self):
        response=self.post('generate',dict(question='열교환기 잔여수명 목록',result_unit='equipment'))
        self.assertEqual(response.status_code,403)
        self.worker.assert_not_called()

    def test_equipment_query_and_summary_are_bound_to_result_and_actor(self):
        self.permit_equipment()
        preview=self.post('generate',dict(question='열교환기 잔여수명 목록',result_unit='equipment'))
        self.assertEqual(preview.status_code,200,preview.json)
        row=dict(heat_exchanger_id=151,equipment_tag='E-106',remaining_life_years=0,
            remaining_display='0.0년',recommendation_date=None,maximum_loss=30,life_source='통계 추정')
        with patch.object(query,'execute',return_value=dict(rows=[row],result_count=1,matched_count=1,limit_reached=False)):
            result=self.post('execute',dict(token=preview.json['token']))
        self.assertEqual(result.status_code,200,result.json)
        token=result.json['result']['summary_token']
        with patch.object(commentary,'generate',return_value=dict(text='근거 요약',model='local',status='generated')) as worker:
            summary=self.post('summarize',dict(token=token,rows=[dict(remaining_display='999년')]))
            self.assertEqual(summary.status_code,200,summary.json)
            self.assertEqual(worker.call_args.args[0]['examples'][0]['remaining_display'],'0.0년')
            other=self.post('summarize',dict(token=token),self.make_client(2))
            self.assertEqual(other.status_code,403)
        self.assertEqual(self.post('summarize',dict(token=token+'x')).status_code,400)
        self.worker.assert_not_called()


if __name__=='__main__':unittest.main()
