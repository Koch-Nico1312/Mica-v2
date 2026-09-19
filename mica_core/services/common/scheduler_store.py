from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCHEDULABLE_ACTIONS = {"brain.reindex", "learning.monitor", "reminder.create", "reminder.dispatch", "message.send", "server.scan"}
EXTERNAL_DELIVERY_ACTIONS = {"reminder.dispatch", "message.send"}
MAX_RECURRENCE_SECONDS = 366 * 24 * 60 * 60
MAX_RECURRENCE_OCCURRENCES = 1000


class ScheduleStore:
    """Persistent, local-only schedule queue.

    A due external delivery is *not* sent by this class.  It is moved to
    ``awaiting_approval`` so every message still needs a fresh confirmation.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schedules ("
                "id TEXT PRIMARY KEY, name TEXT NOT NULL, run_at TEXT NOT NULL, "
                "action TEXT NOT NULL, params TEXT NOT NULL, status TEXT NOT NULL, "
                "created_at TEXT NOT NULL, dispatched_at TEXT, recurrence TEXT NOT NULL DEFAULT '{}', "
                "series_id TEXT)"
            )
            self._ensure_column(conn, "schedules", "recurrence", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(conn, "schedules", "series_id", "TEXT")
            self._ensure_column(conn, "schedules", "task_id", "TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_schedules_due ON schedules(status, run_at)")

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    @staticmethod
    def _parse_time(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError) as error:
            raise ValueError("run_at must be an ISO-8601 timestamp") from error
        if parsed.tzinfo is None:
            raise ValueError("run_at must include a timezone offset")
        return parsed.astimezone(UTC)

    @staticmethod
    def _normalise_recurrence(recurrence: dict[str, Any] | None) -> dict[str, int]:
        """Use a finite interval model instead of an unbounded cron grammar."""
        if recurrence is None:
            return {}
        if not isinstance(recurrence, dict) or set(recurrence) != {"every_seconds", "occurrences"}:
            raise ValueError("recurrence must contain only every_seconds and occurrences")
        every_seconds, occurrences = recurrence.get("every_seconds"), recurrence.get("occurrences")
        if isinstance(every_seconds, bool) or not isinstance(every_seconds, int) or not 60 <= every_seconds <= MAX_RECURRENCE_SECONDS:
            raise ValueError(f"recurrence.every_seconds must be between 60 and {MAX_RECURRENCE_SECONDS}")
        if isinstance(occurrences, bool) or not isinstance(occurrences, int) or not 2 <= occurrences <= MAX_RECURRENCE_OCCURRENCES:
            raise ValueError(f"recurrence.occurrences must be between 2 and {MAX_RECURRENCE_OCCURRENCES}")
        return {"every_seconds": every_seconds, "occurrences": occurrences}

    @staticmethod
    def _row_to_schedule(row: tuple[Any, ...]) -> dict[str, Any]:
        recurrence = json.loads(row[8] or "{}")
        return {
            "id": row[0], "name": row[1], "run_at": row[2], "action": row[3],
            "params": json.loads(row[4]), "status": row[5], "created_at": row[6],
            "dispatched_at": row[7], "recurrence": recurrence or None, "series_id": row[9],
            "task_id": row[10],
        }

    def create(
        self, name: str, run_at: str, action: str, params: dict[str, Any] | None = None,
        recurrence: dict[str, Any] | None = None, task_id: str | None = None,
    ) -> dict[str, Any]:
        if action not in SCHEDULABLE_ACTIONS:
            raise ValueError("Action is not schedulable")
        when = self._parse_time(run_at)
        if when <= datetime.now(UTC):
            raise ValueError("run_at must be in the future")
        recurrence_value = self._normalise_recurrence(recurrence)
        schedule_id = uuid.uuid4().hex
        schedule = {
            "id": schedule_id,
            "name": (name or "Geplante Aufgabe").strip()[:160],
            "run_at": when.isoformat(),
            "action": action,
            "params": params or {},
            "status": "pending",
            "created_at": datetime.now(UTC).isoformat(),
            "dispatched_at": None,
            "recurrence": recurrence_value or None,
            "series_id": schedule_id if recurrence_value else None,
            "task_id": task_id,
        }
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO schedules(id, name, run_at, action, params, status, created_at, dispatched_at, recurrence, series_id, task_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (schedule["id"], schedule["name"], schedule["run_at"], schedule["action"],
                 json.dumps(schedule["params"], ensure_ascii=False, sort_keys=True), schedule["status"],
                 schedule["created_at"], None,
                 json.dumps(recurrence_value, ensure_ascii=False, sort_keys=True), schedule["series_id"], schedule["task_id"]),
            )
            conn.execute("COMMIT")
        return schedule

    def list(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        query = "SELECT id, name, run_at, action, params, status, created_at, dispatched_at, recurrence, series_id, task_id FROM schedules"
        values: tuple[Any, ...] = ()
        if status:
            query += " WHERE status = ?"
            values = (status,)
        query += " ORDER BY run_at ASC LIMIT ?"
        with self._connect() as conn:
            rows = conn.execute(query, (*values, limit)).fetchall()
        return [self._row_to_schedule(row) for row in rows]

    def cancel(self, schedule_id: str) -> bool:
        with self._connect() as conn:
            result = conn.execute("UPDATE schedules SET status = 'cancelled' WHERE id = ? AND status IN ('pending', 'awaiting_approval')", (schedule_id,))
        return result.rowcount == 1

    def get(self, schedule_id: str) -> dict[str, Any] | None:
        return next((entry for entry in self.list(limit=500) if entry["id"] == schedule_id), None)

    def finish_due(self, schedule_id: str, success: bool) -> bool:
        """Record completion of a local due action exactly once."""
        with self._connect() as conn:
            result = conn.execute(
                "UPDATE schedules SET status = ? WHERE id = ? AND status = 'due'",
                ("completed" if success else "failed", schedule_id),
            )
        return result.rowcount == 1

    def finish_delivery(self, schedule_id: str, success: bool) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                "UPDATE schedules SET status = ? WHERE id = ? AND status = 'awaiting_approval'",
                ("completed" if success else "failed", schedule_id),
            )
        return result.rowcount == 1

    def stop_all_pending(self) -> int:
        """Cancel undelivered work for the persistent emergency-stop action."""
        with self._connect() as conn:
            result = conn.execute(
                "UPDATE schedules SET status = 'cancelled' WHERE status IN ('pending', 'awaiting_approval')"
            )
        return result.rowcount

    def claim_due(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Atomically claim due schedules once, never duplicate a delivery."""
        now = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT id, name, run_at, action, params, status, created_at, dispatched_at, recurrence, series_id, task_id "
                "FROM schedules WHERE status = 'pending' AND run_at <= ? ORDER BY run_at ASC", (now,)
            ).fetchall()
            claimed: list[dict[str, Any]] = []
            for row in rows:
                next_status = "awaiting_approval" if row[3] in EXTERNAL_DELIVERY_ACTIONS else "due"
                result = conn.execute(
                    "UPDATE schedules SET status = ?, dispatched_at = ? WHERE id = ? AND status = 'pending'",
                    (next_status, now, row[0]),
                )
                if result.rowcount:
                    recurrence = json.loads(row[8] or "{}")
                    claimed.append({
                        "id": row[0], "name": row[1], "run_at": row[2], "action": row[3],
                        "params": json.loads(row[4]), "status": next_status, "created_at": row[6],
                        "dispatched_at": now, "recurrence": recurrence or None, "series_id": row[9], "task_id": row[10],
                    })
                    if recurrence.get("occurrences", 0) > 1:
                        next_run = self._parse_time(row[2]).timestamp() + recurrence["every_seconds"]
                        next_recurrence = {"every_seconds": recurrence["every_seconds"], "occurrences": recurrence["occurrences"] - 1}
                        conn.execute(
                            "INSERT INTO schedules(id, name, run_at, action, params, status, created_at, dispatched_at, recurrence, series_id, task_id) "
                            "VALUES (?, ?, ?, ?, ?, 'pending', ?, NULL, ?, ?, ?)",
                            (uuid.uuid4().hex, row[1], datetime.fromtimestamp(next_run, UTC).isoformat(), row[3], row[4],
                             datetime.now(UTC).isoformat(), json.dumps(next_recurrence, ensure_ascii=False, sort_keys=True),
                             row[9] or row[0], row[10]),
                        )
            conn.execute("COMMIT")
        return claimed
