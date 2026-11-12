import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2.application import inspection_frequency as frequency
from iris2.llm_integration.text_to_sql import QueryRejected
from iris2.tests import test_text_to_sql_web as web_tests

QUESTION='최근 iris 검사를 제일 많이 수행한 열교환기를 리스트해줘'


class FrequencyTests(unittest.TestCase):
    def test_exact_question_and_periods(self):
        self.assertTrue(frequency.matches(QUESTION))
        self.assertTrue(frequency.matches('IRIS 검사 횟수 상위 5대 교환기'))
        self.assertFalse(frequency.matches('감육이 가장 심한 Tube 5개를 알려줘'))
        self.assertEqual(frequency.options(QUESTION,date(2026,11,9)),dict(start='2021-11-09',end='2026-11-09',limit=20))
        self.assertEqual(frequency.options('최근 3년 IRIS 검사 횟수 상위 5대 열교환기',date(2026,11,9)),
                         dict(start='2023-11-09',end='2026-11-09',limit=5))
        self.assertEqual(frequency.options('작년 검사 횟수 많은 교환기',date(2026,11,9))['end'],'2025-12-31')
        self.assertEqual(frequency.options(QUESTION,date(2024,2,29))['start'],'2019-02-28')
        for question in ['최근 3개월 검사 횟수 많은 열교환기','최근 0년 검사 횟수 많은 교환기',
                         '검사 횟수 상위 101대 교환기','2020년 검사 많은 교환기', '검사 횟수 많은 교환기 잔여수명 예측']:
            with self.subTest(question=question),self.assertRaises(QueryRejected): frequency.options(question)

    @patch.object(frequency.dbapi,'connect')
    def test_scoped_bindings_grants_and_cleanup(self,connect):
        period=frequency.options(QUESTION,date(2026,11,9))
        proposal=frequency.proposal([1,2],period)
        self.assertEqual(proposal['parameters'],[1,2,'2021-11-09','2026-11-10'])
        self.assertIn('COUNT(DISTINCT i.iris_inspection_id)',proposal['sql'])
        self.assertIn("UPPER(TRIM(i.inspection_method))='IRIS'",proposal['sql'])
        conn=connect.return_value
        conn.execute.return_value.fetchall.return_value=[('GRANT SELECT ON `iris2`.* TO reader',)]
        conn.execute.return_value.description=[('inspection_count',)]
        conn.execute.return_value.fetchmany.return_value=[dict(inspection_count=3)]
        result=frequency.execute([1,2],period,proposal,{1,2})
        self.assertEqual(result['rows'],[dict(inspection_count=3)])
        conn.rollback.assert_called_once();conn.close.assert_called_once()
        connect.reset_mock()
        with self.assertRaises(PermissionError): frequency.execute([1,2],period,proposal,{1})
        with self.assertRaises(QueryRejected): frequency.execute([1,2],period,dict(sql='DELETE FROM equipment',parameters=[]),{1,2})
        connect.assert_not_called()
        conn.execute.return_value.fetchall.return_value=[('GRANT ALL PRIVILEGES ON *.* TO reader',)]
        with self.assertRaises(QueryRejected):frequency.execute([1,2],period,proposal,{1,2})


class FrequencyWebTests(web_tests.TextToSqlWebTests):
    def test_ranking_question_generates_history_sql_without_model(self):
        preview=self.post('generate',dict(question=QUESTION,unit_codes=['VCM2']))
        self.assertEqual(preview.status_code,200)
        self.assertEqual(preview.json['query_kind'],'inspection_frequency')
        self.assertIn('COUNT(DISTINCT',preview.json['proposal']['sql'])
        self.worker.assert_not_called();self.scope.assert_not_called()
        with patch('iris2.web.routes.text_to_sql.frequency.execute',return_value={'rows':[]}) as execute:
            response=self.post('execute',dict(token=preview.json['token'],sql='DELETE FROM equipment',exchanger_ids=[999]))
        self.assertEqual(response.status_code,200)
        self.assertEqual(execute.call_args.args[0],[151])

    def test_missing_selection_defaults_to_catalog_and_scope_is_rechecked(self):
        preview=self.post('generate',dict(question=QUESTION))
        self.assertEqual(preview.status_code,200)
        self.catalog.return_value=[]
        self.assertEqual(self.post('execute',dict(token=preview.json['token'])).status_code,403)

    def test_invalid_scope_rejected(self):
        for scope in [dict(unit_codes=['VCM3']),dict(exchanger_ids=[999]),dict(exchanger_ids=[True]),
                      dict(unit_codes=['VCM1'],exchanger_ids=[151])]:
            self.assertIn(self.post('generate',dict(question=QUESTION,**scope)).status_code,(400,403))
        self.worker.assert_not_called()
