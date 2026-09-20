from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.self_source as self_source


class SelfSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "core").mkdir(parents=True, exist_ok=True)
        (self.root / "config").mkdir(parents=True, exist_ok=True)
        (self.root / "core" / "example.py").write_text(
            "DEFAULT_TOKENS = 256\n\n\ndef answer():\n    return DEFAULT_TOKENS\n", encoding="utf-8",
        )
        (self.root / ".env.example").write_text(
            "MODEL_ROUTER_BUDGET_HOURLY=1.0\nGEMINI_API_KEY=template\n", encoding="utf-8",
        )
        (self.root / ".env").write_text(
            "MODEL_ROUTER_BUDGET_HOURLY=1.0\nGEMINI_API_KEY=super-secret-value\n", encoding="utf-8",
        )
        (self.root / "config" / "api_keys.json").write_text(
            json.dumps({"gemini_api_key": "also-secret", "assistant_name": "MICA"}), encoding="utf-8",
        )
        self.previous = {key: os.environ.get(key) for key in ("MICA_SELF_ROOT", "MICA_SELF_EDIT_ENABLED")}
        os.environ["MICA_SELF_ROOT"] = str(self.root)
        os.environ.pop("MICA_SELF_EDIT_ENABLED", None)

    def tearDown(self) -> None:
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temporary.cleanup()

    # ── Reading ──────────────────────────────────────────────────────────────

    def test_read_source_returns_file_content(self) -> None:
        data = self_source.read_source("core/example.py")
        self.assertIn("DEFAULT_TOKENS = 256", data["content"])
        self.assertEqual(data["path"], "core/example.py")

    def test_path_trap_blocks_escaping_the_installation(self) -> None:
        with self.assertRaises(ValueError):
            self_source.read_source("../outside.py")
        with self.assertRaises(ValueError):
            self_source.read_source("core/../../secrets.py")

    def test_secrets_are_masked_in_env_and_json_reads(self) -> None:
        env = self_source.read_source(".env")
        self.assertIn("GEMINI_API_KEY=***gesetzt***", env["content"])
        self.assertNotIn("super-secret-value", env["content"])
        config = self_source.read_source("config/api_keys.json")
        self.assertNotIn("also-secret", config["content"])
        self.assertIn("***gesetzt***", config["content"])
        self.assertIn("MICA", config["content"])  # non-secret values stay readable

    def test_search_finds_terms_with_line_numbers(self) -> None:
        hits = self_source.search_source("DEFAULT_TOKENS", extensions=["py"])
        self.assertEqual(hits[0]["path"], "core/example.py")
        self.assertEqual(hits[0]["line"], 1)
        with self.assertRaises(ValueError):
            self_source.search_source("x")

    # ── Settings ─────────────────────────────────────────────────────────────

    def test_list_settings_masks_secret_values(self) -> None:
        data = self_source.list_settings()
        by_key = {item["key"]: item for item in data["settings"]}
        self.assertEqual(by_key["MODEL_ROUTER_BUDGET_HOURLY"]["value"], "1.0")
        self.assertEqual(by_key["GEMINI_API_KEY"]["value"], "***gesetzt***")

    def test_preview_setting_writes_nothing(self) -> None:
        before = (self.root / ".env").read_text(encoding="utf-8")
        preview = self_source.preview_setting("MODEL_ROUTER_BUDGET_HOURLY", "2.5")
        self.assertEqual(preview["file"], ".env")
        self.assertIn("2.5", preview["diff"])
        self.assertEqual(before, (self.root / ".env").read_text(encoding="utf-8"))

    def test_apply_setting_updates_value_and_creates_backup(self) -> None:
        result = self_source.apply_setting("MODEL_ROUTER_BUDGET_HOURLY", "2.5")
        self.assertTrue(result["written"])
        content = (self.root / ".env").read_text(encoding="utf-8")
        self.assertIn("MODEL_ROUTER_BUDGET_HOURLY=2.5", content)
        self.assertIn("GEMINI_API_KEY=super-secret-value", content)  # untouched
        backup = self.root / "memory" / "self-edits" / result["backup"]
        self.assertIn("MODEL_ROUTER_BUDGET_HOURLY=1.0", backup.read_text(encoding="utf-8"))
        history = self_source.edit_history()
        self.assertEqual(history[0]["file"], ".env")

    def test_unknown_setting_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self_source.preview_setting("NOT_A_REAL_SETTING", "1")

    # ── Source edits ─────────────────────────────────────────────────────────

    def test_source_edit_disabled_by_default(self) -> None:
        result = self_source.apply_source_edit("core/example.py", "DEFAULT_TOKENS = 256", "DEFAULT_TOKENS = 512")
        self.assertFalse(result["written"])
        self.assertIn("MICA_SELF_EDIT_ENABLED", result["reason"])
        self.assertIn("DEFAULT_TOKENS = 256", (self.root / "core" / "example.py").read_text(encoding="utf-8"))

    def test_source_edit_requires_unique_match(self) -> None:
        with self.assertRaises(ValueError):
            self_source.preview_source_edit("core/example.py", "DEFAULT_TOKENS", "TOKENS")

    def test_source_edit_rejects_invalid_python(self) -> None:
        with self.assertRaises(ValueError):
            self_source.preview_source_edit("core/example.py", "return DEFAULT_TOKENS", "return ((")

    def test_source_edit_applies_with_backup_when_enabled(self) -> None:
        os.environ["MICA_SELF_EDIT_ENABLED"] = "1"
        result = self_source.apply_source_edit("core/example.py", "DEFAULT_TOKENS = 256", "DEFAULT_TOKENS = 512")
        self.assertTrue(result["written"])
        self.assertIn("DEFAULT_TOKENS = 512", (self.root / "core" / "example.py").read_text(encoding="utf-8"))
        backup = self.root / "memory" / "self-edits" / result["backup"]
        self.assertIn("DEFAULT_TOKENS = 256", backup.read_text(encoding="utf-8"))

    # ── Tool entry point ─────────────────────────────────────────────────────

    def test_tool_reads_and_previews(self) -> None:
        self.assertIn("DEFAULT_TOKENS = 256", self_source.self_source_action({"action": "read", "path": "core/example.py"}))
        self.assertIn("2.5", self_source.self_source_action(
            {"action": "preview_setting", "key": "MODEL_ROUTER_BUDGET_HOURLY", "value": "2.5"},
        ))
        self.assertIn("Unbekannte Aktion", self_source.self_source_action({"action": "nonsense"}))

    def test_writes_go_through_the_confirmation_gate(self) -> None:
        calls: list[str] = []

        def gate(key: str, title: str, detail: str, run) -> str:
            calls.append(key)
            return "[CONFIRMATION_PENDING] warte auf Bestätigung"

        result = self_source.self_source_action(
            {"action": "apply_setting", "key": "MODEL_ROUTER_BUDGET_HOURLY", "value": "3.0"},
            confirm_request=gate,
        )
        self.assertIn("CONFIRMATION_PENDING", result)
        self.assertEqual(calls, ["self-source:apply_setting:MODEL_ROUTER_BUDGET_HOURLY"])
        # Nothing was written before the user confirms.
        self.assertIn("MODEL_ROUTER_BUDGET_HOURLY=1.0", (self.root / ".env").read_text(encoding="utf-8"))

    def test_write_without_ui_gate_is_refused(self) -> None:
        import core.confirm as confirm_gate

        with patch.object(confirm_gate, "request", None):
            result = self_source.self_source_action(
                {"action": "apply_setting", "key": "MODEL_ROUTER_BUDGET_HOURLY", "value": "3.0"},
            )
        self.assertIn("nichts geändert", result)


if __name__ == "__main__":
    unittest.main()
