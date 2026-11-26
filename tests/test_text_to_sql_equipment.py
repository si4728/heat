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
                return Rows([('GRANT SELECT ON iris2.* TO reader',)]) if sql=='SHOW GRANTS' else Rows([dict(heat_exchanger_id=i) for i in [1,2,3]])
            def rollback(self):pass
            def close(self):pass
        def detail(identifier):
            return dict(remaining_life=dict(analysis_tube_rows=[],equipment_summary={},
                equipment_overview=dict(remaining_life_years={1:None,2:0,3:5.4}[identifier],
                    remaining_display={1:'산정 불가',2:'0.0년',3:'5.4년'}[identifier],source='통계 추정',recommendation_date=None)))
        with patch.object(query.dbapi,'connect',return_value=Connection()),patch.object(query.services,'exchanger_detail',side_effect=detail):
            result=query.execute([1,2,3],query.options('잔여수명 5년 이하 열교환기'),query.proposal([1,2,3]),{1,2,3})
            explicit=query.execute([1,2,3],query.options('열교환기 1대'),query.proposal([1,2,3]),{1,2,3})
            display_settings=query.options('열교환기 목록');display_settings['limit']=1
            display=query.execute([1,2,3],display_settings,query.proposal([1,2,3]),{1,2,3})
        self.assertEqual([r['heat_exchanger_id'] for r in result['rows']],[2])
        self.assertEqual(result['rows'][0]['remaining_display'],'0.0년')
        self.assertEqual(explicit['_commentary_facts']['analyzed_count'],1)
        self.assertEqual(display['_commentary_facts']['analyzed_count'],3)
        self.assertEqual(display['_commentary_facts']['examples'][0]['heat_exchanger_id'],2)

    def test_filters_and_missing_are_explicit(self):
        self.assertEqual(query.options('잔여수명 5년 이하인 열교환기')['conditions'],[['remaining_life_years','이하',5]])
        self.assertEqual(query.options('감육이 심한 열교환기 5대')['sort'],'loss')
        self.assertEqual(query.options('예상 잔여수명이 5년 이하인 열교환기를 보여줘')['conditions'],[['remaining_life_years','이하',5]])
        self.assertEqual(query.options('공정별 차기 검사 권고일이 2027년 이내인 열교환기를 보여줘')['conditions'],[['recommendation_date','이하','2027-12-31']])
        for text in ['평균 감육률 교환기','2025년 검사 결과','차기 검사일 이전 설비','hello']:
            with self.subTest(text=text),self.assertRaises(QueryRejected):query.options(text)

    def test_image_examples_have_explicit_query_modes(self):
        questions=['최근 두 번의 검사 사이 최대 감육률이 5%p 이상 증가한 열교환기는?',
            '감육속도가 0.1 mm/년 이상인 튜브가 있는 열교환기를 알려줘',
            'Plugging 20% 도달까지 10년 이하인 열교환기를 생산팀별로 세어줘',
            '검사 표본이 10본 미만이라 재검사 범위를 늘려야 하는 열교환기는?',
            'IRIS 적용 대상인데 최근 5년간 검사 이력이 없는 열교환기는?',
            'Tube 재질이 Cu-Ni인 열교환기 중 최대 감육률 상위 10대',
            'E-106의 검사 회차별 최대 감육률과 Plugging 수량 추이를 보여줘']
        for question,mode in zip(questions,['increase','rate','team_limit','sample','overdue_iris','material','history']):
            with self.subTest(question=question):self.assertEqual(query.options(question)['mode'],mode)

    def test_tampered_sql_or_revoked_scope_never_connect(self):
        settings=query.options('열교환기 목록')
        with patch.object(query.dbapi,'connect') as connect:
            with self.assertRaises(PermissionError):query.execute([1],settings,query.proposal([1]),set())
            with self.assertRaises(QueryRejected):query.execute([1],settings,dict(sql='DELETE',parameters=[]),{1})
            connect.assert_not_called()

    def test_commentary_grounding_and_no_fake_fallback(self):
        row=dict(heat_exchanger_id=1,remaining_life_years=5,remaining_display='5.0년',recommendation_date='2028-01-01')
        facts=commentary.evidence(dict(rows=[row]))
        valid={key:[s['id'] for s in facts['statements'] if s['section']==key] for key in ('overview','priorities','limitations')}
        sections=commentary.validate(valid,facts)
        self.assertEqual([s['title'] for s in sections],['조회 요약','우선 확인 대상','해석의 한계'])
        for payload in [dict(text='2030년 검사하세요.'),dict(valid,priorities=['UNKNOWN']),dict(valid,limitations=[])]:
            with self.assertRaises(QueryRejected):commentary.validate(payload,facts)


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
