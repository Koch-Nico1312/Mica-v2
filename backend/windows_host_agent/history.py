"""Durable host receipts and bounded, state-checked file compensation.

Only typed data is persisted. No callbacks or executable text cross processes.
Unsupported actions remain visible, with no advertised compensation.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from pathlib import Path

from mica_shared.file_paths import file_action_paths

LIMIT = 1_000_000


def _path():
    return Path(os.getenv('MICA_HOST_HISTORY_PATH', str(Path(os.getenv('ProgramData', 'C:/ProgramData')) / 'Mica/action-history.sqlite3')))


@contextmanager
def _db():
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, action TEXT, operation TEXT, status TEXT, created_at TEXT, paths TEXT, compensation TEXT, undo_status TEXT)')
        with conn:
            yield conn
    finally:
        conn.close()


def action_guard(action):
    if action != 'file_controller':
        return nullcontext()
    from backend.services.common.storage_lock import StorageLease
    return StorageLease(_path().parent / '.host-file-actions', exclusive=True, timeout=15)


def _safe(path: Path) -> Path:
    # Reject links/reparse points before resolving: a changed junction must not
    # retarget a historical operation into a different directory.
    path = path.absolute()
    for node in (path, *path.parents):
        if node.is_symlink() or (hasattr(node, 'is_junction') and node.is_junction()):
            raise ValueError('Verknüpfte Pfade können nicht rückgängig gemacht werden.')
    resolved = path.resolve()
    roots = [Path(x).expanduser().resolve() for x in os.getenv('MICA_WINDOWS_ALLOWED_ROOTS', '').split(os.pathsep) if x.strip()]
    if not any(resolved != root and resolved.is_relative_to(root) for root in roots):
        raise ValueError('Dateipfad liegt außerhalb der freigegebenen Verzeichnisse.')
    return resolved


def _state(path: Path):
    path = _safe(path)
    if not path.exists():
        return {'kind': 'missing'}
    if path.is_dir():
        return {'kind': 'empty_dir'} if not any(path.iterdir()) else None
    if not path.is_file() or path.stat().st_size > LIMIT:
        return None
    data = path.read_bytes()
    if len(data) > LIMIT:
        return None
    return {'kind': 'file', 'sha256': hashlib.sha256(data).hexdigest(), 'data': base64.b64encode(data).decode('ascii')}


def prepare(action, params):
    operation = str(params.get('action', params.get('mode', ''))).strip().lower()
    paths, before = [str(params[k]) for k in ('path', 'file_path', 'destination', 'output_path') if params.get(k)], None
    if action == 'file_controller':
        try:
            paths = [str(path.absolute()) for path in file_action_paths(params)]
        except (ValueError, OSError):
            pass
    if action == 'file_controller' and operation in {'create_file', 'create_folder', 'write', 'move', 'rename', 'copy'}:
        try:
            paths = [str(_safe(path)) for path in file_action_paths(params)]
            before = [_state(Path(p)) for p in paths]
            # Never promise reversal of overwrite-moves, directory trees or
            # large files. Existing file writes have a bounded exact snapshot.
            if any(s is None for s in before) or (len(paths) == 2 and before[1]['kind'] != 'missing'):
                before = None
        except (OSError, ValueError):
            before = None
    identifier = uuid.uuid4().hex
    with _db() as conn:
        conn.execute('INSERT INTO receipts VALUES (?,?,?,?,?,?,?,?)',
                     (identifier, action, operation, 'running', datetime.now(UTC).isoformat(), json.dumps(paths), None, 'unavailable'))
    return identifier, paths, before


def finish(receipt, succeeded):
    identifier, paths, before = receipt
    compensation = None
    if succeeded and before is not None:
        try:
            after = [_state(Path(p)) for p in paths]
            if all(s is not None for s in after) and after != before:
                compensation = {'paths': paths, 'before': before, 'after': after}
        except (ValueError, OSError):
            pass
    with _db() as conn:
        conn.execute('UPDATE receipts SET status=?,compensation=?,undo_status=? WHERE id=?',
                     ('completed' if succeeded else 'uncertain', json.dumps(compensation) if compensation else None,
                      'available' if compensation else 'unavailable', identifier))
    return identifier


def list_receipts(limit=200):
    with _db() as conn:
        rows = conn.execute('SELECT id,action,operation,status,created_at,paths,undo_status FROM receipts ORDER BY created_at DESC LIMIT ?', (max(1, min(limit, 500)),)).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item['paths'] = json.loads(item['paths'])
        item['undo_available'] = item['status'] == 'completed' and item['undo_status'] == 'available'
        items.append(item)
    return items


def undo(identifier):
    with action_guard('file_controller'):
        return _undo_locked(identifier)


def _undo_locked(identifier):
    with _db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM receipts WHERE id=?', (identifier,)).fetchone()
        if not row or row['status'] != 'completed' or row['undo_status'] != 'available':
            raise ValueError('Diese Änderung ist nicht rückgängig machbar.')
        data = json.loads(row['compensation'])
        if [_state(Path(p)) for p in data['paths']] != data['after']:
            raise ValueError('Dateien wurden inzwischen verändert. Rückgängig wurde nicht ausgeführt.')
        for p, before in zip(data['paths'], data['before']):
            if before['kind'] != 'missing' and not _safe(Path(p)).parent.is_dir():
                raise ValueError('Das ursprüngliche Verzeichnis fehlt. Rückgängig wurde nicht ausgeführt.')
        conn.execute("UPDATE receipts SET undo_status='running' WHERE id=?", (identifier,))
    # A crash leaves running, never an automatically repeated compensation.
    try:
        # Restore the original before removing a moved destination. A failed
        # restore must never remove the user's last filesystem copy.
        for p, before, after in zip(data['paths'], data['before'], data['after']):
            if before == after:
                continue
            path = _safe(Path(p))
            if before['kind'] == 'file':
                _restore_file(path, base64.b64decode(before['data'], validate=True), after)
            elif before['kind'] == 'empty_dir':
                path.mkdir(exist_ok=True)
        for p, before in reversed(list(zip(data['paths'], data['before']))):
            path = _safe(Path(p))
            if before['kind'] == 'missing' and path.exists():
                path.rmdir() if path.is_dir() else path.unlink()
    except Exception:
        with _db() as conn:
            conn.execute("UPDATE receipts SET undo_status='uncertain' WHERE id=?", (identifier,))
        raise
    with _db() as conn:
        conn.execute("UPDATE receipts SET undo_status='undone' WHERE id=?", (identifier,))
    return {'change_id': identifier, 'status': 'undone', 'paths': data['paths']}


def _restore_file(path: Path, content: bytes, expected: dict):
    temporary = path.with_name('.mica-undo-' + uuid.uuid4().hex + '.tmp')
    created = False
    try:
        with temporary.open('xb') as stream:
            created = True
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if _state(path) != expected:
            raise ValueError('Datei wurde während Rückgängig verändert; Änderung wird nicht überschrieben.')
        os.replace(temporary, path)
    finally:
        if created:
            temporary.unlink(missing_ok=True)
