from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Phase0ProductionBoundaryTests(unittest.TestCase):
    def test_canonical_windows_entrypoint_has_no_direct_cloud_or_action_dispatch(self):
        source = (ROOT / "local_main.py").read_text(encoding="utf-8").lower()
        launcher = (ROOT / "install_and_start.ps1").read_text(encoding="utf-8").lower()
        self.assertNotIn("gemini", source)
        self.assertNotIn("google.genai", source)
        self.assertNotIn("from actions", source)
        self.assertNotIn("import actions", source)
        self.assertIn('"local_main.py"', launcher)

    def test_phase0_dependency_lock_excludes_legacy_cloud_and_qr_packages(self):
        lock = (ROOT / "requirements-phase0.lock").read_text(encoding="utf-8").lower()
        for package in ("google-genai", "google-generativeai", "qrcode"):
            with self.subTest(package=package):
                self.assertNotIn(package, lock)

    def test_owner_pwa_contains_no_removed_product_surfaces(self):
        pwa = (ROOT / "mica_core" / "web_ui" / "index.html").read_text(encoding="utf-8").lower()
        for removed in ("qr code", "qrcode", "pairing", "marketplace", "multi-tenant", "multitenant"):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, pwa)

    def test_smart_home_is_not_in_the_phase0_capability_registry(self):
        registry = (ROOT / "mica_core" / "services" / "common" / "capabilities.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("smart_home", registry)
        self.assertNotIn("smarthome", registry)

    def test_windows_stop_marker_uses_the_exact_durable_programdata_name(self):
        host = (ROOT / "mica_core" / "windows_host_agent" / "app.py").read_text(encoding="utf-8")
        self.assertIn('PROGRAM_DATA / "EMERGENCY_STOP"', host)
        self.assertIn('LEGACY_STOP_PATH = PROGRAM_DATA / "EMERGENCY_STOP.json"', host)


if __name__ == "__main__":
    unittest.main(verbosity=2)
