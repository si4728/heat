import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2.application import query_period, inspection_frequency as frequency
from iris2.application import text_to_sql_service as service
from iris2.llm_integration.text_to_sql import QueryRejected
from iris2.tests.test_text_to_sql_web import TextToSqlWebTests


class PeriodTests(unittest.TestCase):
    def test_dates_and_calendar_boundaries(self):
        for text, today, start, end in [
            ('최근 1개월 요약', date(2024,3,31), '2024-02-29', '2024-03-31'),
            ('최근 1년 요약', date(2024,2,29), '2023-02-28', '2024-02-29'),
            ('최근 3일 요약', date(2026,11,13), '2026-11-10', '2026-11-13'),
            ('2025년 요약', date(2026,11,13), '2025-01-01', '2025-12-31'),
            ('2024년 2월 요약', date(2026,11,13), '2024-02-01', '2024-02-29'),
            ('2025-01-01부터 2025-12-31까지 요약', date(2026,11,13), '2025-01-01', '2025-12-31'),
            ('2025.1.1~2025.2.28 요약', date(2026,11,13), '2025-01-01', '2025-02-28'),
            ('올해 요약', date(2026,11,13), '2026-01-01', '2026-11-13'),
            ('작년 요약', date(2026,11,13), '2025-01-01', '2025-12-31'),
        ]:
            with self.subTest(text=text):
                period, question = query_period.parse(text, today)
                self.assertEqual(period, dict(start=start, end=end))
                self.assertEqual(question, '요약')
        self.assertEqual(query_period.parse('감육률 30% 이상'), (None, '감육률 30% 이상'))
        self.assertTrue(query_period.parse('전체 이력 요약')[0]['all_history'])

    def test_invalid_or_ambiguous_dates_are_not_ignored(self):
        for text in ['최근 0개월 요약', '2025-02-30~2025-03-01 요약',
                     '2025-12-31~2025-01-01 요약', '최근 3개월 2025년 요약',
                     '지난달 요약', '2025-01-01 이후 요약', '2099년 요약',
                     '2025년 13월 요약', '올해 3월 요약', '2025년 2월 10일 요약']:
            with self.subTest(text=text), self.assertRaises(QueryRejected):
                query_period.parse(text, date(2026,11,13))

    def test_month_count_is_not_ranking_limit(self):
        self.assertEqual(frequency.options('최근 3개월 검사를 많이한 튜브 10개')['limit'], 10)
        self.assertEqual(frequency.options('최근 3개월 검사를 많이한 튜브')['limit'], 20)

    @patch.object(service, 'inspections')
    @patch.object(service, 'catalog')
    def test_all_matching_rounds_and_explicit_round(self, catalog, inspections):
        catalog.return_value = [dict(heat_exchanger_id=1, unit_code='VCM1')]
        inspections.return_value = [dict(iris_inspection_id=i, effective_date=d) for i,d in
            [(1,'2025-01-01'), (2,'2025-12-31'), (3,'2026-01-01'), (4,None)]]
        period = dict(start='2025-01-01', end='2025-12-31')
        scopes, _, _ = service.select_period_scopes(period, exchanger_ids=[1])
        self.assertEqual([s['inspection']['iris_inspection_id'] for s in scopes], [1,2])
        with self.assertRaises(QueryRejected):
            service.select_period_scopes(period, exchanger_ids=[1], inspection_id=3)
        with self.assertRaises(PermissionError):
            service.select_period_scopes(period, exchanger_ids=[999])
        inspections.return_value *= 300
        with self.assertRaises(QueryRejected):
            service.select_period_scopes(period, exchanger_ids=[1])


class PeriodWebTests(TextToSqlWebTests):
    def test_period_is_pinned_and_removed_from_model_question(self):
        self.rounds.return_value = [self.inspection,
            dict(iris_inspection_id=388, effective_date='2025-01-01'),
            dict(iris_inspection_id=390, effective_date='2026-01-01')]
        preview = self.post('generate', dict(exchanger_id=151, question='2025년 검사 결과 요약'))
        self.assertEqual(preview.status_code, 200)
        self.worker.assert_called_once_with('검사 결과 요약')
        self.assertEqual(len(preview.json['scopes']), 2)
        self.assertEqual(preview.json['period']['end'], '2025-12-31')
        result = self.post('execute', dict(token=preview.json['token'], period={'start':'2000-01-01'}))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.execute.call_args.kwargs['scopes'], [[151,389],[151,388]])
        self.assertEqual(self.execute.call_args.kwargs['period'], dict(start='2025-01-01',end='2025-12-31'))

    def test_empty_or_invalid_period_never_reaches_model(self):
        for question in ['2020년 검사 요약', '최근 0개월 검사 요약']:
            self.assertEqual(self.post('generate', dict(exchanger_id=151,question=question)).status_code, 400)
        self.worker.assert_not_called()


if __name__ == '__main__':
    unittest.main()
