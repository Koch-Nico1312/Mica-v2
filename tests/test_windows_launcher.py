from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from mica_core import windows_launcher


class WindowsLauncherTests(unittest.TestCase):
    def test_loads_only_allowlisted_credential_names_without_writing_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "names.json"
            config.write_text(json.dumps({"MICA_PUSH_TOKEN": "PUSH_TOKEN"}), encoding="utf-8")
            with patch.object(windows_launcher, "get_secret", return_value="secret-value"):
                result = windows_launcher.credential_environment(config)
            self.assertEqual(result, {"MICA_PUSH_TOKEN": "secret-value"})
            self.assertNotIn("secret-value", config.read_text(encoding="utf-8"))

    def test_rejects_arbitrary_environment_variables(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "names.json"
            config.write_text('{"PATH":"NOT_ALLOWED"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported"):
                windows_launcher.credential_environment(config)

    def test_cloud_provider_keys_use_the_same_credential_manager_boundary(self):
        names = {
            "OPENAI_API_KEY": "MICA_OPENAI_API_KEY",
            "GEMINI_API_KEY": "MICA_GEMINI_API_KEY",
        }
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "names.json"
            config.write_text(json.dumps(names), encoding="utf-8")
            with patch.object(windows_launcher, "get_secret", side_effect=lambda name: f"value-for-{name}"):
                result = windows_launcher.credential_environment(config)

        self.assertEqual(set(result), set(names))
        self.assertTrue(all(value.startswith("value-for-") for value in result.values()))

    def test_phase4_overlay_is_used_when_present(self):
        completed = Mock(returncode=0)
        with patch.object(windows_launcher, "credential_environment", return_value={}), \
             patch.object(windows_launcher, "_docker_executable", return_value="docker"), \
             patch.object(windows_launcher.Path, "is_file", return_value=True), \
             patch.object(windows_launcher.subprocess, "run", return_value=completed) as run:
            self.assertEqual(windows_launcher.run_compose(Path("names.json"), ["config"]), 0)

        command = run.call_args.args[0]
        self.assertEqual(
            command[:8],
            ["docker", "compose", "--env-file", ".env", "--env-file", ".env.phase4", "config"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
