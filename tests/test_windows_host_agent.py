from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.action_adapters import ActionUnavailable, ENTRYPOINTS, execute, execution_availability
from backend.services.common.capabilities import CAPABILITIES


class ActionAdapterContractTests(unittest.TestCase):
    def test_every_registered_capability_has_an_explicit_adapter_or_builtin(self):
        builtins = {"manage_monitor", "proactive", "system_status"}
        registered = {item.action for item in CAPABILITIES}
        self.assertEqual(set(ENTRYPOINTS) | builtins, registered)

    def test_actions_are_disabled_by_default_and_cloud_legacy_fails_closed(self):
        self.assertEqual(
            execution_availability("open_app", {"app_name": "notepad"}, {}),
            (False, "action_not_enabled_on_windows_host"),
        )
        env = {"MICA_WINDOWS_ENABLED_ACTIONS": "code_helper,file_processor"}
        self.assertEqual(
            execution_availability("code_helper", {"action": "explain"}, env),
            (False, "operation_requires_local_replacement"),
        )
        self.assertEqual(execution_availability("code_helper", {"action": "run"}, env), (True, "available"))
        self.assertEqual(execution_availability("file_processor", {"action": "info"}, env), (True, "available"))

    def test_arbitrary_network_target_and_recipient_fail_closed(self):
        browser_env = {
            "MICA_WINDOWS_ENABLED_ACTIONS": "browser_control",
            "MICA_CAPABILITY_BROWSER_CONTROL_NETWORK": "true",
            "MICA_CAPABILITY_BROWSER_CONTROL_TARGETS": "example.com",
        }
        self.assertEqual(
            execution_availability("browser_control", {"action": "go_to", "url": "https://evil.example/"}, browser_env),
            (False, "network_target_not_allowlisted"),
        )
        message_env = {
            "MICA_WINDOWS_ENABLED_ACTIONS": "send_message",
            "MICA_CAPABILITY_SEND_MESSAGE_NETWORK": "true",
            "MICA_CAPABILITY_SEND_MESSAGE_TARGETS": "whatsapp.com",
            "MICA_CAPABILITY_SEND_MESSAGE_RECIPIENTS": "Test User",
        }
        self.assertEqual(
            execution_availability("send_message", {"receiver": "Other User"}, message_env),
            (False, "recipient_not_allowlisted"),
        )

    def test_internal_network_target_must_match_the_operator_allowlist(self):
        weather_env = {
            "MICA_WINDOWS_ENABLED_ACTIONS": "weather_report",
            "MICA_CAPABILITY_WEATHER_REPORT_NETWORK": "true",
            "MICA_CAPABILITY_WEATHER_REPORT_TARGETS": "example.com",
        }
        self.assertEqual(
            execution_availability("weather_report", {"action": "get", "city": "Wien"}, weather_env),
            (False, "network_target_not_allowlisted"),
        )
        weather_env["MICA_CAPABILITY_WEATHER_REPORT_TARGETS"] = "www.google.com"
        self.assertEqual(
            execution_availability("weather_report", {"action": "get", "city": "Wien"}, weather_env),
            (True, "available"),
        )

    def test_legacy_gemini_web_search_is_never_dispatched(self):
        env = {
            "MICA_WINDOWS_ENABLED_ACTIONS": "web_search",
            "MICA_CAPABILITY_WEB_SEARCH_NETWORK": "true",
            "MICA_CAPABILITY_WEB_SEARCH_TARGETS": "duckduckgo.com",
        }
        self.assertEqual(
            execution_availability("web_search", {"mode": "search", "query": "Mica"}, env),
            (False, "operation_requires_local_replacement"),
        )

    def test_dev_agent_inspects_only_an_allowlisted_project_without_reading_contents(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            project.mkdir()
            (project / "main.py").write_text("secret = 'never returned'", encoding="utf-8")
            env = {
                "MICA_WINDOWS_ENABLED_ACTIONS": "dev_agent",
                "MICA_WINDOWS_ALLOWED_ROOTS": temporary,
            }
            result = execute("dev_agent", {"action": "inspect", "project_path": str(project)}, env)
            self.assertEqual(result["output"]["file_count"], 1)
            self.assertFalse(result["output"]["contents_read"])
            self.assertNotIn("secret", str(result))

    def test_file_paths_fail_closed_without_an_allowlisted_root(self):
        env = {"MICA_WINDOWS_ENABLED_ACTIONS": "file_processor"}
        self.assertEqual(
            execution_availability("file_processor", {"action": "info", "file_path": "C:/data/a.txt"}, env),
            (False, "local_path_allowlist_missing"),
        )

    def test_application_launch_requires_an_exact_allowlist_entry(self):
        base = {"MICA_WINDOWS_ENABLED_ACTIONS": "open_app"}
        self.assertEqual(
            execution_availability("open_app", {"app_name": "notepad"}, base),
            (False, "app_allowlist_missing"),
        )
        allowed = {**base, "MICA_WINDOWS_ALLOWED_APPS": "notepad,calculator"}
        self.assertEqual(
            execution_availability("open_app", {"app_name": "cmd"}, allowed),
            (False, "app_not_allowlisted"),
        )
        self.assertEqual(
            execution_availability("open_app", {"app_name": "Notepad"}, allowed),
            (True, "available"),
        )

    def test_screen_processor_returns_only_ephemeral_metadata(self):
        class Capture:
            monitors = [{"left": 0}, {"left": 0}]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            @staticmethod
            def grab(_monitor):
                return SimpleNamespace(rgb=b"\x01\x02\x03" * 4, width=2, height=2)

        fake_mss = SimpleNamespace(mss=Capture)
        env = {"MICA_WINDOWS_ENABLED_ACTIONS": "screen_processor"}
        with patch.dict(sys.modules, {"mss": fake_mss}):
            result = execute("screen_process", {"action": "capture_metadata", "monitor": 1}, env)
        self.assertEqual(result["output"]["width"], 2)
        self.assertFalse(result["output"]["persisted"])
        self.assertEqual(len(result["output"]["sha256"]), 64)

    def test_screen_processor_reports_a_missing_local_dependency(self):
        env = {"MICA_WINDOWS_ENABLED_ACTIONS": "screen_processor"}
        with patch.dict(sys.modules, {"mss": None}), self.assertRaisesRegex(
            ActionUnavailable, "missing_dependency:mss",
        ):
            execute("screen_process", {"action": "capture_metadata"}, env)

    def test_legacy_adapter_import_failure_is_reported_as_unavailable(self):
        env = {"MICA_WINDOWS_ENABLED_ACTIONS": "reminder"}
        missing = ModuleNotFoundError("No module named optional_runtime", name="optional_runtime")
        with patch("core.action_adapters.importlib.import_module", side_effect=missing), self.assertRaisesRegex(
            ActionUnavailable, "missing_dependency:optional_runtime",
        ):
            execute("reminder", {"action": "create"}, env)


class WindowsHostAgentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.environment = {
            "MICA_WINDOWS_AGENT_CONFIG": str(root / "config.json"),
            "MICA_WINDOWS_AGENT_REPLAY_DB": str(root / "replay.sqlite3"),
            "MICA_WINDOWS_AGENT_STOP_STATE": str(root / "stop.json"),
            "MICA_WINDOWS_ENABLED_ACTIONS": "system_status,open_app",
            "MICA_WINDOWS_ALLOWED_APPS": "notepad",
        }
        (root / "config.json").write_text(
            '{"trusted_broker_subject":"CN=mica-tool-broker",'
            '"allow_broker_resume":false,"allowed_actions":["system_status","open_app"]}',
            encoding="utf-8",
        )
        self.env_patch = patch.dict(os.environ, self.environment, clear=False)
        self.env_patch.start()
        import backend.windows_host_agent.app as module
        self.module = importlib.reload(module)

    def tearDown(self):
        self.env_patch.stop()
        self.temporary.cleanup()

    def request(self, scope: str, *, approval_id: str | None = None):
        return self.module.ScopedRequest(
            request_id=uuid.uuid4().hex,
            scope=scope,
            params={"app_name": "notepad"} if scope == "open_app" else {},
            approval_id=approval_id,
            expires_at=(datetime.now(UTC) + timedelta(seconds=60)).isoformat(),
        )

    def test_execute_rejects_unverified_or_wrong_certificate(self):
        with self.assertRaisesRegex(Exception, "mutually authenticated"):
            self.module.execute(self.request("system_status"), None, None)
        with self.assertRaisesRegex(Exception, "Untrusted broker"):
            self.module.execute(self.request("system_status"), "SUCCESS", "CN=other")

    def test_non_read_action_requires_approval_before_dispatch(self):
        with self.assertRaisesRegex(Exception, "parameter-bound"):
            self.module.execute(
                self.request("open_app"), "SUCCESS", "CN=mica-tool-broker"
            )

    def test_request_id_is_claimed_once(self):
        request = self.request("system_status")
        with patch.object(self.module, "_run_action", return_value={"ok": True, "result": {}}):
            first = self.module.execute(request, "SUCCESS", "CN=mica-tool-broker")
            self.assertEqual(first["request_id"], request.request_id)
            with self.assertRaisesRegex(Exception, "Replayed"):
                self.module.execute(request, "SUCCESS", "CN=mica-tool-broker")

    def test_remote_resume_is_disabled_by_default(self):
        with self.assertRaisesRegex(Exception, "Remote resume is disabled"):
            self.module.emergency_stop(
                self.module.StopRequest(active=False), "SUCCESS", "CN=mica-tool-broker"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
