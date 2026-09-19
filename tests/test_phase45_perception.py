"""Acceptance and unit tests for MICA Phase 4.5: Wahrnehmung & Präsenz.

Validates:
1. Vision / Kamera-Input (VisionEngine, rack diagnostics, audit redaction)
2. Ambient Awareness (AmbientMonitor, cooldowns, quiet hours, alerting)
3. Sprach-Adressierungserkennung (AddressingDetector, vocatives vs background chatter)
4. Physische Präsenz / Hardware-Anker (SatelliteRegistry, heartbeat, announcements)
5. Auth-/Bestätigungs-Layer für autonome Aktionen (AutonomousActionGuard, tiers, tickets, Not-Aus)
6. Mobiler Notfall-Zugriff (EmergencyService, token auth, rate-limiting, Not-Aus)
7. REST API Endpoints in services.api.app (Phase 4.5 flags, validation, authorization)
"""
from __future__ import annotations

import base64
import importlib
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "mica_core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from services.common.addressing import AddressDecision, AddressingDetector
from services.common.ambient import AmbientMonitor, _is_quiet_hours
from services.common.audit import AuditLog
from services.common.autonomous_guard import AutonomousActionGuard, AutonomousDecision
from services.common.brain import MarkdownBrain
from services.common.capabilities import capability_for
from services.common.emergency import EmergencyService
from services.common.phase4 import Phase4Store
from services.common.policy import PolicyEngine
from services.common.satellite import SatelliteRegistry
from services.common.scheduler_store import ScheduleStore
from services.common.task_automation import TaskAutomationStore
from services.common.vision import VisionEngine, VisionResult, detect_image_format
from services.scheduler import run_cycle
from host_agent.satellite_node import SatelliteNodeClient


# Valid 1x1 PNG sample bytes
SAMPLE_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff"
    b"?\x00\x05\xfe\x02\xfe\r\xef\x8fX\x00\x00\x00\x00IEND\xaeB`\x82"
)


class FakeAudit:
    def __init__(self):
        self.events = []

    def append(self, event, payload):
        self.events.append((event, payload))


class Phase45VisionTests(unittest.TestCase):
    def setUp(self):
        self.engine = VisionEngine()

    def test_format_detection_and_validation(self):
        fmt, sha, dims = self.engine.validate_image_payload(SAMPLE_PNG)
        self.assertEqual(fmt, "png")
        self.assertEqual(len(sha), 64)
        self.assertEqual(dims, (1, 1))

        with self.assertRaises(ValueError):
            self.engine.validate_image_payload(b"")
        with self.assertRaises(ValueError):
            self.engine.validate_image_payload(b"NOT_AN_IMAGE_PAYLOAD_AT_ALL")
        with self.assertRaises(ValueError):
            self.engine.validate_image_payload(b"X" * (6 * 1024 * 1024))  # Exceeds 5MB

    def test_server_rack_diagnostics_modes(self):
        # Healthy rack
        healthy = self.engine.analyze(SAMPLE_PNG, mode="server_rack")
        self.assertEqual(healthy.mode, "server_rack")
        self.assertIn("betriebsbereit", healthy.summary.lower())
        self.assertEqual(healthy.rack_diagnostic["severity"], "healthy")
        self.assertEqual(healthy.rack_diagnostic["power_led"], "green")

        # Warning clue
        warning_data = SAMPLE_PNG + b" WARNING: Drive degradation detected"
        warn_res = self.engine.analyze(warning_data, mode="server_rack")
        self.assertEqual(warn_res.rack_diagnostic["severity"], "warning")
        self.assertEqual(warn_res.rack_diagnostic["alert_led"], "amber")

        # Critical clue
        crit_data = SAMPLE_PNG + b" CRITICAL ALERT: Power failure"
        crit_res = self.engine.analyze(crit_data, mode="server_rack")
        self.assertEqual(crit_res.rack_diagnostic["severity"], "critical")
        self.assertEqual(crit_res.rack_diagnostic["power_led"], "red")
        self.assertEqual(crit_res.rack_diagnostic["rack_door"], "open")

    def test_room_state_and_object_detection(self):
        room = self.engine.analyze(SAMPLE_PNG, mode="room_state")
        self.assertEqual(room.mode, "room_state")
        self.assertIn("lighting", room.room_state)
        self.assertIn("desk", room.detected_objects)

        obj = self.engine.analyze(SAMPLE_PNG, mode="object_detection")
        self.assertEqual(obj.mode, "object_detection")
        self.assertGreaterEqual(len(obj.detected_objects), 1)

    def test_capture_frame_returns_valid_image(self):
        frame = self.engine.capture_frame()
        self.assertTrue(frame.startswith(b"\x89PNG"))
        fmt, sha, dims = self.engine.validate_image_payload(frame)
        self.assertEqual(fmt, "png")


class Phase45AmbientTests(unittest.TestCase):
    def test_ambient_triggers_cooldown_and_quiet_hours(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "ambient.sqlite3"
            monitor = AmbientMonitor(db_path, default_cooldown_seconds=600, quiet_hours_enabled=True, quiet_start_hour=23, quiet_end_hour=7)

            # Test server state evaluation
            obs = [{
                "target_id": "zimaos-local",
                "cpu_percent": 95.0,
                "memory_percent": 60.0,
                "disk_percent": 92.0,
                "unhealthy_count": 2,
                "restart_count": 5,
            }]
            events = monitor.evaluate_server_state(obs)
            self.assertGreaterEqual(len(events), 2)  # Disk critical and containers unhealthy
            severities = [e["severity"] for e in events]
            self.assertIn("critical", severities)

            # Cooldown test: immediately re-evaluating should trigger zero duplicate events
            repeat_events = monitor.evaluate_server_state(obs)
            self.assertEqual(len(repeat_events), 0)

            # Acknowledge event
            pending = monitor.list_events(status="pending")
            self.assertGreaterEqual(len(pending), 1)
            ev_id = pending[0]["id"]
            self.assertTrue(monitor.acknowledge_event(ev_id))
            remaining = monitor.list_events(status="pending")
            self.assertEqual(len(remaining), len(pending) - 1)

    def test_schedule_and_vision_ambient_triggers(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "ambient.sqlite3"
            monitor = AmbientMonitor(db_path)

            now = datetime.now(UTC)
            schedules = [
                {"id": "s1", "name": "Backup-Drill", "run_at": (now + timedelta(minutes=5)).isoformat()},
                {"id": "s2", "name": "Späterer Termin", "run_at": (now + timedelta(hours=3)).isoformat()},
            ]
            events = monitor.evaluate_schedules(schedules, notice_minutes=15)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["code"], "upcoming_event")

            # Vision rack diagnostic evaluation
            rack_diag = {
                "severity": "critical",
                "detected_anomalies": ["Strom-LED rot"],
            }
            v_events = monitor.evaluate_vision_diagnostic(rack_diag, "rack-node-1")
            self.assertEqual(len(v_events), 1)
            self.assertEqual(v_events[0]["severity"], "critical")


class Phase45AddressingTests(unittest.TestCase):
    def setUp(self):
        self.detector = AddressingDetector(confidence_threshold=0.65)

    def test_direct_vocative_addressing(self):
        cases = [
            "Mica, schalte bitte das Licht ein",
            "Hey Jarvis, wie ist der Server-Status?",
            "Computer, öffne die Logs",
            "Mika bitte Not-Aus aktivieren",
        ]
        for text in cases:
            decision = self.detector.evaluate(text)
            self.assertTrue(decision.is_addressed, f"Failed for: {text}")
            self.assertEqual(decision.category, "direct_name")
            self.assertGreaterEqual(decision.confidence, 0.90)

    def test_direct_command_and_query_without_name(self):
        cases = [
            "Kannst du bitte den Status prüfen?",
            "Wie viel Uhr ist es?",
            "Wie ist das Wetter heute?",
            "Zeige mir alle Container",
            "Was machst du gerade?",
        ]
        for text in cases:
            decision = self.detector.evaluate(text)
            self.assertTrue(decision.is_addressed, f"Failed for direct command/query: {text}")
            self.assertIn(decision.category, ("direct_command", "direct_query"))

    def test_ambient_chatter_and_media_exclusion(self):
        chatter_cases = [
            "Und dann hat er gesagt wir gehen heute Abend essen",
            "Sie meinte dass wir morgen einkaufen müssen",
            "Hallo Mama ich bins ich ruf dich später an",
            "Im Fernsehen läuft gerade die Zusammenfassung vom Fußball",
            "In den Nachrichten wurde über das Wetter morgen berichtet",
        ]
        for text in chatter_cases:
            decision = self.detector.evaluate(text)
            self.assertFalse(decision.is_addressed, f"False positive for background chatter: {text}")
            self.assertEqual(decision.category, "ambient_chatter")


class Phase45SatelliteTests(unittest.TestCase):
    def test_satellite_registry_lifecycle_and_announcements(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "satellites.sqlite3"
            registry = SatelliteRegistry(db_path, heartbeat_timeout_seconds=2)

            # Register two nodes
            node1 = registry.register("sat-pi-lab", "Labor-Anchor", "Labor", "192.168.1.50")
            node2 = registry.register("sat-pi-living", "Wohnzimmer-Anchor", "Wohnzimmer", "192.168.1.51")
            self.assertEqual(node1["status"], "online")

            # Queue room announcement
            ann1 = registry.queue_announcement("sat-pi-lab", "Achtung: Labor-Temperatur prüfen.", priority="high")
            self.assertEqual(ann1["status"], "pending")

            # Heartbeat from sat-pi-lab receives the announcement
            received = registry.heartbeat("sat-pi-lab", {"cpu_temp": 42.5})
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0]["message"], "Achtung: Labor-Temperatur prüfen.")

            # Mark delivered
            self.assertTrue(registry.mark_announcement_delivered(received[0]["id"]))
            # Subsequent heartbeat gets 0 pending announcements
            self.assertEqual(len(registry.heartbeat("sat-pi-lab")), 0)

            # Offline transition test
            time.sleep(2.1)
            nodes = registry.list_satellites()
            self.assertTrue(all(n["status"] == "offline" for n in nodes))

    def test_satellite_node_client_telemetry(self):
        client = SatelliteNodeClient("http://127.0.0.1:8000", "sat-test", "Test Node", "Lab")
        telem = client.collect_local_telemetry()
        self.assertIn("platform", telem)
        self.assertIn("hostname", telem)


class Phase45AutonomousGuardTests(unittest.TestCase):
    def test_tier_classification_and_proposals(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            guard = AutonomousActionGuard(root / "guard.sqlite3", ticket_ttl_minutes=10)
            policy = PolicyEngine(root / "approval.sqlite3")

            # Tier 0: Read operation
            read_dec = guard.evaluate_proposal(
                "system.status", {"target_id": "zimaos-local"},
                origin={"trigger_type": "ambient_monitor", "reason": "regular check"},
                policy_engine=policy,
            )
            self.assertTrue(read_dec.allowed)
            self.assertFalse(read_dec.requires_approval)
            self.assertEqual(read_dec.tier, 0)

            # Tier 1 without policy -> requires approval ticket
            rev_dec = guard.evaluate_proposal(
                "files.move", {"source": "/a", "destination": "/b"},
                origin={"trigger_type": "ambient_cleanup"},
                policy_engine=policy,
            )
            self.assertFalse(rev_dec.allowed)
            self.assertTrue(rev_dec.requires_approval)
            self.assertEqual(rev_dec.tier, 1)
            self.assertIsNotNone(rev_dec.ticket_id)

            # Tier 1 with policy pre-approval -> allowed immediately
            guard.set_tier1_policy("files.move", auto_allow=True)
            auto_rev_dec = guard.evaluate_proposal(
                "files.move", {"source": "/a", "destination": "/b"},
                origin={"trigger_type": "ambient_cleanup"},
                policy_engine=policy,
            )
            self.assertTrue(auto_rev_dec.allowed)
            self.assertFalse(auto_rev_dec.requires_approval)

            # Tier 2: Destructive action (docker.lifecycle restart) -> ALWAYS requires human approval
            dest_dec = guard.evaluate_proposal(
                "docker.lifecycle", {"operation": "restart", "container": "mica-api"},
                origin={"trigger_type": "vision_rack", "reason": "LED alert"},
                policy_engine=policy,
            )
            self.assertFalse(dest_dec.allowed)
            self.assertTrue(dest_dec.requires_approval)
            self.assertEqual(dest_dec.tier, 2)
            ticket_id = dest_dec.ticket_id

            # Approve ticket and consume token
            approved, token = guard.approve_ticket(ticket_id, operator_id="admin")
            self.assertTrue(approved)
            self.assertEqual(len(token), 48)

            # Token consumption
            self.assertTrue(guard.consume_token(ticket_id, token))
            # Replay fails
            self.assertFalse(guard.consume_token(ticket_id, token))

    def test_emergency_stop_blocks_and_revokes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            guard = AutonomousActionGuard(root / "guard.sqlite3")
            policy = PolicyEngine(root / "approval.sqlite3")

            # Create a pending ticket
            dec = guard.evaluate_proposal("files.delete", {"path": "/tmp/junk"}, {"trigger": "ambient"}, policy)
            self.assertFalse(dec.allowed)
            self.assertIsNotNone(dec.ticket_id)

            # Engage Emergency Stop
            policy.set_emergency_stop(True)
            stopped_dec = guard.evaluate_proposal("system.status", {}, {"trigger": "ambient"}, policy)
            self.assertFalse(stopped_dec.allowed)
            self.assertEqual(stopped_dec.risk, "stopped")

            # Revoke all tickets
            revoked_count = guard.revoke_all_on_emergency_stop()
            self.assertGreaterEqual(revoked_count, 1)
            t = guard.get_ticket(dec.ticket_id)
            self.assertEqual(t["status"], "revoked")


class Phase45EmergencyServiceTests(unittest.TestCase):
    def test_emergency_login_lockout_and_actions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            policy = PolicyEngine(root / "approval.sqlite3")
            guard = AutonomousActionGuard(root / "guard.sqlite3")
            service = EmergencyService(secret="notfall-geheimnis-123", max_failed_attempts=3, lockout_seconds=60)

            # Failed login attempts
            self.assertIsNone(service.login("falsches-secret", "192.168.1.100"))
            self.assertIsNone(service.login("falsches-secret", "192.168.1.100"))
            self.assertIsNone(service.login("falsches-secret", "192.168.1.100"))
            # 4th attempt is locked out even with correct secret
            self.assertIsNone(service.login("notfall-geheimnis-123", "192.168.1.100"))

            # Different IP succeeds
            token = service.login("notfall-geheimnis-123", "192.168.1.101")
            self.assertIsNotNone(token)
            self.assertTrue(service.validate_token(token))

            # Trigger Not-Aus remotely
            self.assertFalse(policy.is_emergency_stopped())
            service.trigger_emergency_stop(policy, guard)
            self.assertTrue(policy.is_emergency_stopped())

            # Resume
            service.resume_from_emergency_stop(policy)
            self.assertFalse(policy.is_emergency_stopped())


class Phase45ApiTests(unittest.TestCase):
    @staticmethod
    def environment(temporary: str, phase45_enabled: str = "1") -> dict[str, str]:
        root = Path(temporary)
        return {
            "BRAIN_DIR": str(root / "brain"),
            "INDEX_PATH": str(root / "index.sqlite3"),
            "AUDIT_PATH": str(root / "audit.jsonl"),
            "APPROVAL_DB": str(root / "approvals.sqlite3"),
            "SCHEDULE_DB": str(root / "state.sqlite3"),
            "MICA_STATE_DB": str(root / "state.sqlite3"),
            "IMPROVEMENT_DB": str(root / "improvements.sqlite3"),
            "IMPROVEMENT_WORKSPACE": str(root / "improvements"),
            "CONNECTOR_DB": str(root / "connectors.sqlite3"),
            "MICA_APPROVAL_SECRET": "test-approval-secret",
            "MICA_EMERGENCY_SECRET": "test-emergency-secret",
            "MICA_PHASE4_ENABLED": "1",
            "MICA_PHASE45_ENABLED": phase45_enabled,
        }

    def test_flag_default_closed(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, self.environment(temporary, "0"), clear=False):
            module = importlib.reload(importlib.import_module("services.api.app"))
            with TestClient(module.app) as client:
                self.assertEqual(client.get("/v1/vision/status").status_code, 409)
                self.assertEqual(client.get("/v1/ambient/events").status_code, 409)
                self.assertEqual(client.get("/v1/satellites").status_code, 409)
                self.assertEqual(client.get("/v1/autonomous-guard/tickets").status_code, 409)
                self.assertEqual(client.post("/v1/emergency/login", json={"secret": "x"}).status_code, 409)

                # Presence reports phase45_enabled flag
                res = client.get("/v1/presence")
                self.assertEqual(res.status_code, 200)
                self.assertFalse(res.json()["phase45_enabled"])

    def test_vision_and_addressing_endpoints(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, self.environment(temporary, "1"), clear=False):
            module = importlib.reload(importlib.import_module("services.api.app"))
            with TestClient(module.app) as client:
                # Vision status
                st = client.get("/v1/vision/status")
                self.assertEqual(st.status_code, 200)
                self.assertTrue(st.json()["ready"])

                # Vision analyze
                b64_img = base64.b64encode(SAMPLE_PNG).decode("ascii")
                analyzed = client.post("/v1/vision/analyze", json={
                    "image_base64": b64_img,
                    "mode": "server_rack",
                })
                self.assertEqual(analyzed.status_code, 200)
                self.assertEqual(analyzed.json()["mode"], "server_rack")
                self.assertEqual(analyzed.json()["rack_diagnostic"]["severity"], "healthy")

                # Verify raw image is NEVER in audit log
                audit_text = (Path(temporary) / "audit.jsonl").read_text(encoding="utf-8")
                self.assertNotIn(b64_img[:50], audit_text)
                self.assertIn("vision.analyzed", audit_text)
                self.assertIn(analyzed.json()["image_hash"], audit_text)

                # Audio Addressing
                addr = client.post("/v1/addressing/evaluate", json={"text": "Mica wie geht es dir?"})
                self.assertEqual(addr.status_code, 200)
                self.assertTrue(addr.json()["is_addressed"])
                self.assertEqual(addr.json()["category"], "direct_name")

    def test_satellite_and_emergency_flow(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, self.environment(temporary, "1"), clear=False):
            module = importlib.reload(importlib.import_module("services.api.app"))
            with TestClient(module.app) as client:
                # Register satellite
                reg = client.post("/v1/satellites/register", json={
                    "satellite_id": "sat-pi-1",
                    "name": "Labor-Anchor",
                    "room": "Labor",
                })
                self.assertEqual(reg.status_code, 200)

                # Heartbeat
                hb = client.post("/v1/satellites/sat-pi-1/heartbeat", json={"telemetry": {"cpu_temp": 45.0}})
                self.assertEqual(hb.status_code, 200)

                # Emergency Login
                login_res = client.post("/v1/emergency/login", json={"secret": "test-emergency-secret"})
                self.assertEqual(login_res.status_code, 200)
                token = login_res.json()["token"]

                # Emergency Overview
                ov = client.get("/v1/emergency/overview", headers={"Authorization": f"Bearer {token}"})
                self.assertEqual(ov.status_code, 200)
                self.assertFalse(ov.json()["emergency_stop_active"])

                # Trigger Emergency Stop
                stop_res = client.post("/v1/emergency/stop", headers={"Authorization": f"Bearer {token}"})
                self.assertEqual(stop_res.status_code, 200)
                self.assertTrue(stop_res.json()["stopped"])

                # Verify overview reflects stopped state
                ov2 = client.get("/v1/emergency/overview", headers={"Authorization": f"Bearer {token}"})
                self.assertTrue(ov2.json()["emergency_stop_active"])

                # Resume
                resume_res = client.post("/v1/emergency/resume", headers={"Authorization": f"Bearer {token}"})
                self.assertEqual(resume_res.status_code, 200)
                self.assertFalse(resume_res.json()["stopped"])


class Phase45SchedulerTests(unittest.TestCase):
    def test_scheduler_cycle_evaluates_ambient_monitor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "state.sqlite3"
            schedules = ScheduleStore(database)
            tasks = TaskAutomationStore(database)
            phase4 = Phase4Store(database)
            policy = PolicyEngine(root / "approvals.sqlite3")
            brain = MarkdownBrain(root / "brain", root / "brain.sqlite3")
            ambient = AmbientMonitor(database)

            # Record a high-disk observation to trigger an ambient event
            phase4.record_server_observation("zimaos-local", {
                "cpu_percent": 10, "memory_percent": 20, "load_percent": 5, "disk_percent": 95,
                "containers": [{"name": "mica-api", "health": "healthy", "running": True, "restart_count": 0}],
            }, tasks)

            res = run_cycle(
                audit=FakeAudit(),
                brain=brain,
                learning=None,
                schedules=schedules,
                tasks=tasks,
                policy=policy,
                phase4=phase4,
                ambient_monitor=ambient,
            )
            self.assertEqual(res["status"], "completed")
            self.assertGreaterEqual(res["ambient_events"], 1)


if __name__ == "__main__":
    unittest.main()
