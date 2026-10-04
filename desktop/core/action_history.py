"""Durable desktop action descriptions, with honest session-only undo status."""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path


def history_path() -> Path:
    return Path(os.getenv('MICA_ACTION_HISTORY_PATH',
        str(Path(__file__).resolve().parents[2] / '.mica-data' / 'action-history.sqlite3')))


def _connect():
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.execute('CREATE TABLE IF NOT EXISTS action_history '
                 '(id TEXT PRIMARY KEY,label TEXT NOT NULL,created_at TEXT NOT NULL,status TEXT NOT NULL)')
    return conn


def record(label: str) -> str:
    identifier = uuid.uuid4().hex
    conn = _connect()
    try:
        conn.execute('INSERT INTO action_history VALUES (?,?,?,?)',
                     (identifier, label, datetime.now(UTC).isoformat(), 'changed'))
        conn.commit()
    finally:
        conn.close()
    return identifier


def finish(identifier: str, status: str):
    if status not in {'undone', 'undo_failed'}:
        raise ValueError('Invalid history status')
    conn = _connect()
    try:
        conn.execute('UPDATE action_history SET status=? WHERE id=?', (status, identifier))
        conn.commit()
    finally:
        conn.close()


def entries(limit: int = 200) -> list[dict]:
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(
            'SELECT * FROM action_history ORDER BY created_at DESC LIMIT ?', (max(1, min(limit, 500)),))]
    finally:
        conn.close()
