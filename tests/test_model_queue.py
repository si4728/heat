from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2.application.model_queue import ModelQueue, QueueFull


class ModelQueueTests(unittest.TestCase):
    def test_fifo_capacity_owner_and_no_parallel_inference(self):
        queue = ModelQueue()
        entered, release = threading.Event(), threading.Event()
        order, active = [], []

        def task(number):
            def run():
                self.assertFalse(active)
                active.append(number)
                order.append(number)
                if number == 1:
                    entered.set()
                    self.assertTrue(release.wait(5))
                active.pop()
                return {'number': number}, 200
            return run

        keys = [queue.submit(1, task(1))]
        try:
            self.assertTrue(entered.wait(3))
            keys.extend(queue.submit(i, task(i)) for i in (2, 3, 4))
            for position, key in enumerate(keys[1:], 1):
                self.assertEqual(queue.status(key, position + 1)['position'], position)
            self.assertIsNone(queue.status(keys[1], 1))
            with self.assertRaises(PermissionError):
                queue.wait(keys[1], 1)
            with self.assertRaises(QueueFull):
                queue.submit(5, task(5))
            self.assertEqual(order, [1])
        finally:
            release.set()
        for number, key in enumerate(keys, 1):
            self.assertEqual(queue.wait(key, number)['result'], {'number': number})
        self.assertEqual(order, [1, 2, 3, 4])
        self.assertEqual(queue.wait(queue.submit(5, task(5)), 5)['http_status'], 200)

    def test_failure_does_not_stop_next_job_or_expose_exception(self):
        queue = ModelQueue()
        def fail():
            raise RuntimeError('private-value')
        failed = queue.wait(queue.submit(1, fail), 1)
        self.assertEqual(failed['state'], 'failed')
        self.assertNotIn('private-value', str(failed))
        self.assertEqual(queue.wait(queue.submit(2, lambda: ({'ok': True}, 200)), 2)['state'], 'succeeded')

    def test_finished_results_are_pruned_without_removing_active_jobs(self):
        queue = ModelQueue(history_limit=1)
        first = queue.submit(1, lambda: ({}, 200))
        queue.wait(first, 1)
        second = queue.submit(1, lambda: ({}, 200))
        queue.wait(second, 1)
        self.assertIsNone(queue.status(first, 1))
        self.assertIsNotNone(queue.status(second, 1))


if __name__ == '__main__':
    unittest.main()
