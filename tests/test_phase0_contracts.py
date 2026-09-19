from __future__ import annotations

import os
import importlib
import hashlib
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mica_core"))

from core.local_core_client import LocalCoreClient, LocalCoreError
from core.local_voice import CoreVoiceSession
from services.common.capabilities import (
    CAPABILITIES,
    RISK_DESTRUCTIVE,
    RISK_READ,
    RISK_REVERSIBLE,
    RISK_SENSITIVE_READ,
    capability_for,
)
from services.common.idempotency import IdempotencyConflict, IdempotencyStore
from services.common.policy import PolicyEngine
from mica_core import windows_preflight


class Phase0CapabilityTests(unittest.TestCase):
    def test_exactly_the_twenty_legacy_action_modules_are_registered(self):
        expected = {
            "background_monitor", "browser_control", "code_helper", "computer_control",
            "computer_settings", "desktop", "dev_agent", "file_controller",
            "file_processor", "flight_finder", "game_updater", "open_app", "proactive",
            "reminder", "screen_processor", "send_message", "system_monitor",
            "weather_report", "web_search", "youtube_video",
        }
        self.assertEqual({item.module for item in CAPABILITIES}, expected)
        self.assertEqual(len({item.action for item in CAPABILITIES}), 20)
        self.assertTrue(all(item.allowed_operations for item in CAPABILITIES))
        for item in CAPABILITIES:
            with self.subTest(module=item.module):
                self.assertEqual(set(item.risk_by_operation), set(item.allowed_operations))

    def test_unknown_operation_is_rejected_at_the_manifest_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            policy = PolicyEngine(Path(temporary) / "policy.sqlite3")
            decision = policy.decide("open_app", {"action": "launch_arbitrary_shell"})
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "unsupported_operation")

    def test_network_capabilities_are_disabled_until_explicit_opt_in(self):
        weather = capability_for("weather_report")
        self.assertIsNotNone(weather)
        self.assertEqual(weather.availability({}), (False, "network_disabled"))
        enabled = {
            "MICA_CAPABILITY_WEATHER_REPORT_NETWORK": "true",
            "MICA_CAPABILITY_WEATHER_REPORT_TARGETS": "www.google.com",
        }
        self.assertEqual(weather.availability(enabled), (True, "available"))

    def test_operation_level_risk_and_retry_contract(self):
        files = capability_for("file_controller")
        self.assertEqual(files.risk_for({"action": "read"}), RISK_SENSITIVE_READ)
        self.assertEqual(files.risk_for({"action": "delete"}), RISK_DESTRUCTIVE)
        self.assertEqual(files.retry_for({"action": "read"}).max_attempts, 3)
        self.assertEqual(files.retry_for({"action": "delete"}).max_attempts, 1)
        self.assertTrue(files.retry_for({"action": "delete"}).requires_idempotency_key)
        self.assertFalse(files.retry_for({"action": "delete"}).retry_after_unknown_outcome)

    def test_registry_actions_use_the_common_policy_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {
                "MICA_CAPABILITY_WEB_SEARCH_NETWORK": "1",
                "MICA_CAPABILITY_WEB_SEARCH_TARGETS": "duckduckgo.com",
            }, clear=False):
                policy = PolicyEngine(Path(temporary) / "policy.sqlite3")
                blocked_search = policy.decide("web_search", {"mode": "search"})
                self.assertEqual(blocked_search.risk, "unavailable")
                self.assertEqual(blocked_search.reason, "operation_requires_local_replacement")
                sensitive = policy.decide("computer_control", {"action": "screenshot"})
                self.assertEqual(sensitive.risk, RISK_SENSITIVE_READ)
                self.assertTrue(sensitive.requires_approval)
                reversible = policy.decide("open_app", {"app_name": "notepad"})
                self.assertEqual(reversible.risk, RISK_REVERSIBLE)
                destructive = policy.decide("send_message", {"receiver": "test"})
                self.assertEqual(destructive.risk, "unavailable")


class Phase0IdempotencyTests(unittest.TestCase):
    def test_completed_result_is_replayed_only_for_identical_parameters(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = IdempotencyStore(Path(temporary) / "idempotency.sqlite3")
            self.assertIsNone(store.begin("request-0001", "open_app", {"app_name": "notepad"}))
            store.complete("request-0001", {"dispatched": True})
            self.assertEqual(
                store.begin("request-0001", "open_app", {"app_name": "notepad"}),
                {"dispatched": True},
            )
            with self.assertRaises(IdempotencyConflict):
                store.begin("request-0001", "open_app", {"app_name": "calc"})

    def test_started_unknown_execution_cannot_be_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = IdempotencyStore(Path(temporary) / "idempotency.sqlite3")
            store.begin("request-0002", "send_message", {"receiver": "test"})
            with self.assertRaisesRegex(IdempotencyConflict, "in progress"):
                store.begin("request-0002", "send_message", {"receiver": "test"})


class WindowsPreflightTests(unittest.TestCase):
    def test_preflight_remains_blocked_when_required_proofs_are_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            backup = root / "backup"
            data.mkdir()
            backup.mkdir()
            with (
                patch.object(windows_preflight, "_command", return_value={"ok": False, "reason": "test"}),
                patch.object(windows_preflight, "_audio", return_value={"ok": False}),
                patch.object(windows_preflight, "_credential_manager", return_value={"ok": False}),
                patch.object(windows_preflight, "_bitlocker", return_value={"ok": False}),
                patch.object(windows_preflight, "_port_available", return_value={"ok": True}),
            ):
                result = windows_preflight.check(data, backup, environ={})
            self.assertFalse(result["ready"])
            self.assertEqual(result["schema_version"], 1)
            self.assertIn("models", result["checks"])


class LocalCoreClientTests(unittest.TestCase):
    def test_client_refuses_non_local_or_plaintext_endpoints(self):
        for url in ("http://127.0.0.1:8000", "https://example.com"):
            with self.subTest(url=url), self.assertRaises(LocalCoreError):
                LocalCoreClient(url)

    def test_voice_meter_uses_pcm_without_persisting_audio(self):
        quiet = (b"\x00\x00" * 1280)
        loud_sample = int(4000).to_bytes(2, "little", signed=True)
        loud = loud_sample * 1280
        self.assertEqual(CoreVoiceSession._level(quiet), 0.0)
        self.assertGreater(CoreVoiceSession._level(loud), 0.0)

    def test_escape_cancel_interrupts_audio_in_under_200ms(self):
        client = LocalCoreClient("https://127.0.0.1:8443")
        session = CoreVoiceSession(client)
        fake_sounddevice = Mock()
        started = time.monotonic()
        with patch.dict(sys.modules, {"sounddevice": fake_sounddevice}):
            session.cancel()
        elapsed = time.monotonic() - started
        fake_sounddevice.stop.assert_called_once_with()
        self.assertLess(elapsed, 0.2)

    def test_server_cancel_state_also_interrupts_local_audio(self):
        client = LocalCoreClient("https://127.0.0.1:8443")
        session = CoreVoiceSession(client)
        completed = threading.Event()
        websocket = Mock()
        websocket.recv.return_value = '{"type":"state","state":"cancelled"}'
        fake_sounddevice = Mock()
        with patch.dict(sys.modules, {"sounddevice": fake_sounddevice}):
            session._reader(websocket, completed)
        self.assertTrue(completed.is_set())
        fake_sounddevice.stop.assert_called_once_with()

    def test_wake_word_requires_a_real_local_model_file(self):
        from core.local_voice import WakeWordListener

        with tempfile.TemporaryDirectory() as temporary:
            model = Path(temporary) / "hey_mica.onnx"
            listener = WakeWordListener(lambda: None, model_path=model)
            self.assertFalse(listener.configured)
            payload = b"onnx-test-placeholder"
            model.write_bytes(payload)
            self.assertFalse(listener.configured)
            provenance = model.with_name(model.name + ".provenance.json")
            provenance.write_text(json.dumps({
                "source": "local-consented-training",
                "version": "test-v1",
                "license": "private-use",
                "test_dataset": "local-held-out-v1",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "acceptance": {
                    "utterances": 40,
                    "detections": 38,
                    "background_hours": 8,
                    "false_activations": 1,
                },
            }), encoding="utf-8")
            self.assertTrue(listener.configured)

    def test_wake_word_microphone_is_explicitly_configurable(self):
        from core.local_voice import WakeWordListener

        with patch.dict(os.environ, {"MICA_WAKE_WORD_DEVICE": "3"}, clear=False):
            listener = WakeWordListener(lambda: None)
        self.assertEqual(listener.device, 3)


class Phase0ApiTests(unittest.TestCase):
    def test_voice_uses_the_common_turn_pipeline_and_versioned_states(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ,
            {
                "BRAIN_DIR": str(Path(temporary) / "brain"),
                "INDEX_PATH": str(Path(temporary) / "index.sqlite3"),
                "AUDIT_PATH": str(Path(temporary) / "audit.jsonl"),
                "APPROVAL_DB": str(Path(temporary) / "approvals.sqlite3"),
                "SCHEDULE_DB": str(Path(temporary) / "schedule.sqlite3"),
                "IMPROVEMENT_DB": str(Path(temporary) / "improvements.sqlite3"),
                "IMPROVEMENT_WORKSPACE": str(Path(temporary) / "improvements"),
                "CONNECTOR_DB": str(Path(temporary) / "connectors.sqlite3"),
                "MICA_APPROVAL_SECRET": "phase0-voice-test",
            },
            clear=False,
        ):
            module = importlib.reload(importlib.import_module("mica_core.services.api.app"))

            class Response:
                def __init__(self, *, data=None, content=b""):
                    self._data = data or {}
                    self.content = content

                def raise_for_status(self):
                    return None

                def json(self):
                    return self._data

            class AsyncClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    return None

                async def post(self, url, **_kwargs):
                    if url.endswith("/v1/transcribe"):
                        return Response(data={"text": "Hallo lokal"})
                    return Response(content=b"RIFF-test")

            planned_turn = Mock(return_value={
                "schema_version": 1, "turn_id": "1" * 32,
                "state": "completed", "reply": "Lokale Antwort",
            })
            with (
                patch.object(module.httpx, "AsyncClient", return_value=AsyncClient()),
                patch.object(module, "turn", planned_turn),
                TestClient(module.app) as client,
                client.websocket_connect("/v1/voice", headers={"origin": "http://localhost:8088"}) as websocket,
            ):
                self.assertEqual(websocket.receive_json()["state"], "listening")
                websocket.send_json({
                    "schema_version": 1, "command": "start",
                    "input_mode": "push_to_talk", "state": "listening",
                })
                self.assertEqual(websocket.receive_json()["state"], "listening")
                websocket.send_bytes(b"\x00\x00" * 16)
                self.assertEqual(websocket.receive_json()["type"], "audio_ack")
                websocket.send_json({
                    "schema_version": 1, "command": "finalize",
                    "input_mode": "push_to_talk", "state": "transcribing",
                })
                self.assertEqual(websocket.receive_json()["state"], "transcribing")
                self.assertEqual(websocket.receive_json()["state"], "planning")
                self.assertEqual(websocket.receive_json()["type"], "transcript")
                self.assertEqual(websocket.receive_json()["text"], "Lokale Antwort")
                self.assertEqual(websocket.receive_json()["state"], "speaking")
                self.assertEqual(websocket.receive_bytes(), b"RIFF-test")
            request = planned_turn.call_args.args[0]
            self.assertEqual(request.client, "voice")
            self.assertEqual(request.message, "Hallo lokal")

    def test_capability_and_turn_endpoints_expose_versioned_contracts(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ,
            {
                "BRAIN_DIR": str(Path(temporary) / "brain"),
                "INDEX_PATH": str(Path(temporary) / "index.sqlite3"),
                "AUDIT_PATH": str(Path(temporary) / "audit.jsonl"),
                "APPROVAL_DB": str(Path(temporary) / "approvals.sqlite3"),
                "SCHEDULE_DB": str(Path(temporary) / "schedule.sqlite3"),
                "IMPROVEMENT_DB": str(Path(temporary) / "improvements.sqlite3"),
                "IMPROVEMENT_WORKSPACE": str(Path(temporary) / "improvements"),
                "CONNECTOR_DB": str(Path(temporary) / "connectors.sqlite3"),
                "MICA_APPROVAL_SECRET": "phase0-api-test",
            },
            clear=False,
        ):
            module = importlib.import_module("mica_core.services.api.app")
            module = importlib.reload(module)
            capabilities = module.capabilities()
            self.assertEqual(capabilities["schema_version"], 1)
            self.assertEqual(capabilities["count"], 20)
            planned = module.turn(module.TurnRequest(
                message="Oeffne Notepad", action="open_app",
                params={"app_name": "notepad"}, dry_run=True,
            ))
            self.assertEqual(planned["state"], "planned")
            self.assertEqual(planned["plan"]["permission"]["risk"], RISK_REVERSIBLE)
            self.assertTrue(planned["plan"]["permission"]["allowed"])
            dry_run = module.execute_task(module.TaskExecution(
                action="open_app", params={"app_name": "notepad"}, dry_run=True,
            ))
            self.assertEqual(dry_run["status"], "dry_run")
            with patch.object(module.httpx, "post") as broker_post:
                blocked = module.execute_task(module.TaskExecution(
                    action="open_app", params={"app_name": "notepad"}, dry_run=False,
                    idempotency_key="phase0-test-0001",
                ))
            self.assertEqual(blocked["status"], "not_dispatched")
            self.assertEqual(blocked["error_class"], "unavailable")
            broker_post.assert_not_called()
            health = module.phase0_health()
            self.assertEqual(health["checks"]["capability_contract"], True)
            self.assertIn(health["status"], {"ready", "blocked"})
            with patch.object(module.httpx, "post", side_effect=module.httpx.ConnectError("offline")):
                stopped = module.turn(module.TurnRequest(message="Mica Not-Aus", client="pyqt"))
            self.assertEqual(stopped["state"], "stopped")
            self.assertTrue(module.policy.is_emergency_stopped())
            local_request = module.Request({"type": "http", "headers": []})
            with (
                patch.object(module.approval_sessions, "valid", return_value=True),
                patch.object(module.httpx, "post", side_effect=module.httpx.ConnectError("offline")),
                self.assertRaises(module.HTTPException) as raised,
            ):
                module.emergency_stop(
                    module.EmergencyStopRequest(active=False), local_request,
                    x_mica_approval_intent="confirm",
                )
            self.assertEqual(raised.exception.status_code, 503)
            self.assertTrue(module.policy.is_emergency_stopped())


if __name__ == "__main__":
    unittest.main(verbosity=2)
