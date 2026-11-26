"""Bounded, thread-safe login attempt limits for the single web process."""
from collections import OrderedDict, deque
import hashlib
import math
from threading import Lock
import time


class LoginGuard:
    def __init__(self, *, attempts=5, source_attempts=30, window=300, max_buckets=4096, clock=time.monotonic):
        if not 1 <= attempts <= source_attempts <= 1000 or not 1 <= window <= 3600 or max_buckets < 4:
            raise ValueError('Invalid login limit configuration')
        self.attempts, self.source_attempts, self.window = attempts, source_attempts, window
        self.max_buckets, self.clock = max_buckets, clock
        self.buckets, self.lock, self.sequence = OrderedDict(), Lock(), 0

    def begin(self, source, username):
        identity = hashlib.sha256(str(username or '').strip().lower()[:512].encode('utf-8')).hexdigest()
        keys = (('source', source), ('account_source', source, identity))
        now = self.clock()
        with self.lock:
            retries = []
            for key, limit in zip(keys, (self.source_attempts, self.attempts)):
                bucket = self.buckets.get(key, deque())
                while bucket and bucket[0][0] <= now - self.window:
                    bucket.popleft()
                if len(bucket) >= limit:
                    retries.append(max(1, math.ceil(bucket[0][0] + self.window - now)))
            if retries:
                return None, max(retries)
            self.sequence += 1
            for key in keys:
                if key not in self.buckets:
                    while len(self.buckets) >= self.max_buckets:
                        self.buckets.popitem(last=False)
                    self.buckets[key] = deque()
                self.buckets[key].append((now, self.sequence))
                self.buckets.move_to_end(key)
            return (self.sequence, keys), 0

    def finish(self, ticket, *, success):
        if not success:
            return
        sequence, keys = ticket
        with self.lock:
            for key in keys:
                if key in self.buckets:
                    self.buckets[key] = deque(item for item in self.buckets[key] if item[1] != sequence)
                    if not self.buckets[key]:
                        del self.buckets[key]
