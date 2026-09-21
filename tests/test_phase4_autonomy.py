from __future__ import annotations

import os
import ast
import json
import importlib
import sqlite3
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "backend"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from backup_restore import run_drill
from services.common.audit import AuditLog
from services.common.brain import MarkdownBrain
from services.common.capabilities import capability_for
from services.common.phase4 import HARD_BUDGET, Phase4Store, day_state_for, steps_for_goal
from services.common.improvements import ImprovementRegistry
from services.common.policy import PolicyEngine
from services.common.scheduler_store import ScheduleStore
from services.common.task_automation import TaskAutomationStore
from services.scheduler import run_cycle


class FakeAudit:
    def __init__(self):
        self.events = []

    def append(self, event, payload):
        self.events.append((event, payload))


class FakeImprovementRegistry:
    def __init__(self):
        self.proposals = []

    def propose(self, name, kind, content, evidence):
        item = {"id": "a" * 32, "name": name, "kind": kind}
        self.proposals.append((item, content, evidence))
        return item


class UnusedLearning:
    def monitor(self, *_args, **_kwargs):
        raise AssertionError("learning monitor was not expected")


class Phase4Tests(unittest.TestCase):
    def test_additive_schema_preserves_phase3_tables(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.sqlite3"
            conn = sqlite3.connect(path)
            conn.execute("CREATE TABLE task_items(id TEXT PRIMARY KEY,title TEXT)")
            conn.execute("INSERT INTO task_items VALUES('old','bleibt')")
            conn.commit()
            conn.close()
            Phase4Store(path)
            conn = sqlite3.connect(path)
            try:
                self.assertEqual(conn.execute("SELECT title FROM task_items WHERE id='old'").fetchone()[0], "bleibt")
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                conn.close()
            self.assertIn("agent_plans", tables)
            self.assertIn("digital_twin_facts", tables)

    def test_plan_hash_risk_budgets_and_correction_invalidate_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Phase4Store(Path(temporary) / "state.sqlite3")
            plan = store.create_plan("ZimaOS prüfen", [{"action": "system.status", "params": {}, "expected_change": "none"}])
            self.assertEqual(plan["risk"], "read")
            self.assertEqual(plan["budget"]["max_steps"], 6)
            self.assertEqual(plan["assessment"]["target_systems"], ["zimaos_host"])
            self.assertEqual(plan["assessment"]["reversibility"], "read_only")
            preview = store.dry_run(plan["id"], PolicyEngine(Path(temporary) / "approval.sqlite3"))
            self.assertFalse(preview["mutated_external_state"])
            corrected = store.patch_plan(plan["id"], {"steps": [
                {"action": "system.status", "params": {}, "expected_change": "read metrics"},
                {"action": "docker.status", "params": {}, "expected_change": "read containers"},
            ]})
            self.assertNotEqual(plan["plan_hash"], corrected["plan_hash"])
            self.assertIsNone(corrected["dry_run_at"])
            self.assertIsNone(corrected["approval_id"])
            with self.assertRaises(ValueError):
                store.create_plan("zu groß", [{"action": "system.status", "params": {}}] * (HARD_BUDGET["max_steps"] + 1))
            with self.assertRaises(ValueError):
                store.create_plan("unbekannt", [{"action": "shell.exec", "params": {"command": "whoami"}}])
            with self.assertRaises(ValueError):
                store.create_plan("extern", [{"action": "send_message", "params": {"recipient": "x"}}])

    def test_risk_change_creates_revision_and_requires_fresh_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = Phase4Store(root / "state.sqlite3")
            policy = PolicyEngine(root / "approval.sqlite3")
            plan = store.create_plan("Status", [{"action": "system.status", "params": {}}])
            store.dry_run(plan["id"], policy)
            changed = store.patch_plan(plan["id"], {"steps": [{
                "action": "files.create", "params": {"path": "/data/report.txt", "content": "ok"},
                "expected_change": "new local file",
            }]})
            self.assertEqual(changed["revision"], 2)
            self.assertEqual(changed["risk"], "reversible")
            self.assertNotEqual(changed["plan_hash"], plan["plan_hash"])
            self.assertIsNone(changed["dry_run_at"])
            with self.assertRaises(ValueError):
                store.activate(changed["id"], policy)
            preview = store.dry_run(changed["id"], policy)
            self.assertEqual(preview["steps"][0]["required_approval"], "parameter_bound")
            _, decision = store.activate(changed["id"], policy)
            self.assertTrue(decision.requires_approval)

    def test_host_plan_capabilities_are_registered_and_overwrite_is_destructive(self):
        self.assertEqual(capability_for("system.status").risk_for({}), "read")
        self.assertEqual(capability_for("files.create").risk_for({"overwrite": False}), "reversible")
        self.assertEqual(capability_for("files.create").risk_for({"overwrite": True}), "destructive")
        self.assertIsNone(capability_for("shell.exec"))

    def test_server_plan_target_is_normalized_and_allowlisted(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "MICA_SERVER_AGENT_TARGETS": "zimaos-local",
        }):
            store = Phase4Store(Path(temporary) / "state.sqlite3")
            plan = store.create_plan("Status", [{"action": "system.status", "params": {}}])
            self.assertEqual(plan["steps"][0]["params"]["target_id"], "zimaos-local")
            preview = store.dry_run(plan["id"], PolicyEngine(Path(temporary) / "approval.sqlite3"))
            self.assertEqual(preview["steps"][0]["required_approval"], "none")
            with self.assertRaises(ValueError):
                store.create_plan("Fremdes Ziel", [{
                    "action": "system.status", "params": {"target_id": "public-host"},
                }])

    def test_goal_decomposition_is_finite_and_rejects_unknown_goals(self):
        self.assertEqual([step["action"] for step in steps_for_goal("ZimaOS und Docker Status prüfen")],
                         ["system.status", "docker.status"])
        with self.assertRaises(ValueError):
            steps_for_goal("Mach irgendetwas Intelligentes")

    def test_read_plan_runs_one_step_per_cycle_and_stop_is_rechecked(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "MICA_PHASE4_ENABLED": "1", "MICA_SELF_PLANNING_ENABLED": "1",
        }):
            root = Path(temporary)
            store = Phase4Store(root / "state.sqlite3")
            policy = PolicyEngine(root / "approval.sqlite3")
            tasks = TaskAutomationStore(root / "state.sqlite3")
            audit = FakeAudit()
            plan = store.create_plan("lesen", [
                {"action": "system.status", "params": {}},
                {"action": "docker.status", "params": {}},
            ])
            store.dry_run(plan["id"], policy)
            activated, decision = store.activate(plan["id"], policy)
            self.assertTrue(decision.allowed)
            calls = []
            dispatch = lambda action, params, key, approval_id=None: calls.append((action, key)) or {"ok": True}
            self.assertEqual(store.run_one_step(policy, dispatch, tasks, audit)["status"], "completed")
            self.assertEqual(len(calls), 1)
            policy.set_emergency_stop(True)
            self.assertEqual(store.run_one_step(policy, dispatch, tasks, audit)["status"], "stopped")
            self.assertEqual(len(calls), 1)
            self.assertEqual(activated["status"], "active")

    def test_reversible_plan_needs_exact_approval_and_destructive_step_stops_again(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "MICA_PHASE4_ENABLED": "1", "MICA_SELF_PLANNING_ENABLED": "1",
        }):
            root = Path(temporary)
            store = Phase4Store(root / "state.sqlite3")
            policy = PolicyEngine(root / "approval.sqlite3")
            tasks = TaskAutomationStore(root / "state.sqlite3")
            audit = FakeAudit()
            plan = store.create_plan("Neustart prüfen", [{
                "action": "docker.lifecycle", "params": {"operation": "restart", "container": "mica-api"},
            }])
            store.dry_run(plan["id"], policy)
            _, pending = store.activate(plan["id"], policy)
            self.assertFalse(pending.allowed)
            self.assertTrue(pending.requires_approval)
            self.assertTrue(policy.resolve(pending.approval_id, True))
            active, allowed = store.activate(plan["id"], policy, pending.approval_id)
            self.assertTrue(allowed.allowed)
            result = store.run_one_step(policy, lambda *_: {"bad": True}, tasks, audit)
            self.assertEqual(result["status"], "blocked")
            self.assertIsNotNone(result["approval_id"])
            step_approval = result["approval_id"]
            self.assertEqual(store.get_plan(active["id"])["status"], "paused")
            self.assertTrue(policy.resolve(step_approval, True))
            resumed, resume_decision = store.activate(active["id"], policy, step_approval)
            self.assertTrue(resume_decision.allowed)
            calls = []
            completed = store.run_one_step(
                policy, lambda action, params, key, approval_id=None: calls.append(approval_id) or {"ok": True},
                tasks, audit,
            )
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(calls, [step_approval])
            self.assertEqual(store.get_plan(resumed["id"])["status"], "completed")

    def test_failure_creates_finite_correction_and_interrupted_destructive_step_is_not_retried(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "MICA_PHASE4_ENABLED": "1", "MICA_SELF_PLANNING_ENABLED": "1",
        }):
            root = Path(temporary)
            store = Phase4Store(root / "state.sqlite3")
            policy = PolicyEngine(root / "approval.sqlite3")
            tasks = TaskAutomationStore(root / "state.sqlite3")
            audit = FakeAudit()
            plan = store.create_plan("Status lesen", [{"action": "system.status", "params": {}}])
            store.dry_run(plan["id"], policy)
            store.activate(plan["id"], policy)
            failed = store.run_one_step(policy, lambda *_: (_ for _ in ()).throw(TimeoutError()), tasks, audit)
            self.assertEqual(failed["status"], "failed")
            self.assertIsNotNone(failed["correction_id"])
            self.assertEqual(len(store.get_plan(plan["id"])["correction_proposals"]), 1)

            destructive = store.create_plan("Container neu starten", [{
                "action": "docker.lifecycle", "params": {"operation": "restart", "container": "mica-api"},
            }])
            conn = sqlite3.connect(root / "state.sqlite3")
            try:
                conn.execute("UPDATE agent_plans SET status='active',started_at=? WHERE id=?", (datetime.now().astimezone().isoformat(), destructive["id"]))
                conn.execute("UPDATE agent_plan_steps SET status='running' WHERE plan_id=?", (destructive["id"],))
                conn.commit()
            finally:
                conn.close()
            calls = []
            result = store.run_one_step(policy, lambda *_: calls.append(True) or {}, tasks, audit)
            self.assertEqual(result["status"], "idle")
            self.assertEqual(calls, [])
            recovered = store.get_plan(destructive["id"])
            self.assertEqual(recovered["status"], "paused")
            self.assertEqual(recovered["last_error"], "uncertain_outcome")

    def test_failed_dispatch_consumes_tool_budget(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "MICA_PHASE4_ENABLED": "1", "MICA_SELF_PLANNING_ENABLED": "1",
        }):
            root = Path(temporary)
            store = Phase4Store(root / "state.sqlite3")
            policy = PolicyEngine(root / "approval.sqlite3")
            tasks = TaskAutomationStore(root / "state.sqlite3")
            plan = store.create_plan("Status", [{"action": "system.status", "params": {}}])
            store.dry_run(plan["id"], policy)
            store.activate(plan["id"], policy)
            store.run_one_step(policy, lambda *_: (_ for _ in ()).throw(TimeoutError()), tasks, FakeAudit())
            self.assertEqual(store.get_plan(plan["id"])["tool_calls"], 1)

    def test_server_diagnostics_create_local_tasks_and_enforce_allowlist(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"MICA_SERVER_AGENT_TARGETS": "zimaos-local"}):
            root = Path(temporary)
            store = Phase4Store(root / "state.sqlite3")
            tasks = TaskAutomationStore(root / "state.sqlite3")
            observation = store.record_server_observation("zimaos-local", {
                "cpu_percent": 96, "memory_percent": 30, "load_percent": 20, "disk_percent": 91,
                "containers": [{"name": "mica-api", "health": "unhealthy", "running": False, "restart_count": 4}],
            }, tasks)
            self.assertGreaterEqual(len(observation["diagnostics"]), 4)
            self.assertEqual(len(tasks.list_tasks()), len(observation["diagnostics"]))
            self.assertTrue(all("payload" not in item for item in store.server_diagnostics()))
            with self.assertRaises(ValueError):
                store.record_server_observation("arbitrary-host", {}, tasks)
            empty = store.record_server_observation("zimaos-local", {
                "cpu_percent": 1, "memory_percent": 2, "load_percent": 3, "disk_percent": 4,
                "containers": [],
            }, tasks)
            self.assertFalse(empty["mica_services_ok"])

    def test_server_trend_creates_diagnosis_task_and_optional_plan(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "MICA_SERVER_AGENT_TARGETS": "zimaos-local",
        }):
            root = Path(temporary)
            store = Phase4Store(root / "state.sqlite3")
            tasks = TaskAutomationStore(root / "state.sqlite3")
            healthy = [{"name": "mica-api", "health": "healthy", "running": True, "restart_count": 0}]
            for index in range(3):
                store.record_server_observation("zimaos-local", {
                    "cpu_percent": 10 + index, "memory_percent": 20, "load_percent": 10,
                    "disk_percent": 20, "containers": healthy,
                }, tasks)
            spike = store.record_server_observation("zimaos-local", {
                "cpu_percent": 55, "memory_percent": 20, "load_percent": 10,
                "disk_percent": 20, "containers": healthy,
            }, tasks)
            diagnostic = next(
                item for item in store.server_diagnostics()
                if item["id"] in spike["diagnostics"] and item["code"] == "cpu_trend"
            )
            confirmed = store.confirm_server_diagnostic(diagnostic["id"])
            plan = store.create_plan("Diagnose prüfen", [
                {"action": "system.status", "params": {"target_id": confirmed["target_id"]}},
            ], task_id=confirmed["task_id"])
            self.assertTrue(store.link_diagnostic_plan(diagnostic["id"], plan["id"]))
            self.assertEqual(store.server_diagnostics()[0]["plan_id"], plan["id"])

    def test_finite_server_scan_runs_through_scheduler_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "MICA_PHASE4_ENABLED": "1", "MICA_SERVER_AGENT_ENABLED": "1",
            "MICA_SELF_PLANNING_ENABLED": "0", "MICA_SERVER_AGENT_TARGETS": "zimaos-local",
        }):
            root = Path(temporary)
            database = root / "state.sqlite3"
            schedules = ScheduleStore(database)
            tasks = TaskAutomationStore(database)
            phase4 = Phase4Store(database)
            policy = PolicyEngine(root / "approvals.sqlite3")
            brain = MarkdownBrain(root / "brain", root / "brain.sqlite3")
            schedule = schedules.create(
                "Zima überwachen", (datetime.now(UTC) + timedelta(minutes=1)).isoformat(), "server.scan",
                {"target_id": "zimaos-local"}, {"every_seconds": 300, "occurrences": 2},
            )
            conn = sqlite3.connect(database)
            try:
                conn.execute("UPDATE schedules SET run_at=? WHERE id=?", ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), schedule["id"]))
                conn.commit()
            finally:
                conn.close()

            def dispatch(action, params, key, approval_id=None):
                if action == "system.status":
                    return {"result": {"cpu_percent": 10, "memory_percent": 20, "load_percent": 5, "disk_percent": 30}}
                return {"result": {"containers": [{"name": "mica-api", "health": "healthy", "running": True, "restart_count": 0}]}}

            result = run_cycle(FakeAudit(), brain, UnusedLearning(), schedules, tasks, policy, phase4, dispatch)
            self.assertEqual(result["processed"], 1)
            self.assertEqual(len(phase4.server_observations()), 1)
            restarted_schedules = ScheduleStore(database)
            pending = restarted_schedules.list("pending")
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["recurrence"]["occurrences"], 1)

    def test_twin_threshold_sensitive_confirmation_exclusions_and_delete(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "MICA_PHASE4_ENABLED": "1", "MICA_DIGITAL_TWIN_ENABLED": "1",
        }):
            store = Phase4Store(Path(temporary) / "state.sqlite3")
            store.update_twin_settings({"enabled": True})
            fact = None
            for index in range(3):
                fact = store.observe_twin("tasks.preferred_priority", "high", "preference", "task", f"task-{index}", .9)
            self.assertTrue(fact["active"])
            self.assertEqual(fact["observation_count"], 3)
            sensitive = None
            for index in range(3):
                sensitive = store.observe_twin("person.city", "Wien", "location", "chat_summary", f"summary-{index}", .95)
            self.assertFalse(sensitive["active"])
            sensitive = store.patch_twin_fact(sensitive["id"], {"confirmed": True})
            self.assertTrue(sensitive["active"])
            self.assertIsNone(store.observe_twin("token", "api_key=secret", "secret", "task", "unsafe", 1.0))
            with self.assertRaises(ValueError):
                store.patch_twin_fact(sensitive["id"], {"value": "token=must-not-be-stored"})
            self.assertTrue(store.delete_twin_fact(fact["id"]))
            self.assertIsNone(store.get_twin_fact(fact["id"]))

    def test_presence_and_improvement_deduplication(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "MICA_SELF_IMPROVEMENT_ENABLED": "1",
        }):
            store = Phase4Store(Path(temporary) / "state.sqlite3")
            self.assertEqual(store.set_presence("thinking")["state"], "thinking")
            with self.assertRaises(ValueError):
                store.set_presence("secret-mode")
            registry = FakeImprovementRegistry()
            self.assertFalse(store.maybe_propose_improvement("Timeout", "agent-plan:system.status", registry)["proposed"])
            self.assertFalse(store.maybe_propose_improvement("Timeout", "agent-plan:system.status", registry)["proposed"])
            self.assertTrue(store.maybe_propose_improvement("Timeout", "agent-plan:system.status", registry)["proposed"])
            self.assertFalse(store.maybe_propose_improvement("Timeout", "agent-plan:system.status", registry)["proposed"])
            self.assertEqual(len(registry.proposals), 1)
            self.assertEqual(registry.proposals[0][0]["kind"], "prompt")
            suggestion_id = registry.proposals[0][0]["id"]
            self.assertTrue(store.quarantine_improvement(suggestion_id))
            local = datetime.now().astimezone()
            self.assertEqual(day_state_for(local.replace(hour=6)), "morning")
            self.assertEqual(day_state_for(local.replace(hour=12)), "day")
            self.assertEqual(day_state_for(local.replace(hour=20)), "evening")
            self.assertEqual(day_state_for(local.replace(hour=1)), "night")

    def test_shadow_is_read_only_but_promotion_and_rollback_are_single_use(self):
        with tempfile.TemporaryDirectory() as temporary:
            policy = PolicyEngine(Path(temporary) / "approval.sqlite3")
            self.assertTrue(policy.decide("improvement.shadow", {"improvement_id": "a" * 32}).allowed)
            params = {"improvement_id": "a" * 32}
            pending = policy.decide("improvement.promote", params)
            self.assertTrue(pending.requires_approval)
            self.assertEqual(pending.risk, "destructive")
            self.assertTrue(policy.resolve(pending.approval_id, True))
            self.assertTrue(policy.consume_approval(pending.approval_id, "improvement.promote", params))
            self.assertFalse(policy.consume_approval(pending.approval_id, "improvement.promote", params))
            rollback = policy.decide("improvement.rollback", {"name": "safe-runbook"})
            self.assertTrue(rollback.requires_approval)
            self.assertEqual(rollback.risk, "destructive")

    def test_prompt_improvement_shadow_promotion_and_rollback_runtime(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "IMPROVEMENT_WORKSPACE": str(Path(temporary) / "improvement-workspace"),
        }):
            root = Path(temporary)
            registry = ImprovementRegistry(root / "improvements.sqlite3", MarkdownBrain(root / "brain", root / "brain.sqlite3"))
            first = registry.propose("response-style", "prompt", "Antworte kurz.", "Wiederholte lange Antwort")
            self.assertTrue(registry.evaluate(first["id"], True, True, "tests ok", "health ok"))
            self.assertTrue(registry.promote(first["id"]))
            second = registry.propose("response-style", "prompt", "Antworte klar und kurz.", "Erneute Beobachtung")
            self.assertTrue(registry.evaluate(second["id"], True, True, "tests ok", "health ok"))
            self.assertTrue(registry.promote(second["id"]))
            self.assertIn("klar", registry.runtime_artifact("response-style")["content"])
            self.assertTrue(registry.rollback("response-style"))
            restored = registry.runtime_artifact("response-style")
            self.assertEqual(restored["id"], first["id"])
            self.assertIn("Antworte kurz", restored["content"])
            store = Phase4Store(root / "state.sqlite3")
            with patch.dict(os.environ, {"MICA_SELF_IMPROVEMENT_ENABLED": "1"}):
                store.maybe_propose_improvement("server.cpu_trend", "confirmed-diagnostic:zimaos-local", registry)
                store.maybe_propose_improvement("server.cpu_trend", "confirmed-diagnostic:zimaos-local", registry)
                proposed = store.maybe_propose_improvement(
                    "server.cpu_trend", "confirmed-diagnostic:zimaos-local", registry,
                )
            self.assertTrue(proposed["proposed"])
            candidate = next(item for item in registry.list() if item["id"] == proposed["suggestion_id"])
            self.assertEqual(candidate["kind"], "config")

    def test_pyqt_and_pwa_share_the_canonical_avatar_states(self):
        expected = {"offline", "idle", "listening", "thinking", "approval_required", "executing", "speaking", "error"}
        tree = ast.parse((ROOT / "desktop" / "ui.py").read_text(encoding="utf-8"))
        assignments = [node for node in tree.body if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "PRESENCE_STATES" for target in node.targets
        )]
        self.assertEqual(len(assignments), 1)
        ui_states = set(ast.literal_eval(assignments[0].value.args[0]))
        self.assertEqual(ui_states, expected)
        pwa = (CORE / "web_ui" / "index.html").read_text(encoding="utf-8")
        self.assertTrue(all(state in pwa for state in expected))
        self.assertEqual({day_state_for(datetime.now(UTC).replace(hour=hour)) for hour in (1, 6, 12, 20)},
                         {"night", "morning", "day", "evening"})

    def test_backup_contains_valid_versioned_phase4_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data, backups = root / "data", root / "backups"
            data.mkdir()
            TaskAutomationStore(data / "scheduler.sqlite3").create_task("Export")
            Phase4Store(data / "scheduler.sqlite3").create_plan("Exportplan", [{"action": "system.status", "params": {}}])
            MarkdownBrain(data / "brain", data / "brain.sqlite3").write("tasks", "Backup", "Phase 4")
            AuditLog(data / "audit" / "events.jsonl").append("backup.test", {"safe": True})
            report = run_drill(data, backups)
            self.assertTrue(report["passed"])
            self.assertTrue(report["state_export_valid"])
            self.assertTrue(report["state_sqlite_rebuilt"])
            self.assertGreaterEqual(report["restored_state_rows"], 2)


class Phase4ApiTests(unittest.TestCase):
    @staticmethod
    def environment(temporary: str, enabled: str = "1") -> dict[str, str]:
        root = Path(temporary)
        return {
            "BRAIN_DIR": str(root / "brain"), "INDEX_PATH": str(root / "index.sqlite3"),
            "AUDIT_PATH": str(root / "audit.jsonl"), "APPROVAL_DB": str(root / "approvals.sqlite3"),
            "SCHEDULE_DB": str(root / "state.sqlite3"), "MICA_STATE_DB": str(root / "state.sqlite3"),
            "IMPROVEMENT_DB": str(root / "improvements.sqlite3"), "IMPROVEMENT_WORKSPACE": str(root / "improvements"),
            "CONNECTOR_DB": str(root / "connectors.sqlite3"), "LEARNING_DOMAINS_PATH": str(root / "domains.json"),
            "MICA_PROFILE_PATH": str(root / "profile.json"), "MICA_APPROVAL_SECRET": "phase4-test-secret",
            "MICA_PHASE3_ENABLED": "1", "MICA_PHASE4_ENABLED": enabled,
            "MICA_SELF_PLANNING_ENABLED": enabled, "MICA_SERVER_AGENT_ENABLED": enabled,
            "MICA_DIGITAL_TWIN_ENABLED": enabled, "MICA_SELF_IMPROVEMENT_ENABLED": enabled,
            "MICA_SERVER_AGENT_TARGETS": "zimaos-local", "MICA_LEARNING_NETWORK": "0",
            "MICA_SERVER_AGENT_FIXTURES": "1",
        }

    def test_flags_default_closed_and_presence_remains_readable(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, self.environment(temporary, "0"), clear=False):
            module = importlib.reload(importlib.import_module("services.api.app"))
            with TestClient(module.app) as client:
                self.assertEqual(client.get("/v1/agent-plans").status_code, 409)
                self.assertEqual(client.get("/v1/server-agent/status").status_code, 409)
                self.assertEqual(client.get("/v1/digital-twin/facts").status_code, 409)
                presence = client.get("/v1/presence")
                self.assertEqual(presence.status_code, 200)
                self.assertFalse(presence.json()["phase4_enabled"])

    def test_plan_api_scan_twin_and_unknown_ids(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, self.environment(temporary), clear=False):
            module = importlib.reload(importlib.import_module("services.api.app"))
            with TestClient(module.app) as client:
                created = client.post("/v1/agent-plans", json={
                    "goal": "ZimaOS prüfen",
                })
                self.assertEqual(created.status_code, 200, created.text)
                self.assertEqual([item["action"] for item in created.json()["steps"]], ["system.status", "docker.status"])
                plan_id = created.json()["id"]
                self.assertEqual(client.post(f"/v1/agent-plans/{plan_id}/activate", json={}).status_code, 409)
                preview = client.post(f"/v1/agent-plans/{plan_id}/dry-run")
                self.assertEqual(preview.status_code, 200)
                self.assertFalse(preview.json()["mutated_external_state"])
                active = client.post(f"/v1/agent-plans/{plan_id}/activate", json={})
                self.assertEqual(active.status_code, 200)
                self.assertEqual(active.json()["status"], "active")
                missing = "0" * 32
                self.assertEqual(client.get(f"/v1/agent-plans/{missing}").status_code, 404)
                self.assertEqual(client.post(f"/v1/agent-plans/{missing}/dry-run").status_code, 404)
                invalid = client.post("/v1/agent-plans", json={
                    "goal": "Shell", "steps": [{"action": "shell.exec", "params": {"command": "id"}}],
                })
                self.assertEqual(invalid.status_code, 422)
                scan = client.post("/v1/server-agent/scan", json={"target_id": "zimaos-local", "monitor_occurrences": 3, "snapshot": {
                    "cpu_percent": 20, "memory_percent": 30, "load_percent": 10, "disk_percent": 40,
                    "containers": [{"name": "mica-api", "health": "healthy", "running": True, "restart_count": 0}],
                }})
                self.assertEqual(scan.status_code, 200, scan.text)
                monitor = module.schedule_store.get(scan.json()["monitoring_schedule_id"])
                self.assertEqual(monitor["action"], "server.scan")
                self.assertEqual(monitor["recurrence"], {"every_seconds": 300, "occurrences": 3})
                self.assertEqual(client.get("/v1/server-agent/observations").status_code, 200)
                self.assertEqual(client.get("/v1/server-agent/diagnostics").status_code, 200)
                settings = client.patch("/v1/digital-twin/settings", json={"enabled": True})
                self.assertEqual(settings.status_code, 200)
                profile = client.patch("/v1/profile", json={"communication_preferences": ["kurz und klar"]})
                self.assertEqual(profile.status_code, 200)
                facts = client.get("/v1/digital-twin/facts")
                self.assertEqual(facts.status_code, 200)
                self.assertTrue(any(item["confirmed"] and item["active"] for item in facts.json()["facts"]))

            audit_text = (Path(temporary) / "audit.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("ZimaOS prüfen", audit_text)
            self.assertNotIn("containers", audit_text)
            self.assertNotIn("snapshot", audit_text)
            allowed = {
                "plan_id", "plan_hash", "risk", "status", "observation_id", "schedule_id",
                "diagnostic_id", "task_id", "fact_id", "improvement_id",
            }
            phase4_events = [json.loads(line) for line in audit_text.splitlines() if line.strip()]
            for event in phase4_events:
                if event["type"].startswith(("agent_plan.", "server_agent.", "digital_twin.", "improvement.")):
                    self.assertFalse(set(event["payload"]) - allowed, event)

    def test_confirmed_diagnostic_can_create_a_bounded_plan(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, self.environment(temporary), clear=False):
            module = importlib.reload(importlib.import_module("services.api.app"))
            with TestClient(module.app) as client:
                scan = client.post("/v1/server-agent/scan", json={"target_id": "zimaos-local", "snapshot": {
                    "cpu_percent": 99, "memory_percent": 20, "load_percent": 10, "disk_percent": 20,
                    "containers": [{"name": "mica-api", "health": "healthy", "running": True, "restart_count": 0}],
                }})
                diagnostic_id = scan.json()["diagnostics"][0]
                confirmed = client.post(
                    f"/v1/server-agent/diagnostics/{diagnostic_id}/confirm", json={"create_plan": True},
                )
                self.assertEqual(confirmed.status_code, 200, confirmed.text)
                self.assertEqual(confirmed.json()["status"], "confirmed")
                plan = client.get(f"/v1/agent-plans/{confirmed.json()['plan_id']}")
                self.assertEqual(plan.status_code, 200)
                self.assertEqual([step["action"] for step in plan.json()["steps"]], ["system.status", "docker.status"])


class Phase4BrokerAuditTests(unittest.TestCase):
    def test_ids_only_mode_excludes_params_and_host_result(self):
        class FakeHost:
            def execute(self, action, params, approval_id):
                return {"request_id": "request-123", "secret_result": "must-not-enter-audit"}

        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "BRAIN_DIR": str(Path(temporary) / "brain"),
            "INDEX_PATH": str(Path(temporary) / "brain.sqlite3"),
            "AUDIT_PATH": str(Path(temporary) / "audit.jsonl"),
            "APPROVAL_DB": str(Path(temporary) / "approvals.sqlite3"),
            "CONNECTOR_DB": str(Path(temporary) / "connectors.sqlite3"),
            "IDEMPOTENCY_DB": str(Path(temporary) / "idempotency.sqlite3"),
            "OPERATIONS_DB": str(Path(temporary) / "operations.sqlite3"),
            "TURN_BUDGET_DB": str(Path(temporary) / "turn-budget.sqlite3"),
        }, clear=False):
            broker = importlib.reload(importlib.import_module("services.tool_broker"))
            broker.brain.search = lambda *_args, **_kwargs: []
            with patch.object(broker.HostAgentClient, "from_environment", return_value=FakeHost()):
                result = broker.call_tool(broker.ToolCall(
                    task_id="a" * 32, action="system.status",
                    params={"target_id": "private-zima-host"}, audit_mode="ids_only",
                ))
            self.assertTrue(result["dispatched"])
            audit_text = (Path(temporary) / "audit.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("private-zima-host", audit_text)
            self.assertNotIn("must-not-enter-audit", audit_text)
            self.assertNotIn('"params"', audit_text)
            self.assertIn('"risk": "read"', audit_text)


if __name__ == "__main__":
    unittest.main()
