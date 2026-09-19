from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator


TASK_STATUSES = {"open", "in_progress", "completed", "cancelled"}
TASK_PRIORITIES = {"low", "normal", "high"}
RULE_PAIRS = {
    ("task.overdue", "reminder.create"),
    ("schedule.failed", "task.create"),
}
ALLOWED_TRANSITIONS = {
    "open": {"open", "in_progress", "completed", "cancelled"},
    "in_progress": {"open", "in_progress", "completed", "cancelled"},
    "completed": {"completed"},
    "cancelled": {"cancelled"},
}


def _enabled(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def phase3_enabled() -> bool:
    return _enabled("MICA_PHASE3_ENABLED")


def automations_enabled() -> bool:
    return _enabled("MICA_AUTOMATIONS_ENABLED")


class TaskAutomationStore:
    """Small local task and finite-rule store sharing the scheduler database."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS task_items ("
                "id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL, "
                "status TEXT NOT NULL, priority TEXT NOT NULL, due_at TEXT, "
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS automation_rules ("
                "id TEXT PRIMARY KEY, name TEXT NOT NULL, trigger_name TEXT NOT NULL, "
                "action_name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0, "
                "cooldown_seconds INTEGER NOT NULL, max_runs INTEGER NOT NULL, "
                "run_count INTEGER NOT NULL DEFAULT 0, last_run_at TEXT, last_error TEXT, "
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS automation_firings ("
                "rule_id TEXT NOT NULL, subject_id TEXT NOT NULL, status TEXT NOT NULL, "
                "fired_at TEXT NOT NULL, PRIMARY KEY(rule_id, subject_id))"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_items_status_due ON task_items(status, due_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rules_enabled ON automation_rules(enabled, trigger_name)")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _time(value: str | None, field: str = "due_at") -> str | None:
        if value is None or value == "":
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError) as error:
            raise ValueError(f"{field} must be an ISO-8601 timestamp") from error
        if parsed.tzinfo is None:
            raise ValueError(f"{field} must include a timezone offset")
        return parsed.astimezone(UTC).isoformat()

    @staticmethod
    def _task(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "id": row[0], "title": row[1], "description": row[2], "status": row[3],
            "priority": row[4], "due_at": row[5], "created_at": row[6], "updated_at": row[7],
        }

    @staticmethod
    def _rule(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "id": row[0], "name": row[1], "trigger": row[2], "action": row[3],
            "enabled": bool(row[4]), "cooldown_seconds": row[5], "max_runs": row[6],
            "run_count": row[7], "remaining_runs": max(0, row[6] - row[7]),
            "last_run_at": row[8], "last_error": row[9],
            "created_at": row[10], "updated_at": row[11],
        }

    def create_task(
        self, title: str, description: str = "", priority: str = "normal", due_at: str | None = None,
    ) -> dict[str, Any]:
        title = title.strip()
        if not title:
            raise ValueError("title is required")
        if priority not in TASK_PRIORITIES:
            raise ValueError("priority must be low, normal or high")
        now = self._now()
        task = {
            "id": uuid.uuid4().hex, "title": title[:160], "description": description.strip()[:4000],
            "status": "open", "priority": priority, "due_at": self._time(due_at),
            "created_at": now, "updated_at": now,
        }
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO task_items(id,title,description,status,priority,due_at,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                tuple(task[key] for key in (
                    "id", "title", "description", "status", "priority", "due_at", "created_at", "updated_at"
                )),
            )
        return task

    def list_tasks(
        self, status: str | None = None, priority: str | None = None,
        overdue: bool = False, limit: int = 200,
    ) -> list[dict[str, Any]]:
        if status and status not in TASK_STATUSES:
            raise ValueError("invalid task status")
        if priority and priority not in TASK_PRIORITIES:
            raise ValueError("invalid task priority")
        clauses: list[str] = []
        values: list[Any] = []
        if status:
            clauses.append("status = ?")
            values.append(status)
        if priority:
            clauses.append("priority = ?")
            values.append(priority)
        if overdue:
            clauses.extend(["status IN ('open','in_progress')", "due_at IS NOT NULL", "due_at <= ?"])
            values.append(self._now())
        query = "SELECT id,title,description,status,priority,due_at,created_at,updated_at FROM task_items"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, due_at IS NULL, due_at, created_at LIMIT ?"
        values.append(max(1, min(limit, 500)))
        with self._connect() as conn:
            rows = conn.execute(query, values).fetchall()
        return [self._task(row) for row in rows]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id,title,description,status,priority,due_at,created_at,updated_at "
                "FROM task_items WHERE id = ?", (task_id,),
            ).fetchone()
        return self._task(row) if row else None

    def update_task(self, task_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {"title", "description", "status", "priority", "due_at"}
        if not changes or set(changes) - allowed:
            raise ValueError("no supported task fields supplied")
        current = self.get_task(task_id)
        if not current:
            return None
        if "title" in changes:
            title = str(changes["title"] or "").strip()
            if not title:
                raise ValueError("title is required")
            current["title"] = title[:160]
        if "description" in changes:
            current["description"] = str(changes["description"] or "").strip()[:4000]
        if "priority" in changes:
            if changes["priority"] not in TASK_PRIORITIES:
                raise ValueError("invalid task priority")
            current["priority"] = changes["priority"]
        if "status" in changes:
            status = changes["status"]
            if status not in TASK_STATUSES or status not in ALLOWED_TRANSITIONS[current["status"]]:
                raise ValueError(f"invalid transition from {current['status']}")
            current["status"] = status
        if "due_at" in changes:
            current["due_at"] = self._time(changes["due_at"])
        current["updated_at"] = self._now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE task_items SET title=?,description=?,status=?,priority=?,due_at=?,updated_at=? WHERE id=?",
                (current["title"], current["description"], current["status"], current["priority"],
                 current["due_at"], current["updated_at"], task_id),
            )
        return current

    def create_rule(
        self, name: str, trigger: str, action: str, cooldown_seconds: int, max_runs: int,
    ) -> dict[str, Any]:
        if (trigger, action) not in RULE_PAIRS:
            raise ValueError("unsupported trigger/action pair")
        if not 60 <= cooldown_seconds <= 2_592_000:
            raise ValueError("cooldown_seconds must be between 60 and 2592000")
        if not 1 <= max_runs <= 100:
            raise ValueError("max_runs must be between 1 and 100")
        now = self._now()
        rule_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO automation_rules(id,name,trigger_name,action_name,enabled,cooldown_seconds,max_runs,"
                "run_count,last_run_at,last_error,created_at,updated_at) VALUES (?,?,?,?,0,?,?,0,NULL,NULL,?,?)",
                (rule_id, (name or "Lokale Automation").strip()[:160], trigger, action,
                 cooldown_seconds, max_runs, now, now),
            )
        return self.get_rule(rule_id) or {}

    def list_rules(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id,name,trigger_name,action_name,enabled,cooldown_seconds,max_runs,run_count,"
                "last_run_at,last_error,created_at,updated_at FROM automation_rules ORDER BY created_at"
            ).fetchall()
        return [self._rule(row) for row in rows]

    def get_rule(self, rule_id: str) -> dict[str, Any] | None:
        return next((item for item in self.list_rules() if item["id"] == rule_id), None)

    def update_rule(self, rule_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {"enabled", "cooldown_seconds", "max_runs"}
        if not changes or set(changes) - allowed:
            raise ValueError("no supported rule fields supplied")
        current = self.get_rule(rule_id)
        if not current:
            return None
        enabled = bool(changes.get("enabled", current["enabled"]))
        cooldown = changes.get("cooldown_seconds", current["cooldown_seconds"])
        max_runs = changes.get("max_runs", current["max_runs"])
        if isinstance(cooldown, bool) or not isinstance(cooldown, int) or not 60 <= cooldown <= 2_592_000:
            raise ValueError("cooldown_seconds must be between 60 and 2592000")
        if isinstance(max_runs, bool) or not isinstance(max_runs, int) or not current["run_count"] <= max_runs <= 100:
            raise ValueError("max_runs must be between run_count and 100")
        with self._connect() as conn:
            conn.execute(
                "UPDATE automation_rules SET enabled=?,cooldown_seconds=?,max_runs=?,updated_at=? WHERE id=?",
                (1 if enabled else 0, cooldown, max_runs, self._now(), rule_id),
            )
        return self.get_rule(rule_id)

    def claim_firing(self, rule_id: str, subject_id: str, now: datetime | None = None) -> bool:
        now = (now or datetime.now(UTC)).astimezone(UTC)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT enabled,cooldown_seconds,max_runs,run_count,last_run_at FROM automation_rules WHERE id=?",
                (rule_id,),
            ).fetchone()
            if not row or not row[0] or row[3] >= row[2]:
                conn.execute("ROLLBACK")
                return False
            if row[4] and datetime.fromisoformat(row[4]) + timedelta(seconds=row[1]) > now:
                conn.execute("ROLLBACK")
                return False
            try:
                conn.execute(
                    "INSERT INTO automation_firings(rule_id,subject_id,status,fired_at) VALUES (?,?,'running',?)",
                    (rule_id, subject_id, now.isoformat()),
                )
            except sqlite3.IntegrityError:
                conn.execute("ROLLBACK")
                return False
            conn.execute(
                "UPDATE automation_rules SET run_count=run_count+1,last_run_at=?,last_error=NULL,updated_at=? WHERE id=?",
                (now.isoformat(), now.isoformat(), rule_id),
            )
            conn.execute("COMMIT")
        return True

    def finish_firing(self, rule_id: str, subject_id: str, success: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE automation_firings SET status=? WHERE rule_id=? AND subject_id=?",
                ("completed" if success else "failed", rule_id, subject_id),
            )
            if not success:
                conn.execute(
                    "UPDATE automation_rules SET last_error='Ausführung fehlgeschlagen',updated_at=? WHERE id=?",
                    (self._now(), rule_id),
                )


def rule_candidates(
    store: TaskAutomationStore, schedule_store: Any, rule: dict[str, Any], now: datetime | None = None,
) -> list[dict[str, Any]]:
    if rule["trigger"] == "task.overdue":
        return store.list_tasks(overdue=True, limit=500)
    if rule["trigger"] == "schedule.failed":
        return schedule_store.list(status="failed", limit=500)
    return []


def dry_run_rule(store: TaskAutomationStore, schedule_store: Any, rule_id: str) -> dict[str, Any] | None:
    rule = store.get_rule(rule_id)
    if not rule:
        return None
    candidates = rule_candidates(store, schedule_store, rule)
    return {
        "rule": rule,
        "candidate_count": len(candidates),
        "candidate_ids": [item["id"] for item in candidates[:20]],
        "would_run": min(len(candidates), rule["remaining_runs"]),
        "mutated": False,
    }


def evaluate_automations(
    store: TaskAutomationStore, schedule_store: Any, brain: Any, audit: Any,
    *, emergency_stopped: bool,
) -> dict[str, Any]:
    if not phase3_enabled() or not automations_enabled():
        return {"status": "disabled", "executed": 0, "failed": 0}
    if emergency_stopped:
        return {"status": "stopped", "executed": 0, "failed": 0}
    executed = failed = 0
    for rule in store.list_rules():
        if not rule["enabled"] or not rule["remaining_runs"]:
            continue
        for subject in rule_candidates(store, schedule_store, rule):
            if not store.claim_firing(rule["id"], subject["id"]):
                continue
            try:
                if rule["action"] == "reminder.create":
                    brain.write(
                        "tasks", f"Erinnerung: {subject['title']}",
                        "Diese lokale Aufgabe ist überfällig.",
                        {"task_id": subject["id"], "automation_rule_id": rule["id"]},
                    )
                elif rule["action"] == "task.create":
                    store.create_task(
                        f"Zeitplan fehlgeschlagen: {subject['name']}",
                        "Ein lokaler Zeitplan ist fehlgeschlagen. Details stehen im Audit.",
                        "high",
                    )
                store.finish_firing(rule["id"], subject["id"], True)
                audit.append("automation.completed", {
                    "rule_id": rule["id"], "trigger": rule["trigger"],
                    "action": rule["action"], "subject_id": subject["id"],
                })
                executed += 1
            except Exception as error:
                store.finish_firing(rule["id"], subject["id"], False)
                store.create_task(
                    "Automationsfehler prüfen",
                    f"Regel {rule['id']} konnte ihre lokale Aktion nicht abschließen ({type(error).__name__}).",
                    "high",
                )
                audit.append("automation.failed", {
                    "rule_id": rule["id"], "trigger": rule["trigger"],
                    "action": rule["action"], "subject_id": subject["id"],
                    "error_type": type(error).__name__,
                })
                failed += 1
    return {"status": "completed", "executed": executed, "failed": failed}
