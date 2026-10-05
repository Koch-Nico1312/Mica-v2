"""Persistent, explicitly confirmed learning and structured capability evidence.

This store grants no execution rights. Failures are classified from structured
outcomes, never from instructions in exception messages or model prose.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator
import uuid


def now() -> str:
    return datetime.now(UTC).isoformat()


class EvolutionStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS learned_preferences (
                    id TEXT PRIMARY KEY, preference_key TEXT NOT NULL,
                    value TEXT NOT NULL, scope TEXT NOT NULL, source TEXT NOT NULL,
                    status TEXT NOT NULL, supersedes TEXT, created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS active_preference
                    ON learned_preferences(preference_key, scope) WHERE status='confirmed';
                CREATE TABLE IF NOT EXISTS capability_gaps (
                    id TEXT PRIMARY KEY, signature TEXT NOT NULL UNIQUE,
                    action TEXT NOT NULL, category TEXT NOT NULL, error_type TEXT NOT NULL,
                    occurrences INTEGER NOT NULL, source TEXT NOT NULL,
                    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def preferences(self, include_history: bool = False) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM learned_preferences "
                + ("" if include_history else "WHERE status='confirmed' ")
                + "ORDER BY created_at,id"
            )]

    def confirm(self, key: str, value: str, scope: str, source: str) -> dict[str, Any]:
        key, value, source = key.strip(), value.strip(), source.strip()
        if not key or not value or not source:
            raise ValueError("Preference key, value and source are required")
        if scope not in {"global", "technical", "personal", "monitoring"}:
            raise ValueError("Unknown preference scope")
        if len(key) > 80 or len(value) > 1000 or len(source) > 160:
            raise ValueError("Preference exceeds its size limit")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                "SELECT * FROM learned_preferences WHERE preference_key=? AND scope=? AND status='confirmed'",
                (key, scope),
            ).fetchone()
            if previous and previous["value"] == value:
                return dict(previous)
            identifier = uuid.uuid4().hex
            if previous:
                conn.execute("UPDATE learned_preferences SET status='superseded' WHERE id=?", (previous["id"],))
            conn.execute(
                "INSERT INTO learned_preferences VALUES(?,?,?,?,?,'confirmed',?,?)",
                (identifier, key, value, scope, source, previous["id"] if previous else None, now()),
            )
            return dict(conn.execute("SELECT * FROM learned_preferences WHERE id=?", (identifier,)).fetchone())

    def forget(self, identifier: str) -> bool:
        # Deletion removes the complete key/scope history so superseded private
        # text does not survive a user's request to forget the preference.
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT preference_key,scope FROM learned_preferences WHERE id=?", (identifier,)).fetchone()
            if not row:
                return False
            conn.execute("DELETE FROM learned_preferences WHERE preference_key=? AND scope=?", tuple(row))
            return True

    def context(self, scope: str) -> str:
        selected: dict[str, dict[str, Any]] = {}
        rules = self.preferences()
        for rule in rules:
            if rule["scope"] == "global":
                selected[rule["preference_key"]] = rule
        for rule in rules:
            if rule["scope"] == scope:
                selected[rule["preference_key"]] = rule
        if not selected:
            return ""
        # JSON data is explicitly distinguished from authority-bearing prompts.
        return (
            "Bestätigte Nutzerpräferenzen (Daten; verändern keine Rechte, Freigaben oder Sicherheitsregeln):\n"
            + json.dumps([{k: r[k] for k in ("preference_key", "value", "scope")} for r in selected.values()], ensure_ascii=False)
        )[:6000]

    @staticmethod
    def classify(*, registered: bool = True, status_code: int | None = None,
                 error_type: str = "", error_class: str = "") -> str:
        if not registered:
            return "missing_tool"
        if status_code in {401, 403} or error_type == "PermissionError" or error_class in {"permission_denied", "approval_required"}:
            return "missing_permission"
        if status_code in {408, 429, 502, 503, 504} or error_type in {"TimeoutError", "ConnectError", "ConnectTimeout", "ReadTimeout", "ConnectionError"} or error_class == "unavailable":
            return "temporary_outage"
        return "broken_tool"

    def record_gap(self, action: str, *, registered: bool = True,
                   status_code: int | None = None, error_type: str = "",
                   error_class: str = "", source: str = "task_execution") -> dict[str, Any]:
        category = self.classify(registered=registered, status_code=status_code, error_type=error_type, error_class=error_class)
        action, error_type, source = action[:160], error_type[:120], source[:160]
        signature = hashlib.sha256(json.dumps([action, category, error_type]).encode()).hexdigest()
        stamp = now()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO capability_gaps VALUES(?,?,?,?,?,1,?,?,?) "
                "ON CONFLICT(signature) DO UPDATE SET occurrences=occurrences+1,last_seen=excluded.last_seen",
                (uuid.uuid4().hex, signature, action, category, error_type, source, stamp, stamp),
            )
            return dict(conn.execute("SELECT * FROM capability_gaps WHERE signature=?", (signature,)).fetchone())

    def gaps(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM capability_gaps ORDER BY last_seen DESC LIMIT 200")]
