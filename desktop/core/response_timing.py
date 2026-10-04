"""Bounded, content-free desktop response timings for the current process."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import threading
import time


class TimingHistory:
    def __init__(self, limit=100, clock=time.monotonic):
        self.clock = clock
        self._records = deque(maxlen=limit)
        self._lock = threading.Lock()

    def begin(self, kind):
        if kind not in {'text', 'voice'}:
            raise ValueError('Unknown timing kind')
        return ResponseTiming(self, kind)

    def snapshot(self):
        with self._lock:
            return [dict(record) for record in self._records]

    def clear(self):
        with self._lock:
            self._records.clear()

    def _append(self, record):
        with self._lock:
            self._records.append(record)


class ResponseTiming:
    def __init__(self, history, kind):
        self.history, self.kind = history, kind
        self.started = history.clock()
        self._marks = {}
        self._finished = False
        self._lock = threading.Lock()

    def mark(self, phase):
        if phase not in {'connected', 'submitted', 'transcript', 'reply', 'audio'}:
            raise ValueError('Unknown timing phase')
        with self._lock:
            if not self._finished:
                self._marks.setdefault(phase, self.history.clock())

    def finish(self, outcome):
        if outcome not in {'success', 'failed', 'cancelled'}:
            raise ValueError('Unknown timing outcome')
        with self._lock:
            if self._finished:
                return
            self._finished = True
            ended = self.history.clock()
            record = {'kind': self.kind, 'outcome': outcome,
                      'created_at': datetime.now(timezone.utc).isoformat(),
                      'total_ms': round(max(0, ended - self.started) * 1000)}
            if 'connected' in self._marks:
                record['connect_ms'] = round(max(0, self._marks['connected'] - self.started) * 1000)
            origin = self.started if self.kind == 'text' else self._marks.get('submitted')
            if origin is not None:
                for phase in ('transcript', 'reply', 'audio'):
                    if phase in self._marks and self._marks[phase] >= origin:
                        record[phase + '_ms'] = round((self._marks[phase] - origin) * 1000)
            self.history._append(record)


RESPONSE_TIMINGS = TimingHistory()
