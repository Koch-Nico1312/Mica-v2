from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from actions.cua_driver import (
    CONFIRM_COMMANDS,
    MAX_TIMEOUT_SECONDS,
    MIN_TIMEOUT_SECONDS,
    _bounded_timeout,
    _run_driver,
    driver_available,
    enabled,
    native_app_control,
    status,
)


class CuaDriverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous = os.environ.get("MICA_CUA_ENABLED")
        os.environ.pop("MICA_CUA_ENABLED", None)

    def tearDown(self) -> None:
        if self.previous is None:
            os.environ.pop("MICA_CUA_ENABLED", None)
        else:
            os.environ["MICA_CUA_ENABLED"] = self.previous

    def test_disabled_by_default(self) -> None:
        self.assertFalse(enabled())
        self.assertFalse(status()["available"])

    def test_unknown_action_is_refused_before_any_detection(self) -> None:
        result = native_app_control({"action": "format_disk"})
        self.assertIn("unknown action", result)

    def test_disabled_gives_guidance(self) -> None:
        result = native_app_control({"action": "focus", "app": "Notepad"})
        self.assertIn("disabled", result)

    def test_missing_driver_fails_closed(self) -> None:
        os.environ["MICA_CUA_ENABLED"] = "1"
        with patch("actions.cua_driver.driver_available", return_value=None):
            result = native_app_control({"action": "type", "app": "Notepad", "text": "hi"})
        self.assertIn("driver not installed", result)
        self.assertIn("install.ps1", result)

    def test_safe_action_dispatches_to_driver(self) -> None:
        os.environ["MICA_CUA_ENABLED"] = "1"
        calls: list[list[str]] = []

        def fake_run(driver: str, args: list[str], timeout: int) -> str:
            calls.append(args)
            return "focused"

        with patch("actions.cua_driver.driver_available", return_value="cua"), \
             patch("actions.cua_driver._run_driver", side_effect=fake_run):
            result = native_app_control({"action": "focus", "app": "Notepad"})
        self.assertEqual(result, "focused")
        self.assertEqual(calls, [["apps", "focus", "Notepad"]])

    def test_close_requires_confirmation_and_never_runs_directly(self) -> None:
        os.environ["MICA_CUA_ENABLED"] = "1"
        ran: list[str] = []

        def gate(key: str, title: str, detail: str, run) -> str:
            ran.append(key)
            return f"[CONFIRMATION_PENDING] {title}"

        with patch("actions.cua_driver.driver_available", return_value="cua"), \
             patch("actions.cua_driver._run_driver", side_effect=AssertionError("must not run")):
            result = native_app_control({"action": "close", "app": "Notepad"}, confirm_request=gate)
        self.assertIn("CONFIRMATION_PENDING", result)
        self.assertEqual(ran, ["cua-close:Notepad"])

    def test_timeout_is_clamped_into_a_bounded_window(self) -> None:
        self.assertEqual(_bounded_timeout(15), 15)
        self.assertEqual(_bounded_timeout(10_000), MAX_TIMEOUT_SECONDS)
        self.assertEqual(_bounded_timeout(1), MIN_TIMEOUT_SECONDS)
        self.assertEqual(_bounded_timeout("junk"), MIN_TIMEOUT_SECONDS)
        self.assertEqual(_bounded_timeout(None), MIN_TIMEOUT_SECONDS)

    def test_run_driver_uses_the_clamped_timeout(self) -> None:
        captured: dict = {}

        class Completed:
            returncode = 0
            stdout = "ok"
            stderr = ""

        def fake_run(args, **kwargs):
            captured.update(kwargs)
            return Completed()

        with patch("actions.cua_driver.subprocess.run", side_effect=fake_run):
            self.assertEqual(_run_driver("cua", ["apps", "list"], 99_999), "ok")
        self.assertEqual(captured["timeout"], MAX_TIMEOUT_SECONDS)

    def test_close_without_ui_gate_is_refused(self) -> None:
        os.environ["MICA_CUA_ENABLED"] = "1"
        # Headless environment: core.confirm has no UI bound, so request()
        # refuses. The close command must surface that refusal verbatim.
        with patch("actions.cua_driver.driver_available", return_value="cua"), \
             patch("actions.cua_driver._run_driver", side_effect=AssertionError("must not run")):
            result = native_app_control({"action": "close", "app": "Notepad"}, confirm_request=None)
        self.assertIn("not", result.lower())
        self.assertIn("confirm", result.lower())


if __name__ == "__main__":
    unittest.main()
