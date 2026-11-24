from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from itsdangerous import URLSafeTimedSerializer
import test_text_to_sql_web as existing


class TextToSqlQueueTests(unittest.TestCase):
    setUp = existing.TextToSqlWebTests.setUp
    start_patch = existing.TextToSqlWebTests.start_patch
    make_client = existing.TextToSqlWebTests.make_client
    post = existing.TextToSqlWebTests.post

    def submit(self, client=None):
        return self.post('generate', dict(exchanger_id=151, inspection_id=389,
            question='검사 결과 요약', async_model=True), client)

    def block_first(self):
        entered, release = threading.Event(), threading.Event()
        def worker(question):
            entered.set()
            if not release.wait(10):
                raise AssertionError('test release timeout')
            return existing.SUMMARY
        self.worker.side_effect = worker
        self.addCleanup(release.set)
        response = self.submit()
        self.assertEqual(response.status_code, 202)
        self.assertTrue(entered.wait(3))
        return release, response.json['model_job']['job_id']

    def test_four_users_fifo_then_full_rejected_and_results_private(self):
        release, first = self.block_first()
        jobs = [(1, first)]
        try:
            for uid in (2, 3, 4):
                client = self.make_client(uid)
                response = self.submit(client)
                self.assertEqual(response.status_code, 202)
                state = response.json['model_job']
                self.assertEqual(state['position'], uid - 1)
                self.assertIn('기다려', state['message'])
                self.assertEqual(self.client.get(state['status_url']).status_code, 404)
                self.assertEqual(client.get(state['status_url']).headers['Cache-Control'], 'no-store')
                jobs.append((uid, state['job_id']))
            rejected = self.submit(self.make_client(5))
            self.assertEqual(rejected.status_code, 429)
            self.assertIn('나중에', rejected.json['error'])
            self.worker.assert_called_once()
        finally:
            release.set()
        queue = self.app.extensions['text_to_sql_model_queue']
        for uid, key in jobs:
            completed = queue.wait(key, uid)
            self.assertEqual(completed['http_status'], 200, completed)
            result = self.post('execute', {'token': completed['result']['token']}, self.make_client(uid))
            self.assertEqual(result.status_code, 200)
        self.assertEqual(self.worker.call_count, 4)

    def test_summary_and_sql_share_queue_and_permission_revoked_while_waiting(self):
        for key in ('EXCHANGERS', 'REMAINING_LIFE'):
            self.profile['permissions'][key] = dict(can_view=True, can_edit=False)
        release, first = self.block_first()
        signer = URLSafeTimedSerializer(self.app.secret_key, salt='iris2-text-to-sql-v1')
        token = signer.dumps(dict(actor=2, kind='result_commentary', ids=[151], facts={}))
        with patch.object(existing.routes.commentary, 'generate', return_value={'text': 'summary'}) as summary:
            try:
                response = self.post('summarize', dict(token=token, async_model=True), self.make_client(2))
                self.assertEqual(response.status_code, 202, response.json)
                self.assertEqual(response.json['model_job']['position'], 1)
                summary.assert_not_called()
                self.profile['permissions'].pop('EXCHANGERS')
            finally:
                release.set()
            queue = self.app.extensions['text_to_sql_model_queue']
            queue.wait(first, 1)
            result = queue.wait(response.json['model_job']['job_id'], 2)
            self.assertEqual(result['http_status'], 403)
            summary.assert_not_called()
            self.assertEqual(self.make_client(2).get(response.json['model_job']['status_url']).status_code, 403)

    def test_polling_requires_login_and_permissions(self):
        self.assertIn(self.app.test_client().get('/inspections/text-to-sql/model-jobs/missing').status_code, (302, 403))
        self.profile['permissions'].pop('TEXT_TO_SQL')
        self.assertEqual(self.client.get('/inspections/text-to-sql/model-jobs/missing').status_code, 403)


if __name__ == '__main__':
    unittest.main()
