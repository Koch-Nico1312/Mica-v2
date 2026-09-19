from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch


HOST_AGENT_ROOT = Path(__file__).resolve().parents[1] / "mica_core" / "host_agent"
sys.path.insert(0, str(HOST_AGENT_ROOT))


class HostAgentSafetyTests(unittest.TestCase):
    @staticmethod
    def _request(module, scope: str, params: dict, *, approved: bool = True):
        return module.ScopedRequest(
            request_id=uuid.uuid4().hex,
            scope=scope,
            params=params,
            approval_id="a" * 32 if approved else None,
            expires_at=(datetime.now(UTC) + timedelta(seconds=60)).isoformat(),
        )

    def test_emergency_stop_survives_a_process_reload_and_must_be_explicitly_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            config.write_text(json.dumps({
                "trusted_broker_subject": "mica-tool-broker",
                "allowed_scopes": [],
            }), encoding="utf-8")
            with patch.dict(os.environ, {
                "MICA_HOST_AGENT_CONFIG": str(config),
                "MICA_HOST_AGENT_STOP_STATE": str(root / "emergency-stop.json"),
                "MICA_HOST_AGENT_REPLAY_DB": str(root / "replay.sqlite3"),
            }, clear=False):
                module = importlib.import_module("app")
                module = importlib.reload(module)
                result = module.emergency_stop(
                    {"active": True}, "SUCCESS", "mica-tool-broker",
                )
                self.assertTrue(result["active"])
                self.assertEqual(module.health()["status"], "stopped")

                # Reload models a new host-agent process reading durable state.
                module = importlib.reload(module)
                self.assertEqual(module.health()["status"], "stopped")
                module.emergency_stop({"active": False}, "SUCCESS", "mica-tool-broker")
                module = importlib.reload(module)
                self.assertEqual(module.health()["status"], "ok")

    def test_non_active_code_revision_is_rejected_before_docker_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "active.json").write_text(
                json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8",
            )
            config = root / "config.json"
            config.write_text(json.dumps({
                "trusted_broker_subject": "mica-tool-broker",
                "improvement_runtime_root": str(runtime),
                "allowed_scopes": ["improvement.invoke"],
            }), encoding="utf-8")
            with patch.dict(os.environ, {
                "MICA_HOST_AGENT_CONFIG": str(config),
                "MICA_HOST_AGENT_STOP_STATE": str(root / "emergency-stop.json"),
            }, clear=False):
                module = importlib.import_module("app")
                module = importlib.reload(module)
                with self.assertRaises(module.HTTPException) as raised:
                    module._invoke_active_improvement("a" * 32, {})
                self.assertEqual(raised.exception.status_code, 403)

    def test_destructive_scope_requires_broker_approval_at_host_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            config.write_text(json.dumps({
                "trusted_broker_subject": "mica-tool-broker",
                "allowed_scopes": ["docker.lifecycle"],
                "allowed_containers": ["mica-api"],
            }), encoding="utf-8")
            with patch.dict(os.environ, {
                "MICA_HOST_AGENT_CONFIG": str(config),
                "MICA_HOST_AGENT_STOP_STATE": str(root / "emergency-stop.json"),
                "MICA_HOST_AGENT_REPLAY_DB": str(root / "replay.sqlite3"),
            }, clear=False):
                module = importlib.reload(importlib.import_module("app"))
                request = self._request(
                    module, "docker.lifecycle",
                    {"operation": "stop", "container": "mica-api"},
                    approved=False,
                )
                with patch.object(module, "_docker") as docker_call, self.assertRaises(module.HTTPException) as raised:
                    module.execute(request, "SUCCESS", "mica-tool-broker")
                self.assertEqual(raised.exception.status_code, 403)
                docker_call.assert_not_called()

    def test_file_delete_is_a_recoverable_move_to_configured_trash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "note.txt"
            source.write_text("recover me", encoding="utf-8")
            config = root / "config.json"
            config.write_text(json.dumps({
                "trusted_broker_subject": "mica-tool-broker",
                "files_root": str(root),
                "trash_root": str(root / ".trash"),
                "allowed_scopes": ["files.delete", "files.move"],
            }), encoding="utf-8")
            with patch.dict(os.environ, {
                "MICA_HOST_AGENT_CONFIG": str(config),
                "MICA_HOST_AGENT_STOP_STATE": str(root / "emergency-stop.json"),
                "MICA_HOST_AGENT_REPLAY_DB": str(root / "replay.sqlite3"),
            }, clear=False):
                module = importlib.reload(importlib.import_module("app"))
                result = module.execute(
                    self._request(module, "files.delete", {"path": str(source)}),
                    "SUCCESS", "mica-tool-broker",
                )
                trashed = Path(result["trashed_to"])
                self.assertFalse(source.exists())
                self.assertEqual(trashed.read_text(encoding="utf-8"), "recover me")
                self.assertTrue(result["recoverable"])
                undo = result["undo"]
                module.execute(
                    self._request(module, "files.move", {"from": undo["from"], "to": undo["to"]}),
                    "SUCCESS", "mica-tool-broker",
                )
                self.assertEqual(source.read_text(encoding="utf-8"), "recover me")

    def test_network_change_uses_only_operator_owned_argv(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            config.write_text(json.dumps({
                "trusted_broker_subject": "mica-tool-broker",
                "allowed_scopes": ["network.change"],
                "network_profiles": {
                    "lan-primary": {
                        "up": [sys.executable, "-c", "print('profile-up')"],
                        "down": [sys.executable, "-c", "print('profile-down')"],
                    },
                },
            }), encoding="utf-8")
            with patch.dict(os.environ, {
                "MICA_HOST_AGENT_CONFIG": str(config),
                "MICA_HOST_AGENT_STOP_STATE": str(root / "emergency-stop.json"),
                "MICA_HOST_AGENT_REPLAY_DB": str(root / "replay.sqlite3"),
            }, clear=False):
                module = importlib.reload(importlib.import_module("app"))
                manipulated = self._request(module, "network.change", {
                    "profile": "lan-primary", "state": "up", "command": "anything",
                })
                with self.assertRaises(module.HTTPException) as raised:
                    module.execute(manipulated, "SUCCESS", "mica-tool-broker")
                self.assertEqual(raised.exception.status_code, 422)

                result = module.execute(
                    self._request(module, "network.change", {"profile": "lan-primary", "state": "up"}),
                    "SUCCESS", "mica-tool-broker",
                )
                self.assertEqual(result["output"].strip(), "profile-up")
                self.assertEqual(result["undo"]["state"], "down")


if __name__ == "__main__":
    unittest.main(verbosity=2)
