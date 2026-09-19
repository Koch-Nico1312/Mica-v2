from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "mica_core"
sys.path.insert(0, str(ROOT))


class ActiveImprovementProfileTests(unittest.TestCase):
    def test_promoted_prompt_config_and_skill_change_the_live_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
            "BRAIN_DIR": str(Path(temp) / "brain"),
            "INDEX_PATH": str(Path(temp) / "index.sqlite3"),
            "AUDIT_PATH": str(Path(temp) / "audit.jsonl"),
            "APPROVAL_DB": str(Path(temp) / "approvals.sqlite3"),
            "SCHEDULE_DB": str(Path(temp) / "schedules.sqlite3"),
            "IMPROVEMENT_DB": str(Path(temp) / "improvements.sqlite3"),
            "IMPROVEMENT_WORKSPACE": str(Path(temp) / "improvement-workspace"),
            "CONNECTOR_DB": str(Path(temp) / "connectors.sqlite3"),
            "MICA_APPROVAL_SECRET": "local-test-secret",
        }, clear=False):
            module = importlib.import_module("services.api.app")
            module = importlib.reload(module)

            candidates = (
                ("mica-system-prompt", "prompt", "Antworte freundlich auf Deutsch."),
                ("mica-runtime-config", "config", '{"temperature":0.2,"chat_tokens":512,"voice_tokens":192}'),
                ("docker-diagnose", "skill", "Prüfe zuerst den Volume-Mount."),
            )
            for name, kind, content in candidates:
                proposal = module.improvements.propose(name, kind, content, "verified test evidence")
                self.assertTrue(module.improvements.evaluate(
                    proposal["id"], True, True, "tests passed", "health passed",
                ))
                self.assertTrue(module.improvements.promote(proposal["id"]), name)

            prompt, config, knowledge = module._active_assistant_profile()
            self.assertEqual(prompt, "Antworte freundlich auf Deutsch.")
            self.assertEqual(config, {"temperature": 0.2, "chat_tokens": 512, "voice_tokens": 192})
            self.assertIn("Prüfe zuerst den Volume-Mount.", knowledge)
            self.assertNotIn("policy", knowledge.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
