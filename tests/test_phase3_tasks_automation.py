from __future__ import annotations

import importlib
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "mica_core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from backup_restore import run_drill
from services.common.audit import AuditLog
from services.common.brain import MarkdownBrain
from services.common.policy import PolicyEngine
from services.common.scheduler_store import ScheduleStore
from services.common.task_automation import (
    TaskAutomationStore,
    dry_run_rule,
    evaluate_automations,
)
from services.scheduler import run_cycle


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def append(self, name: str, payload: dict) -> None:
        self.events.append((name, payload))


class UnusedLearning:
    def monitor(self, *_args, **_kwargs):
        raise AssertionError("learning.monitor was not expected")


class SelectiveFailBrain(MarkdownBrain):
    def write(self, kind, title, body, metadata=None):
        if "Fehler-Eingabe" in title:
            raise RuntimeError("contains private input that must not reach audit")
        return super().write(kind, title, body, metadata)


class Phase3StoreTests(unittest.TestCase):
    def test_recovered_runtime_uses_normal_source_files(self) -> None:
        expected = [
            ROOT / "local_main.py", ROOT / "install_and_start.ps1",
            ROOT / "requirements-phase0.lock", CORE / "services" / "api" / "app.py",
            CORE / "services" / "scheduler.py", CORE / "web_ui" / "index.html",
            CORE / "backup_restore.py", ROOT / "docs" / "phase2-acceptance.md",
        ]
        self.assertTrue(all(path.is_file() for path in expected))
        task_module = importlib.import_module("services.common.task_automation")
        self.assertEqual(Path(task_module.__file__).suffix, ".py")
        launcher = (ROOT / "install_and_start.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('"local_main.py"', launcher)
        self.assertIn("install_and_start.ps1", (ROOT / "readme.md").read_text(encoding="utf-8"))

    def test_recovered_backup_restore_path_rebuilds_truth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data, backups = root / "data", root / "backups"
            brain = MarkdownBrain(data / "brain", data / "index" / "brain.sqlite3")
            brain.write("tasks", "Wiederherstellung", "Lokaler Test", {"source": "phase3a"})
            AuditLog(data / "audit" / "events.jsonl").append("phase3a.backup_test", {"safe": True})
            report = run_drill(data, backups)
            self.assertTrue(report["passed"])
            self.assertTrue(report["audit_valid"])
            self.assertTrue(report["sqlite_rebuilt"])
            self.assertGreaterEqual(report["markdown_documents"], 1)
            self.assertTrue(Path(report["archive"]).is_file())

    def test_schedule_migration_is_additive_and_keeps_existing_row(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "schedules.sqlite3"
            conn = sqlite3.connect(path)
            try:
                conn.execute(
                    "CREATE TABLE schedules (id TEXT PRIMARY KEY,name TEXT,run_at TEXT,action TEXT,params TEXT,"
                    "status TEXT,created_at TEXT,dispatched_at TEXT,recurrence TEXT,series_id TEXT)"
                )
                now = datetime.now(UTC).isoformat()
                conn.execute(
                    "INSERT INTO schedules VALUES ('old','Alt',?,'brain.reindex','{}','pending',?,NULL,'{}',NULL)",
                    ((datetime.now(UTC) + timedelta(hours=1)).isoformat(), now),
                )
                conn.commit()
            finally:
                conn.close()
            store = ScheduleStore(path)
            old = store.get("old")
            self.assertIsNotNone(old)
            self.assertIsNone(old["task_id"])
            conn = sqlite3.connect(path)
            try:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(schedules)")}
            finally:
                conn.close()
            self.assertIn("task_id", columns)

    def test_task_validation_transitions_and_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = TaskAutomationStore(Path(temporary) / "state.sqlite3")
            task = store.create_task("Backup prüfen", "lokal", "high")
            active = store.update_task(task["id"], {"status": "in_progress"})
            self.assertEqual(active["status"], "in_progress")
            done = store.update_task(task["id"], {"status": "completed"})
            self.assertEqual(done["status"], "completed")
            self.assertEqual(store.update_task(task["id"], {"status": "completed"})["status"], "completed")
            with self.assertRaises(ValueError):
                store.update_task(task["id"], {"status": "open"})
            with self.assertRaises(ValueError):
                store.create_task("Naiv", due_at="2026-09-18T12:00:00")

    def test_filters_cooldown_and_budget_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = TaskAutomationStore(Path(temporary) / "state.sqlite3")
            overdue = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
            first = store.create_task("Hoch", priority="high", due_at=overdue)
            store.create_task("Niedrig", priority="low")
            self.assertEqual([item["id"] for item in store.list_tasks(priority="high")], [first["id"]])
            self.assertEqual([item["id"] for item in store.list_tasks(overdue=True)], [first["id"]])

            rule = store.create_rule("Grenzen", "task.overdue", "reminder.create", 60, 2)
            store.update_rule(rule["id"], {"enabled": True})
            now = datetime.now(UTC)
            self.assertTrue(store.claim_firing(rule["id"], "subject-1", now))
            self.assertFalse(store.claim_firing(rule["id"], "subject-2", now + timedelta(seconds=30)))
            self.assertTrue(store.claim_firing(rule["id"], "subject-2", now + timedelta(seconds=61)))
            self.assertFalse(store.claim_firing(rule["id"], "subject-3", now + timedelta(seconds=122)))
            self.assertEqual(store.get_rule(rule["id"])["remaining_runs"], 0)

    def test_rules_are_finite_deduplicated_and_dry_run_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "MICA_PHASE3_ENABLED": "1", "MICA_AUTOMATIONS_ENABLED": "1",
        }):
            root = Path(temporary)
            store = TaskAutomationStore(root / "state.sqlite3")
            schedules = ScheduleStore(root / "state.sqlite3")
            brain = MarkdownBrain(root / "brain", root / "index.sqlite3")
            due = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
            task = store.create_task("Rechnung prüfen", due_at=due)
            rule = store.create_rule("Überfällig", "task.overdue", "reminder.create", 60, 2)
            store.update_rule(rule["id"], {"enabled": True})
            preview = dry_run_rule(store, schedules, rule["id"])
            self.assertEqual(preview["candidate_ids"], [task["id"]])
            self.assertFalse(preview["mutated"])
            self.assertEqual(store.get_rule(rule["id"])["run_count"], 0)

            audit = FakeAudit()
            first = evaluate_automations(store, schedules, brain, audit, emergency_stopped=False)
            second = evaluate_automations(store, schedules, brain, audit, emergency_stopped=False)
            self.assertEqual(first["executed"], 1)
            self.assertEqual(second["executed"], 0)
            self.assertEqual(store.get_rule(rule["id"])["remaining_runs"], 1)
            self.assertEqual(len(brain.documents()), 1)

    def test_failed_schedule_creates_one_task_and_stop_blocks_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "MICA_PHASE3_ENABLED": "1", "MICA_AUTOMATIONS_ENABLED": "1",
        }):
            root = Path(temporary)
            store = TaskAutomationStore(root / "state.sqlite3")
            schedules = ScheduleStore(root / "state.sqlite3")
            brain = MarkdownBrain(root / "brain", root / "index.sqlite3")
            schedule = schedules.create(
                "Index", (datetime.now(UTC) + timedelta(minutes=1)).isoformat(), "brain.reindex",
            )
            schedules.claim_due(datetime.now(UTC) + timedelta(minutes=2))
            schedules.finish_due(schedule["id"], False)
            rule = store.create_rule("Fehler", "schedule.failed", "task.create", 60, 3)
            store.update_rule(rule["id"], {"enabled": True})
            stopped = evaluate_automations(store, schedules, brain, FakeAudit(), emergency_stopped=True)
            self.assertEqual(stopped["status"], "stopped")
            self.assertEqual(store.list_tasks(), [])
            evaluate_automations(store, schedules, brain, FakeAudit(), emergency_stopped=False)
            evaluate_automations(store, schedules, brain, FakeAudit(), emergency_stopped=False)
            tasks = store.list_tasks()
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["priority"], "high")

    def test_linked_finite_schedule_creates_local_reminder_and_stop_holds_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "MICA_PHASE3_ENABLED": "1", "MICA_AUTOMATIONS_ENABLED": "0",
        }):
            root = Path(temporary)
            store = TaskAutomationStore(root / "state.sqlite3")
            schedules = ScheduleStore(root / "state.sqlite3")
            brain = MarkdownBrain(root / "brain", root / "index.sqlite3")
            policy = PolicyEngine(root / "approvals.sqlite3")
            task = store.create_task("Einmalige Erinnerung")
            schedule = schedules.create(
                "Task-Erinnerung", (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
                "reminder.create", recurrence={"every_seconds": 60, "occurrences": 2}, task_id=task["id"],
            )
            conn = sqlite3.connect(root / "state.sqlite3")
            try:
                conn.execute(
                    "UPDATE schedules SET run_at=? WHERE id=?",
                    ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), schedule["id"]),
                )
                conn.commit()
            finally:
                conn.close()
            result = run_cycle(FakeAudit(), brain, UnusedLearning(), schedules, store, policy)
            self.assertEqual(result["processed"], 1)
            self.assertEqual(schedules.get(schedule["id"])["status"], "completed")
            remaining = schedules.list(status="pending")
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0]["task_id"], task["id"])
            self.assertEqual(len(brain.documents()), 1)

            held = schedules.create(
                "Durch Not-Aus gehalten", (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
                "reminder.create", task_id=task["id"],
            )
            conn = sqlite3.connect(root / "state.sqlite3")
            try:
                conn.execute(
                    "UPDATE schedules SET run_at=? WHERE id=?",
                    ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), held["id"]),
                )
                conn.commit()
            finally:
                conn.close()
            policy.set_emergency_stop(True)
            stopped = run_cycle(FakeAudit(), brain, UnusedLearning(), schedules, store, policy)
            self.assertEqual(stopped["status"], "stopped")
            self.assertEqual(schedules.get(held["id"])["status"], "pending")
            self.assertEqual(len(brain.documents()), 1)

    def test_schedule_error_isolated_audited_and_exposed_as_one_local_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "MICA_PHASE3_ENABLED": "1", "MICA_AUTOMATIONS_ENABLED": "1",
        }):
            root = Path(temporary)
            store = TaskAutomationStore(root / "state.sqlite3")
            schedules = ScheduleStore(root / "state.sqlite3")
            brain = SelectiveFailBrain(root / "brain", root / "index.sqlite3")
            policy = PolicyEngine(root / "approvals.sqlite3")
            failing = schedules.create(
                "Fehler-Eingabe", (datetime.now(UTC) + timedelta(minutes=1)).isoformat(), "reminder.create",
            )
            succeeding = schedules.create(
                "Sichere Erinnerung", (datetime.now(UTC) + timedelta(minutes=1)).isoformat(), "reminder.create",
            )
            rule = store.create_rule("Fehlerfolge", "schedule.failed", "task.create", 60, 1)
            store.update_rule(rule["id"], {"enabled": True})
            conn = sqlite3.connect(root / "state.sqlite3")
            try:
                conn.execute(
                    "UPDATE schedules SET run_at=? WHERE id IN (?,?)",
                    ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), failing["id"], succeeding["id"]),
                )
                conn.commit()
            finally:
                conn.close()
            audit = FakeAudit()
            result = run_cycle(audit, brain, UnusedLearning(), schedules, store, policy)
            self.assertEqual(result["failed"], 1)
            self.assertEqual(result["processed"], 1)
            self.assertEqual(result["automations_executed"], 1)
            self.assertEqual(schedules.get(failing["id"])["status"], "failed")
            self.assertEqual(schedules.get(succeeding["id"])["status"], "completed")
            followups = store.list_tasks()
            self.assertEqual(len(followups), 1)
            self.assertIn("Zeitplan fehlgeschlagen", followups[0]["title"])
            self.assertNotIn("Fehler-Eingabe", repr(audit.events))

    def test_only_fixed_rule_pairs_are_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = TaskAutomationStore(Path(temporary) / "state.sqlite3")
            with self.assertRaises(ValueError):
                store.create_rule("Frei", "task.overdue", "message.send", 60, 1)
            source = (CORE / "services" / "common" / "task_automation.py").read_text(encoding="utf-8")
            for forbidden in ("subprocess", "os.system", "socket", "httpx", "requests", "message.send", "host."):
                self.assertNotIn(forbidden, source)


class Phase3ApiTests(unittest.TestCase):
    @staticmethod
    def environment(temporary: str, enabled: str = "1") -> dict[str, str]:
        root = Path(temporary)
        return {
            "BRAIN_DIR": str(root / "brain"), "INDEX_PATH": str(root / "index.sqlite3"),
            "AUDIT_PATH": str(root / "audit.jsonl"), "APPROVAL_DB": str(root / "approvals.sqlite3"),
            "SCHEDULE_DB": str(root / "schedules.sqlite3"), "IMPROVEMENT_DB": str(root / "improvements.sqlite3"),
            "IMPROVEMENT_WORKSPACE": str(root / "improvements"), "CONNECTOR_DB": str(root / "connectors.sqlite3"),
            "LEARNING_DOMAINS_PATH": str(root / "domains.json"), "MICA_PROFILE_PATH": str(root / "profile.json"),
            "MICA_APPROVAL_SECRET": "phase3-test-secret", "MICA_PHASE3_ENABLED": enabled,
            "MICA_AUTOMATIONS_ENABLED": "0", "MICA_LEARNING_NETWORK": "0",
        }

    def test_pilot_is_disabled_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, self.environment(temporary, "0"), clear=False,
        ):
            module = importlib.reload(importlib.import_module("services.api.app"))
            with TestClient(module.app) as client:
                self.assertEqual(client.get("/v1/task-items").status_code, 409)
                self.assertEqual(client.get("/v1/automations/rules").status_code, 409)

    def test_crud_schedule_link_approval_and_dry_run_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, self.environment(temporary), clear=False,
        ):
            module = importlib.reload(importlib.import_module("services.api.app"))
            with TestClient(module.app) as client:
                created = client.post("/v1/task-items", json={
                    "title": "Backup prüfen", "description": "lokal", "priority": "high",
                })
                self.assertEqual(created.status_code, 200)
                task_id = created.json()["id"]
                self.assertEqual(client.get(f"/v1/task-items/{task_id}").status_code, 200)
                second = client.post("/v1/task-items", json={"title": "Später", "priority": "low"})
                self.assertEqual(second.status_code, 200)
                edited = client.patch(f"/v1/task-items/{task_id}", json={
                    "title": "Backup kontrollieren", "description": "lokal geändert", "priority": "high",
                    "due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                })
                self.assertEqual(edited.status_code, 200)
                self.assertEqual(edited.json()["title"], "Backup kontrollieren")
                linked = client.post("/v1/schedules", json={
                    "name": "Index", "run_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                    "action": "brain.reindex", "task_id": task_id,
                })
                self.assertEqual(linked.status_code, 200)
                self.assertEqual(linked.json()["task_id"], task_id)
                self.assertEqual(client.patch(f"/v1/task-items/{task_id}", json={"status": "completed"}).status_code, 200)
                self.assertEqual(client.patch(f"/v1/task-items/{task_id}", json={"status": "open"}).status_code, 422)
                filtered = client.get("/v1/task-items?status=completed&priority=high")
                self.assertEqual([item["id"] for item in filtered.json()["tasks"]], [task_id])
                missing_id = "0" * 32
                self.assertEqual(client.get(f"/v1/task-items/{missing_id}").status_code, 404)
                self.assertEqual(client.patch(f"/v1/task-items/{missing_id}", json={"status": "cancelled"}).status_code, 404)
                missing_link = client.post("/v1/schedules", json={
                    "name": "Unbekannt", "run_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                    "action": "brain.reindex", "task_id": missing_id,
                })
                self.assertEqual(missing_link.status_code, 404)

                invalid = client.post("/v1/automations/rules", json={
                    "name": "Falsch", "trigger": "task.overdue", "action": "task.create",
                })
                self.assertEqual(invalid.status_code, 422)
                created_rule = client.post("/v1/automations/rules", json={
                    "name": "Überfällig", "trigger": "task.overdue", "action": "reminder.create",
                    "cooldown_seconds": 60, "max_runs": 2,
                })
                self.assertEqual(created_rule.status_code, 200)
                self.assertFalse(created_rule.json()["enabled"])
                rule_id = created_rule.json()["id"]
                self.assertEqual(client.patch(f"/v1/automations/rules/{missing_id}", json={"enabled": False}).status_code, 404)
                self.assertEqual(client.post(f"/v1/automations/rules/{missing_id}/dry-run").status_code, 404)
                disabled = client.patch(f"/v1/automations/rules/{rule_id}", json={"enabled": True})
                self.assertEqual(disabled.status_code, 409)
                os.environ["MICA_AUTOMATIONS_ENABLED"] = "1"
                module.policy.set_emergency_stop(True)
                stopped = client.patch(f"/v1/automations/rules/{rule_id}", json={"enabled": True})
                self.assertEqual(stopped.status_code, 403)
                self.assertIsNone(stopped.json()["detail"]["approval_id"])
                module.policy.set_emergency_stop(False)
                blocked = client.patch(f"/v1/automations/rules/{rule_id}", json={"enabled": True})
                self.assertEqual(blocked.status_code, 403)
                approval_id = blocked.json()["detail"]["approval_id"]

                login = client.post("/v1/auth/approval-session", json={"secret": "phase3-test-secret"})
                self.assertEqual(login.status_code, 200)
                approved = client.post(
                    f"/v1/approvals/{approval_id}", json={"approved": True},
                    headers={"X-Mica-Approval-Intent": "confirm"},
                )
                self.assertEqual(approved.status_code, 200)
                enabled = client.patch(f"/v1/automations/rules/{rule_id}", json={"enabled": True})
                self.assertEqual(enabled.status_code, 200)
                self.assertTrue(enabled.json()["enabled"])
                limits = client.patch(
                    f"/v1/automations/rules/{rule_id}",
                    json={"cooldown_seconds": 120, "max_runs": 4},
                )
                self.assertEqual(limits.status_code, 200)
                self.assertEqual(limits.json()["cooldown_seconds"], 120)
                self.assertEqual(limits.json()["remaining_runs"], 4)
                preview = client.post(f"/v1/automations/rules/{rule_id}/dry-run")
                self.assertEqual(preview.status_code, 200)
                self.assertFalse(preview.json()["mutated"])

            audit_text = (Path(temporary) / "audit.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("Backup prüfen", audit_text)
            self.assertNotIn("Backup kontrollieren", audit_text)
            self.assertNotIn('"name":"Index"', audit_text)
            self.assertNotIn('"description":"lokal"', audit_text)
            self.assertNotIn("lokal geändert", audit_text)
            self.assertNotIn("phase3-test-secret", audit_text)

        html = (CORE / "web_ui" / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-view="tasks"', html)
        self.assertIn("/v1/task-items", html)
        self.assertIn("/v1/automations/rules", html)
        self.assertIn('id="task-filter-status"', html)
        self.assertIn("Bearbeiten", html)
        self.assertIn("Erinnerung planen", html)
        self.assertIn("Letzter Lauf", html)
        self.assertIn("Grenzen ändern", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
