"""One process-local FIFO for local model inference (one active, three waiting)."""
from __future__ import annotations

from collections import OrderedDict, deque
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4


class QueueFull(Exception):
    pass


class ModelQueue:
    def __init__(self, *, max_waiting=3, retention_seconds=900, history_limit=128):
        self.max_waiting = max_waiting
        self.retention_seconds = retention_seconds
        self.history_limit = history_limit
        self._lock = Lock()
        self._jobs = OrderedDict()
        self._pending = deque()
        self._active = None

    def _prune(self):
        completed = [key for key, job in self._jobs.items() if job['done'].is_set()]
        now = monotonic()
        for index, key in enumerate(completed):
            if (now - self._jobs[key]['finished'] > self.retention_seconds
                    or index < len(completed) - self.history_limit):
                del self._jobs[key]

    def submit(self, owner, task, *, kind=None):
        with self._lock:
            self._prune()
            if self._active is not None and len(self._pending) >= self.max_waiting:
                raise QueueFull
            key = uuid4().hex
            self._jobs[key] = dict(owner=owner, task=task, kind=kind, state='queued', done=Event())
            if self._active is None:
                self._active = key
                self._jobs[key]['state'] = 'running'
                Thread(target=self._run, name='text-sql-model-queue', daemon=True).start()
            else:
                self._pending.append(key)
            return key

    def _run(self):
        while True:
            with self._lock:
                key = self._active
                job = self._jobs[key]
                task = job.pop('task')
            try:
                response = task()
                payload, status = response[:2]
                usage_id = response[2] if len(response) > 2 else None
            except Exception:
                payload, status = {'error': '모델 요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요.'}, 503
                usage_id = None
            with self._lock:
                job.update(state='succeeded' if status < 400 else 'failed',
                           payload=payload, http_status=status, usage_id=usage_id, finished=monotonic())
                job['done'].set()
                self._active = self._pending.popleft() if self._pending else None
                if self._active is None:
                    return
                self._jobs[self._active]['state'] = 'running'

    def status(self, key, owner):
        with self._lock:
            self._prune()
            job = self._jobs.get(key)
            if job is None or job['owner'] != owner:
                return None
            state = job['state']
            position = list(self._pending).index(key) + 1 if state == 'queued' else 0
            message = (f'앞선 요청이 끝날 때까지 기다려 주세요. 현재 대기 {position}번입니다. 차례가 되면 자동으로 진행합니다.'
                       if state == 'queued' else '차례가 되어 모델이 요청을 처리하고 있습니다.'
                       if state == 'running' else '모델 요청 처리가 완료되었습니다.')
            result = dict(job_id=key, kind=job['kind'], state=state, position=position, message=message)
            if job['done'].is_set():
                result.update(result=job['payload'], http_status=job['http_status'], usage_id=job['usage_id'])
            return result

    def wait(self, key, owner):
        # Compatibility for synchronous API callers; the browser uses polling.
        with self._lock:
            job = self._jobs[key]
            if job['owner'] != owner:
                raise PermissionError('본인이 접수한 요청만 조회할 수 있습니다.')
            done = job['done']
        done.wait()
        # Keep the reference even if a later request prunes the completed history.
        with self._lock:
            return dict(state=job['state'], result=job['payload'], http_status=job['http_status'], usage_id=job['usage_id'])
