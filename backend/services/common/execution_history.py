"""Durable API dispatch journal. Uncertain effects are never replayed here."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .idempotency import IdempotencyConflict, IdempotencyStore


class ExecutionHistory:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute("""CREATE TABLE IF NOT EXISTS execution_history (
                key TEXT PRIMARY KEY, task_id TEXT NOT NULL, action TEXT NOT NULL,
                fingerprint TEXT NOT NULL, status TEXT NOT NULL, result TEXT,
                detail TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL)""")
            if 'params' not in {row[1] for row in conn.execute('PRAGMA table_info(execution_history)')}:
                conn.execute('ALTER TABLE execution_history ADD COLUMN params TEXT')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_execution_history_created ON execution_history(created_at)')
            conn.execute('COMMIT')

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def begin(self, key: str, task_id: str, action: str, params: dict) -> dict | None:
        fingerprint = IdempotencyStore.fingerprint(action, params)
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM execution_history WHERE key=?', (key,)).fetchone()
            if row:
                if row['fingerprint'] != fingerprint or row['task_id'] != task_id:
                    conn.execute('ROLLBACK')
                    raise IdempotencyConflict('Execution key belongs to a different task or parameters')
                if row['result'] and row['status'] == 'succeeded':
                    conn.execute('ROLLBACK')
                    return json.loads(row['result'])
                if row['status'] in {'not_dispatched', 'approval_required'}:
                    conn.execute("UPDATE execution_history SET status='running',result=NULL,detail='',updated_at=? WHERE key=?", (now, key))
                    conn.execute('COMMIT')
                    return None
                conn.execute('ROLLBACK')
                raise IdempotencyConflict('Execution already recorded; inspect its status before continuing')
            conn.execute(
                'INSERT INTO execution_history(key,task_id,action,fingerprint,status,created_at,updated_at,params) '
                "VALUES(?,?,?,?,'running',?,?,?)", (key, task_id, action, fingerprint, now, now, json.dumps(params, ensure_ascii=False)),
            )
            conn.execute('COMMIT')
        return None

    def finish(self, key: str, status: str, result: dict | None = None, detail: str = '') -> None:
        if status not in {'succeeded', 'not_dispatched', 'approval_required', 'uncertain', 'failed'}:
            raise ValueError('Unsupported execution status')
        with self._connect() as conn:
            conn.execute(
                "UPDATE execution_history SET status=?,result=?,detail=?,updated_at=? WHERE key=? AND status='running'",
                (status, json.dumps(result, ensure_ascii=False) if result else None,
                 detail[:1000], datetime.now(UTC).isoformat(), key),
            )

    def list(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute('SELECT * FROM execution_history ORDER BY created_at DESC LIMIT ?',
                                (max(1, min(limit, 500)),)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item.pop('fingerprint')
            item['result'] = json.loads(item['result']) if item['result'] else None
            item['params'] = json.loads(item['params']) if item['params'] is not None else None
            # Running may outlive an API process. It stays claimed, even after
            # restart; a timeout is never evidence that dispatch did not happen.
            item['can_retry'] = item['status'] in {'not_dispatched', 'approval_required'}
            item['needs_reconciliation'] = item['status'] in {'running', 'uncertain'}
            items.append(item)
        return items

    def retry_request(self, key: str) -> dict:
        with self._connect() as conn:
            row = conn.execute('SELECT * FROM execution_history WHERE key=?', (key,)).fetchone()
        if not row or row['params'] is None or row['status'] not in {'not_dispatched', 'approval_required'}:
            raise IdempotencyConflict('Only a known undispatched execution with saved parameters can resume')
        return {'task_id': row['task_id'], 'action': row['action'], 'params': json.loads(row['params']), 'idempotency_key': key}

    def reconcile(self, key: str, fingerprint: str, result: dict) -> bool:
        """Resolve an uncertain outcome only from an exact durable broker result."""
        if result.get('status') != 'succeeded':
            raise ValueError('Only a verified successful result may resolve an unknown execution')
        with self._connect() as conn:
            return bool(conn.execute(
                "UPDATE execution_history SET status='succeeded',result=?,detail='',updated_at=? "
                "WHERE key=? AND fingerprint=? AND status IN ('running','uncertain')",
                (json.dumps(result, ensure_ascii=False), datetime.now(UTC).isoformat(), key, fingerprint),
            ).rowcount)
