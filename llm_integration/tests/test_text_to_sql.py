from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from iris2.llm_integration import text_to_sql as module


SUMMARY = {"sql": "SELECT COUNT(*) AS inspected_tubes, COUNT(wall_loss_percent) AS valid_loss_tubes, MIN(minimum_wall_thickness_mm) AS minimum_mm, MAX(wall_loss_percent) AS maximum_loss, AVG(wall_loss_percent) AS mean_loss FROM analysis_tubes", "parameters": []}
TOP = {"sql": "SELECT tube_id, source_tube_id, wall_loss_percent, minimum_wall_thickness_mm, location_mm, iris_tube_result_id, source_page FROM analysis_tubes WHERE wall_loss_percent >= ? ORDER BY wall_loss_percent DESC, tube_id ASC LIMIT 5", "parameters": [30]}


class ValidationTests(unittest.TestCase):
    def test_summary_and_parameterized_ranking(self):
        self.assertIn("LIMIT 100", module.validate_proposal(SUMMARY)[0])
        self.assertEqual(module.validate_proposal(TOP)[1], [30])

    def test_adversarial_sql_is_rejected(self):
        attacks = [
            "DELETE FROM analysis_tubes", "SELECT tube_id FROM analysis_tubes; SELECT 1",
            "SELECT tube_id FROM equipment", "SELECT tube_id FROM iris2.analysis_tubes",
            "SELECT tube_id FROM analysis_tubes a", "SELECT * FROM analysis_tubes",
            "SELECT SLEEP(?) AS x FROM analysis_tubes", "SELECT LOAD_FILE(?) AS x FROM analysis_tubes",
            "SELECT tube_id INTO OUTFILE 'x' FROM analysis_tubes",
            "SELECT tube_id FROM analysis_tubes FOR UPDATE",
            "SELECT tube_id FROM analysis_tubes UNION SELECT tube_id FROM analysis_tubes",
            "SELECT tube_id FROM analysis_tubes WHERE tube_id IN (SELECT tube_id FROM analysis_tubes)",
            "SELECT tube_id FROM analysis_tubes JOIN equipment USING(tube_id)",
            "SELECT tube_id FROM analysis_tubes -- comment",
            "SELECT /* hint */ tube_id FROM analysis_tubes",
            "SELECT @x FROM analysis_tubes", "SELECT ? AS x FROM analysis_tubes",
            "SELECT tube_id FROM analysis_tubes WHERE wall_loss_percent > 30",
            "SELECT tube_id FROM analysis_tubes LIMIT 101",
            "SELECT tube_id FROM analysis_tubes LIMIT 0",
            "SELECT tube_id FROM analysis_tubes LIMIT 1 OFFSET 1",
            "WITH x AS (SELECT tube_id FROM analysis_tubes) SELECT tube_id FROM x",
            "SELECT unknown_field FROM analysis_tubes",
            "SELECT tube_id AS x, source_tube_id AS x FROM analysis_tubes",
        ]
        for sql in attacks:
            with self.subTest(sql=sql), self.assertRaises(module.QueryRejected):
                module.validate_proposal({"sql": sql, "parameters": []})

    def test_parameters_and_invalid_outputs(self):
        for value in [None, [], {"sql": "SELECT 1"}, {**TOP, "parameters": []},
                      {**TOP, "parameters": [float('nan')]}, {**TOP, "parameters": [{}]}]:
            with self.subTest(value=value), self.assertRaises(module.QueryRejected):
                module.validate_proposal(value)

    def test_model_is_called_and_sql_not_rule_generated(self):
        client = Mock()
        client.generate.return_value = __import__('json').dumps(TOP)
        self.assertEqual(module.generate_proposal("감육률 30% 이상인 Tube 5개", client), TOP)
        self.assertEqual(client.generate.call_args.kwargs["temperature"], 0)
        client.generate.return_value = '{"unsupported":"수명"}'
        with self.assertRaises(module.QueryRejected):
            module.generate_proposal("잔여수명", client)

    def test_wrong_but_readable_sql_is_not_an_answer(self):
        with self.assertRaises(module.QueryRejected):
            module.validate_question_contract("최근 검사 요약", TOP)
        with self.assertRaises(module.QueryRejected):
            module.validate_question_contract("감육률 30% 이상 Tube", SUMMARY)
        wrong = {**TOP, 'parameters':[20]}
        with self.assertRaises(module.QueryRejected):
            module.validate_question_contract("감육률 30% 이상 Tube", wrong)
        with self.assertRaises(module.QueryRejected):
            module.validate_question_contract("감육이 가장 심한 Tube 5개", TOP)

    def test_one_model_repair_then_fail_closed(self):
        import json
        client = Mock()
        client.generate.side_effect = [json.dumps(TOP), json.dumps(SUMMARY)]
        self.assertEqual(module.generate_proposal("최근 검사 요약", client), SUMMARY)
        self.assertEqual(client.generate.call_count, 2)
        client.generate.side_effect = [json.dumps(TOP), json.dumps(TOP)]
        with self.assertRaises(module.QueryRejected):
            module.generate_proposal("최근 검사 요약", client)

    def test_unsupported_questions_never_reach_model(self):
        client = Mock()
        for q in ('잔여수명을 계산해 줘', '이전 검사와 비교', '종합의견 작성', '차기 검사 시점'):
            with self.subTest(q=q), self.assertRaises(module.QueryRejected):
                module.generate_proposal(q, client)
        client.generate.assert_not_called()

    @patch.object(module.dbapi, 'schema_for', return_value='iris2')
    @patch.object(module.dbapi, 'load_database_config')
    @patch.object(module.dbapi.pymysql, 'connect')
    def test_dedicated_profile_and_invalid_profiles(self, connect, config, schema):
        config.return_value = dict(host='127.0.0.1',port=3307,user='iris2_test',password='test',charset='utf8mb4')
        module.dbapi.connect(module.DB_PATH, readonly=True, readonly_profile='text_to_sql')
        self.assertEqual(config.call_args.kwargs['path'].name, 'database-text-to-sql.conf')
        connect.reset_mock()
        for readonly,profile in ((False,'text_to_sql'),(True,'../../other')):
            with self.assertRaises(ValueError):
                module.dbapi.connect(module.DB_PATH,readonly=readonly,readonly_profile=profile)
        connect.assert_not_called()

    @patch.object(module.dbapi, "connect")
    def test_access_and_validation_fail_before_connect(self, connect):
        with self.assertRaises(PermissionError):
            module.execute_proposal(TOP, exchanger_id=1, authorized_exchanger_ids={2})
        with self.assertRaises(module.QueryRejected):
            module.execute_proposal({"sql":"DELETE FROM x", "parameters":[]}, exchanger_id=1, authorized_exchanger_ids={1})
        connect.assert_not_called()

    @patch.object(module.dbapi, "connect")
    def test_scoped_sql_bind_order_and_cleanup(self, connect):
        connection = connect.return_value
        connection.execute.return_value.fetchone.return_value = {"unit_code":"VCM1", "equipment_tag":"E-141B"}
        connection.execute.return_value.fetchall.side_effect = [
            [("GRANT SELECT ON `iris2`.* TO 'reader'@'localhost'",)],
            [{"iris_inspection_id":9,"effective_date":"2026-01-01"}]]
        connection.execute.return_value.fetchmany.return_value = [{"tube_id": 3,
            '__iris2_exchanger_id':7, '__iris2_equipment_code':'E-107'}]
        connection.execute.return_value.description = [('tube_id',)]
        result = module.execute_proposal(TOP, exchanger_id=7, authorized_exchanger_ids={7})
        sql, bindings = connection.execute.call_args.args
        self.assertIn("u.unit_code IN ('VCM1', 'VCM2')", sql)
        self.assertEqual(bindings, (7, 9, 30))
        self.assertEqual(result["rows"], [{"tube_id":3,'heat_exchanger_id':7,'equipment_code':'E-107'}])
        self.assertEqual(result['columns'][:2], ['equipment_code','heat_exchanger_id'])
        self.assertIn('hx.heat_exchanger_id', sql)
        self.assertTrue(connect.call_args.kwargs["readonly"])
        connection.rollback.assert_called_once()
        connection.close.assert_called_once()

    @patch.object(module.dbapi, 'connect')
    def test_detail_rows_keep_their_own_exchanger_codes_in_combined_scope(self, connect):
        connection=connect.return_value
        connection.execute.return_value.fetchone.return_value={'equipment_code':'E-107','unit_code':'VCM1'}
        connection.execute.return_value.fetchall.side_effect=[
            [('GRANT SELECT ON iris2.* TO reader',)],
            [{'iris_inspection_id':9,'effective_date':'2026-01-01'}],
            [{'iris_inspection_id':10,'effective_date':'2026-01-02'}]]
        connection.execute.return_value.description=[('tube_id',),('__iris2_exchanger_id',),('__iris2_equipment_code',)]
        connection.execute.return_value.fetchmany.return_value=[
            {'tube_id':3,'__iris2_exchanger_id':7,'__iris2_equipment_code':'E-107'},
            {'tube_id':4,'__iris2_exchanger_id':8,'__iris2_equipment_code':'E-108'}]
        result=module.execute_proposal(TOP,exchanger_id=7,authorized_exchanger_ids={7,8},scopes=[(7,9),(8,10)])
        self.assertEqual([r['equipment_code'] for r in result['rows']],['E-107','E-108'])
        self.assertEqual([r['heat_exchanger_id'] for r in result['rows']],[7,8])

    @patch.object(module.dbapi, "connect")
    def test_ambiguous_latest_round_is_not_silently_selected(self, connect):
        connection = connect.return_value
        connection.execute.return_value.fetchone.return_value = {"unit_code":"VCM1"}
        connection.execute.return_value.fetchall.side_effect = [[("GRANT SELECT ON `iris2`.* TO 'reader'@'localhost'",)], [
            {"iris_inspection_id":9,"effective_date":"2026-01-01"},
            {"iris_inspection_id":8,"effective_date":"2026-01-01"}]]
        with self.assertRaises(module.QueryRejected):
            module.execute_proposal(TOP, exchanger_id=7, authorized_exchanger_ids={7})
        connection.close.assert_called_once()

    @patch.object(module.dbapi, "connect")
    def test_overprivileged_database_accounts_are_rejected(self, connect):
        for grant in ["GRANT ALL PRIVILEGES ON iris2.* TO reader",
                      "GRANT SELECT, INSERT ON iris2.* TO reader",
                      "GRANT FILE ON *.* TO reader", "GRANT some_role TO reader",
                      "GRANT SELECT ON iris2.* TO reader WITH GRANT OPTION"]:
            connection = connect.return_value = Mock()
            connection.execute.return_value.fetchall.return_value = [(grant,)]
            with self.subTest(grant=grant), self.assertRaises(module.QueryRejected):
                module.execute_proposal(TOP, exchanger_id=7, authorized_exchanger_ids={7})
            self.assertEqual(connection.execute.call_count, 1)
            connection.rollback.assert_called_once()
            connection.close.assert_called_once()

    @patch.object(module.dbapi, "connect")
    def test_database_failure_closes_connection(self, connect):
        connection = connect.return_value
        connection.execute.side_effect = RuntimeError("database unavailable")
        with self.assertRaises(RuntimeError):
            module.execute_proposal(TOP, exchanger_id=7, authorized_exchanger_ids={7})
        connection.close.assert_called_once()

    def test_access_denied_does_not_call_model(self):
        client = Mock()
        with self.assertRaises(PermissionError):
            module.answer_question("요약", client, exchanger_id=7, authorized_exchanger_ids={8})
        client.generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
