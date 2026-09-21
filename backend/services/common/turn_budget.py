"""Persistent hard limits for Phase-0 planning and execution turns."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator


MAX_TOOL_CALLS = 5
MAX_PLANNING_PASSES = 3
MAX_TURN_SECONDS = 120


class TurnBudgetExceeded(RuntimeError):
    pass


class TurnBudget:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS turns ("
                "turn_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, planning_passes INTEGER NOT NULL, "
                "tool_calls INTEGER NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY, turn_id TEXT NOT NULL)"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=5000")
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    def register_plan(self, turn_id: str, task_id: str) -> None:
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT started_at, planning_passes FROM turns WHERE turn_id = ?", (turn_id,),
            ).fetchone()
            if row:
                started = datetime.fromisoformat(row[0])
                if (now - started).total_seconds() > MAX_TURN_SECONDS:
                    connection.execute("ROLLBACK")
                    raise TurnBudgetExceeded("Turn exceeded 120 seconds")
                if int(row[1]) >= MAX_PLANNING_PASSES:
                    connection.execute("ROLLBACK")
                    raise TurnBudgetExceeded("Turn exceeded three planning passes")
                connection.execute(
                    "UPDATE turns SET planning_passes = planning_passes + 1 WHERE turn_id = ?", (turn_id,),
                )
            else:
                connection.execute(
                    "INSERT INTO turns VALUES (?, ?, 1, 0)", (turn_id, now.isoformat()),
                )
            connection.execute(
                "INSERT INTO tasks(task_id, turn_id) VALUES (?, ?) "
                "ON CONFLICT(task_id) DO UPDATE SET turn_id=excluded.turn_id", (task_id, turn_id),
            )
            connection.execute("COMMIT")

    def claim_tool_call(self, task_id: str, fallback_turn_id: str | None = None) -> str:
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT turns.turn_id, turns.started_at, turns.tool_calls FROM tasks "
                "JOIN turns ON turns.turn_id=tasks.turn_id WHERE tasks.task_id=?", (task_id,),
            ).fetchone()
            if not row:
                turn_id = fallback_turn_id or task_id
                existing_turn = connection.execute(
                    "SELECT started_at, tool_calls FROM turns WHERE turn_id=?", (turn_id,),
                ).fetchone()
                if existing_turn:
                    row = (turn_id, existing_turn[0], existing_turn[1])
                else:
                    connection.execute("INSERT INTO turns VALUES (?, ?, 0, 0)", (turn_id, now.isoformat()))
                    row = (turn_id, now.isoformat(), 0)
                connection.execute("INSERT INTO tasks VALUES (?, ?)", (task_id, turn_id))
            started = datetime.fromisoformat(row[1])
            if (now - started).total_seconds() > MAX_TURN_SECONDS:
                connection.execute("ROLLBACK")
                raise TurnBudgetExceeded("Turn exceeded 120 seconds")
            if int(row[2]) >= MAX_TOOL_CALLS:
                connection.execute("ROLLBACK")
                raise TurnBudgetExceeded("Turn exceeded five tool calls")
            connection.execute(
                "UPDATE turns SET tool_calls=tool_calls+1 WHERE turn_id=?", (row[0],),
            )
            connection.execute("COMMIT")
            return str(row[0])
