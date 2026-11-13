"""Language aliases must preserve numeric conditions and safety contracts."""
import json
import unittest
from datetime import date
from unittest.mock import Mock

from iris2.application.query_period import parse
from iris2.llm_integration.question_language import normalize
from iris2.llm_integration.text_to_sql import QueryRejected, generate_proposal, validate_question_contract
from iris2.llm_integration.tests.test_text_to_sql import SUMMARY, TOP


class LanguageTests(unittest.TestCase):
    def test_equivalent_thresholds_keep_contract(self):
        for question in ('두께 감소율 30퍼센트 이상 전열관', 'wall loss 30% 이상 tubes',
                         '감육 율 30 이상 튜브', '감육률 ３０％ 이상 Tube'):
            with self.subTest(question=question):
                validate_question_contract(question, TOP)
                with self.assertRaises(QueryRejected):
                    validate_question_contract(question, {**TOP, 'parameters': [20]})

    def test_summary_aliases_and_model_prompt(self):
        client = Mock()
        client.generate.return_value = json.dumps(SUMMARY)
        for question in ('검사 현황 알려줘', '검사 결과 정리해줘', 'summary'):
            self.assertEqual(generate_proposal(question, client), SUMMARY)
            with self.assertRaises(QueryRejected):
                validate_question_contract(question, TOP)
        self.assertIn('요약', client.generate.call_args.args[0])
        self.assertEqual(normalize('TOP 10 전열관'), '상위 10개 Tube')

    def test_calendar_periods(self):
        cases = {'이번 달': ('2026-11-01', '2026-11-13'),
                 '지난달': ('2026-10-01', '2026-10-31'),
                 '이번주': ('2026-11-09', '2026-11-13'),
                 '지난 주': ('2026-11-02', '2026-11-08'),
                 '어제': ('2026-11-12', '2026-11-12'),
                 '상반기': ('2026-01-01', '2026-06-30'),
                 '하반기': ('2026-07-01', '2026-11-13'),
                 '2025년 2월': ('2025-02-01', '2025-02-28')}
        for phrase, (start, end) in cases.items():
            with self.subTest(phrase=phrase):
                period, question = parse(phrase + ' 검사 요약', date(2026, 11, 13))
                self.assertEqual(period, dict(start=start, end=end))
                self.assertEqual(question, '검사 요약')
        self.assertEqual(parse('지난달 요약', date(2026, 1, 5))[0]['start'], '2025-12-01')
        for phrase in ('2026년 13월', '지난달 올해', '내년', '2027년 1월'):
            with self.subTest(phrase=phrase), self.assertRaises(QueryRejected):
                parse(phrase, date(2026, 11, 13))
