from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2.application import wall_loss_exchanger_count as count
from iris2.llm_integration.text_to_sql import QueryRejected, validate_proposal, validate_question_contract, execute_proposal, generate_proposal


class WallLossCountTests(unittest.TestCase):
    def test_core_generator_bypasses_model_for_supported_count(self):
        client = Mock()
        value = generate_proposal('2025년 감육률 10% 이상 교환기 수량 공정별', client)
        self.assertTrue(count.is_proposal(value))
        client.generate.assert_not_called()

    def test_identity_columns_remain_closed_outside_fixed_count(self):
        with self.assertRaises(QueryRejected):
            validate_proposal(dict(sql='SELECT unit_code, heat_exchanger_id FROM analysis_tubes',parameters=[]))

    def test_exact_contract_and_comparisons(self):
        for comparison, operator in [('이상','>='),('초과','>'),('이하','<='),('미만','<')]:
            question = f'튜브별 감육률 10% {comparison}인 교환기 수량은 VCM1과 VCM2로 구분해줘'
            self.assertTrue(count.matches(question))
            proposal = count.proposal(question)
            validate_question_contract(question, proposal)
            self.assertIn(f'wall_loss_percent {operator} ?', proposal['sql'])
            self.assertEqual(proposal['parameters'], [10.0])
            sql, parameters = validate_proposal(proposal)
            self.assertTrue(count.is_proposal(dict(sql=sql, parameters=parameters)))
            with self.assertRaises(QueryRejected):
                validate_question_contract(question, dict(proposal, sql=proposal['sql'].replace('COUNT(DISTINCT heat_exchanger_id)', 'COUNT(tube_id)')))

    def test_does_not_capture_tube_lists_or_summary(self):
        for question in ['감육률 10% 이상 튜브 목록', '검사 결과 요약', '검사를 가장 많이한 교환기 10대']:
            self.assertFalse(count.matches(question))

    def test_bad_ranges_and_additional_conditions(self):
        for question in ['감육률 -1% 이상 교환기 수량 공정별', '감육률 101% 이상 교환기 수량 공정별',
                         '평균 감육률 10% 이상 교환기 수량 공정별', '모든 튜브 감육률 10% 이상 교환기 수량 공정별',
                         '감육률 10% 이상 20% 이하 교환기 수량 공정별']:
            with self.subTest(question=question), self.assertRaises(QueryRejected):
                count.proposal(question)

    def test_real_mariadb_distinct_counts_match_independent_query(self):
        from iris2.application import text_to_sql_service as analysis
        from iris2.database import get_engine
        from sqlalchemy import text
        for period in [None, dict(start='2020-01-01',end='2025-12-31')]:
            selector = analysis.select_period_scopes if period else analysis.select_scopes
            scopes, excluded, allowed = selector(**(dict(period=period) if period else {}),unit_codes=['VCM1','VCM2'])
            pairs = [(s['equipment']['heat_exchanger_id'],s['inspection']['iris_inspection_id']) for s in scopes]
            proposal = count.proposal('감육률 10% 이상 교환기 수량 공정별')
            result = execute_proposal(proposal, exchanger_id=pairs[0][0],inspection_id=pairs[0][1],
                                      scopes=pairs, period=period,authorized_exchanger_ids=allowed)
            ids = ','.join(str(i) for _, i in pairs)
            with get_engine().connect() as connection:
                rows = connection.execute(text(f'''SELECT u.unit_code, i.heat_exchanger_id, r.wall_loss_percent, r.result_status
                    FROM iris_tube_result r JOIN iris_inspection i ON i.iris_inspection_id=r.iris_inspection_id
                    JOIN heat_exchanger h ON h.heat_exchanger_id=i.heat_exchanger_id
                    JOIN equipment e ON e.equipment_id=h.equipment_id JOIN process_unit u ON u.unit_id=e.unit_id
                    WHERE i.iris_inspection_id IN ({ids}) AND i.superseded_by_inspection_id IS NULL''')).mappings().all()
            expected = {}
            for row in rows:
                if row['result_status'] == 'VALID' and row['wall_loss_percent'] is not None and row['wall_loss_percent'] >= 10:
                    expected.setdefault(row['unit_code'],set()).add(row['heat_exchanger_id'])
            self.assertEqual(result['rows'], [dict(unit_code=unit,exchanger_count=len(ids)) for unit,ids in sorted(expected.items())])
            self.assertEqual(result['columns'], ['unit_code','exchanger_count'])


if __name__ == '__main__':
    unittest.main()
