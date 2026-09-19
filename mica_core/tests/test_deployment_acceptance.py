"""Fast local checks for deployment claims that do not need a ZimaOS host."""
from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))

from services.common.health import fresh, reset, touch


class WorkerHealthMarkerTests(unittest.TestCase):
    def test_marker_is_atomic_readable_and_expires(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            "os.environ", {"MICA_HEALTH_DIR": temporary}, clear=False
        ):
            self.assertFalse(fresh("scheduler", 1))
            touch("scheduler")
            self.assertTrue(fresh("scheduler", 1))
            reset("scheduler")
            self.assertFalse(fresh("scheduler", 1))
            touch("scheduler")
            time.sleep(0.02)
            self.assertFalse(fresh("scheduler", 0.001))


class ComposeAcceptanceTests(unittest.TestCase):
    def test_mandatory_dependency_and_worker_health_contract(self):
        compose = (CORE / "docker-compose.yml").read_text(encoding="utf-8")
        for service in ("llama-server", "stt", "tts", "brain-index", "tool-broker", "scheduler"):
            self.assertIn(f"      {service}:\n        condition: service_healthy", compose)
        self.assertIn("fresh('brain-index', 45)", compose)
        self.assertIn("fresh('scheduler', 75)", compose)
        self.assertNotIn("import os; os.kill(1, 0)", compose)


if __name__ == "__main__":
    unittest.main()
