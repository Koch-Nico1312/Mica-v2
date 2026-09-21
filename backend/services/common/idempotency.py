from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class IdempotencyConflict(ValueError):
    pass


class IdempotencyStore:
    """Persist exact execution results so retries cannot duplicate side effects."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS executions ("
                "key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, status TEXT NOT NULL, result TEXT)"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def fingerprint(action: str, params: dict[str, Any]) -> str:
        canonical = json.dumps(
            {"action": action, "params": params}, ensure_ascii=False,
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def begin(self, key: str, action: str, params: dict[str, Any]) -> dict[str, Any] | None:
        fingerprint = self.fingerprint(action, params)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT fingerprint, status, result FROM executions WHERE key = ?", (key,),
            ).fetchone()
            if row:
                connection.execute("COMMIT")
                if row[0] != fingerprint:
                    raise IdempotencyConflict("Idempotency key was already used for different parameters")
                if row[1] == "completed" and row[2]:
                    return json.loads(row[2])
                raise IdempotencyConflict("An execution with this idempotency key is already in progress")
            connection.execute(
                "INSERT INTO executions(key, fingerprint, status) VALUES (?, ?, 'started')",
                (key, fingerprint),
            )
            connection.execute("COMMIT")
        return None

    def complete(self, key: str, result: dict[str, Any]) -> None:
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False)
        with self._connect() as connection:
            connection.execute(
                "UPDATE executions SET status = 'completed', result = ? WHERE key = ? AND status = 'started'",
                (encoded, key),
            )

    def abandon(self, key: str) -> None:
        """Allow a retry only when dispatch is known not to have happened."""
        with self._connect() as connection:
            connection.execute("DELETE FROM executions WHERE key = ? AND status = 'started'", (key,))
