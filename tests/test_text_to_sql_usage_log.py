import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2.application import text_to_sql_usage_log as usage
from iris2.hx_configuration import APP_DIR
from iris2.tests.test_text_to_sql_web import TextToSqlWebTests


class MonthlyUsageWriterTests(unittest.TestCase):
    def setUp(self):
        (APP_DIR / 'tmp').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=APP_DIR / 'tmp')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def lines(self, path):
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]

    def test_utf8_complete_sets_append_without_overwriting_and_newline_is_escaped(self):
        record = dict(input=dict(question='감육률 30% 이상\nTube 조회', selection=dict(exchanger_ids=[157])),
                      sql='SELECT *\nFROM analysis_tubes', parameters=[], error=None)
        first = usage.append_usage(record, directory=self.directory)
        before = first.read_bytes()
        second = usage.append_usage(dict(record, error=dict(message='잘못된 SQL입니다.')), directory=self.directory)
        self.assertEqual(first, second)
        self.assertTrue(first.read_bytes().startswith(before))
        self.assertEqual(len(self.lines(first)), 2)
        self.assertEqual(self.lines(first)[0]['input'], record['input'])
        self.assertEqual(self.lines(first)[0]['sql'], record['sql'])
        self.assertEqual(list(self.directory.iterdir()), [first])

    def test_month_rotation_uses_korean_time_and_never_replaces_previous_month(self):
        january = usage.append_usage(dict(event_id='one'), directory=self.directory,
            now=datetime(2026, 1, 31, 14, 59, 59, tzinfo=timezone.utc))
        february = usage.append_usage(dict(event_id='two'), directory=self.directory,
            now=datetime(2026, 1, 31, 15, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(january.name, 'text_to_sql_2026-01.txt')
        self.assertEqual(february.name, 'text_to_sql_2026-02.txt')
        self.assertEqual(len(self.lines(january)), 1)
        self.assertTrue(self.lines(february)[0]['logged_at'].startswith('2026-02-01T00:00:00'))
        with self.assertRaises(ValueError):
            usage.append_usage({}, directory=self.directory, now=datetime(2026, 1, 1))

    def test_simultaneous_threads_write_valid_noninterleaved_records(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            paths = list(executor.map(lambda i: usage.append_usage(dict(event_id=i, sql='가'*6000),
                directory=self.directory), range(80)))
        rows = self.lines(paths[0])
        self.assertEqual(len(rows), 80)
        self.assertEqual({row['event_id'] for row in rows}, set(range(80)))

    def test_multiple_processes_share_one_file_without_lost_or_interleaved_rows(self):
        code = """import sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd().parent))
from iris2.application.text_to_sql_usage_log import append_usage
for i in range(20):append_usage(dict(event_id=sys.argv[2]+'-'+str(i),sql='SELECT '*800),directory=sys.argv[1])
"""
        processes = [subprocess.Popen([sys.executable, '-c', code, str(self.directory), str(i)],
            cwd=APP_DIR, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(4)]
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, stderr.decode(errors='replace'))
        paths = list(self.directory.glob('*.txt'))
        self.assertEqual(len(paths), 1)
        rows = self.lines(paths[0])
        self.assertEqual(len(rows), 80)
        self.assertEqual(len({row['event_id'] for row in rows}), 80)

    def test_input_whitelist_never_records_tokens_and_invalid_numbers_are_json_safe(self):
        context = usage.input_context(dict(question='질문', exchanger_ids=[157], token='private-token',
            password='private-password', inspection_id=float('nan')))
        encoded = json.dumps(context, allow_nan=False)
        self.assertNotIn('private', encoded)
        self.assertEqual(context['selection']['exchanger_ids'], [157])
        self.assertEqual(context['selection']['inspection_id'], {'invalid_number': 'nan'})
        with self.assertRaises(ValueError):
            usage.append_usage({}, directory=APP_DIR.parent / 'outside-iris2')

    def test_partial_failed_append_preserves_previous_complete_records(self):
        path = usage.append_usage(dict(event_id='original'), directory=self.directory)
        before = path.read_bytes()
        original_write = os.write
        calls = 0

        def interrupted(fd, payload):
            nonlocal calls
            calls += 1
            if calls == 1:
                return original_write(fd, payload[:10])
            raise OSError('simulated disk failure')

        with patch.object(usage.os, 'write', side_effect=interrupted), self.assertRaises(OSError):
            usage.append_usage(dict(event_id='failed'), directory=self.directory)
        self.assertEqual(path.read_bytes(), before)
        usage.append_usage(dict(event_id='after-recovery'), directory=self.directory)
        self.assertEqual([row['event_id'] for row in self.lines(path)], ['original', 'after-recovery'])


class UsageRouteTests(TextToSqlWebTests):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(dir=APP_DIR / 'tmp')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.app.config['TEXT_TO_SQL_USAGE_LOG_DIR'] = self.directory

    def records(self):
        return [json.loads(line) for path in self.directory.glob('*.txt')
                for line in path.read_text(encoding='utf-8').splitlines()]

    def test_generate_and_execute_have_complete_context_and_same_usage_id(self):
        preview = self.generate()
        response = self.post('execute', dict(token=preview.json['token'], question='tampered', exchanger_id=999))
        self.assertEqual(response.status_code, 200)
        generated, executed = self.records()
        self.assertEqual([generated['event'], executed['event']], ['generate', 'execute'])
        self.assertEqual(generated['usage_id'], executed['usage_id'])
        self.assertNotEqual(generated['event_id'], executed['event_id'])
        self.assertEqual(preview.headers['X-Text-to-SQL-Usage-ID'], generated['usage_id'])
        for row in (generated, executed):
            self.assertEqual(row['actor']['username'], 'reader')
            self.assertEqual(row['input']['question'], '검사 결과 요약')
            self.assertEqual(row['input']['selection']['exchanger_id'], 151)
            self.assertEqual(row['scopes'][0]['equipment']['equipment_tag'], 'E-106')
            self.assertEqual(row['scopes'][0]['inspection']['iris_inspection_id'], 389)
            self.assertEqual(row['sql'], preview.json['proposal']['sql'])
            self.assertEqual(row['parameters'], preview.json['proposal']['parameters'])
            self.assertEqual(row['status'], 'success')
            self.assertIsNone(row['error'])
            self.assertNotIn(preview.json['token'], json.dumps(row))
        self.assertEqual(executed['result']['result_count'], 1)

    def test_failed_validation_preserves_rejected_generated_sql_and_error(self):
        self.worker.return_value = dict(sql='DELETE FROM equipment', parameters=[])
        response = self.generate()
        self.assertEqual(response.status_code, 400)
        row = self.records()[0]
        self.assertEqual(row['sql'], 'DELETE FROM equipment')
        self.assertEqual(row['input']['question'], '검사 결과 요약')
        self.assertEqual(row['error']['message'], response.json['error'])
        self.assertEqual(row['error']['type'], 'QueryRejected')
        self.execute.assert_not_called()

    def test_runtime_execution_error_has_input_sql_and_safe_message_without_credentials(self):
        preview = self.generate()
        self.execute.side_effect = RuntimeError('password=private-db-secret')
        response = self.post('execute', dict(token=preview.json['token']))
        self.assertEqual(response.status_code, 503)
        row = self.records()[-1]
        self.assertEqual(row['sql'], preview.json['proposal']['sql'])
        self.assertEqual(row['error']['type'], 'RuntimeError')
        self.assertEqual(row['error']['message'], response.json['error'])
        self.assertNotIn('private-db-secret', json.dumps(self.records()))

    def test_invalid_input_and_csrf_rejections_are_recorded_without_tokens(self):
        self.post('generate', dict(question='검사 요약', exchanger_id='bad-id'))
        response = self.client.post('/inspections/text-to-sql/generate',
            json=dict(question='검사 요약', exchanger_id=151, token='do-not-log'))
        self.assertEqual(response.status_code, 400)
        rows = self.records()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['input']['selection']['exchanger_id'], 'bad-id')
        self.assertTrue(all(row['status'] == 'error' for row in rows))
        self.assertNotIn('do-not-log', json.dumps(rows))

    def test_frequency_question_logs_full_scope_sql_and_execution_context(self):
        question = 'IRIS 검사를 가장 많이 수행한 열교환기를 보여줘'
        preview = self.post('generate', dict(question=question, unit_codes=['VCM2']))
        self.assertEqual(preview.status_code, 200)
        with patch('iris2.web.routes.text_to_sql.frequency.execute', return_value=dict(result_count=1, rows=[])):
            result = self.post('execute', dict(token=preview.json['token']))
        self.assertEqual(result.status_code, 200)
        rows = self.records()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row['input']['question'], question)
            self.assertEqual(row['input']['selection'], dict(unit_codes=['VCM2']))
            self.assertEqual(row['query_kind'], 'inspection_frequency')
            self.assertIn('COUNT(DISTINCT', row['sql'])
            self.assertEqual(row['scopes'][0]['equipment']['heat_exchanger_id'], 151)
            self.assertIn('start', row['period'])
        self.assertEqual(rows[0]['usage_id'], rows[1]['usage_id'])

    def test_multi_selection_and_excluded_equipment_are_logged_together(self):
        scopes = [dict(equipment=self.equipment, inspection=self.inspection)]
        excluded = [dict(heat_exchanger_id=152, reason='유효 검사 없음')]
        with patch('iris2.web.routes.text_to_sql.analysis.select_scopes', return_value=(scopes, excluded, {151, 152})):
            response = self.post('generate', dict(question='검사 요약', exchanger_ids=[151, 152]))
        self.assertEqual(response.status_code, 200)
        row = self.records()[0]
        self.assertEqual(row['input']['selection'], dict(exchanger_ids=[151, 152]))
        self.assertEqual(row['excluded'], excluded)
        self.assertEqual(row['scopes'], scopes)

    def test_expired_own_token_recovers_context_but_other_actor_token_does_not(self):
        from itsdangerous import URLSafeTimedSerializer
        preview = self.generate()
        serializer = URLSafeTimedSerializer(self.app.secret_key, salt='iris2-text-to-sql-v1')
        with patch('itsdangerous.timed.TimestampSigner.get_timestamp', return_value=1):
            expired = serializer.dumps(serializer.loads(preview.json['token']))
        self.assertEqual(self.post('execute', dict(token=expired)).status_code, 400)
        rows = self.records()
        self.assertEqual(rows[-1]['sql'], rows[0]['sql'])
        self.assertEqual(rows[-1]['usage_id'], rows[0]['usage_id'])
        self.assertEqual(self.post('execute', dict(token=preview.json['token']), self.make_client(2)).status_code, 403)
        self.assertIsNone(self.records()[-1]['sql'])

    def test_write_failure_is_visible_and_never_returns_an_unlogged_success(self):
        with patch('iris2.web.routes.text_to_sql.usage_log.append_usage', side_effect=OSError('disk full')):
            with self.assertLogs(self.app.logger, level='ERROR'):
                response = self.generate()
        self.assertEqual(response.status_code, 503)
        self.assertIn('사용 이력을 저장하지 못했습니다', response.json['error'])
        self.assertNotIn('token', response.json)


if __name__ == '__main__':
    unittest.main()
