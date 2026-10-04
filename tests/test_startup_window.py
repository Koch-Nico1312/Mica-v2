import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import time
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication

from desktop.startup_window import StartupWindow


class StartupWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def finish(self, window):
        deadline = time.monotonic() + 3
        while window.outcome is None or window.worker.isRunning():
            self.app.processEvents()
            if time.monotonic() >= deadline:
                self.fail("Startup worker did not finish")
            time.sleep(0.005)
        self.app.processEvents()

    def test_failed_start_can_retry_without_exposing_secrets(self):
        attempts = []

        def starter(progress):
            attempts.append(True)
            progress("services")
            if len(attempts) == 1:
                raise RuntimeError("secret-password")
            return {"status": "ready"}

        window = StartupWindow(starter, Path(__file__).resolve().parents[1])
        window.show()
        window.begin()
        self.finish(window)
        self.assertEqual(window.outcome, "failed")
        self.assertNotIn("secret-password", window.detail.text())
        self.assertIn("Modelle", window.detail.text())
        self.assertFalse(window.retry.isHidden())
        self.assertTrue(window.continue_button.isHidden())
        window.retry.click()
        self.finish(window)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(window.result(), window.DialogCode.Accepted)
        window.close()

    def test_blocked_capabilities_require_explicit_continue(self):
        window = StartupWindow(lambda progress: {"status": "blocked"}, Path.cwd())
        window.show()
        window.begin()
        self.finish(window)
        self.assertEqual(window.outcome, "limited")
        self.assertEqual(window.result(), window.DialogCode.Rejected)
        self.assertFalse(window.continue_button.isHidden())
        window.continue_button.click()
        self.assertEqual(window.result(), window.DialogCode.Accepted)
        window.close()

    def test_recovery_action_matches_failed_stage(self):
        window = StartupWindow(lambda progress: {}, Path.cwd())
        with patch("desktop.startup_window.QDesktopServices.openUrl") as open_url:
            window.set_stage("services")
            window.open_help()
            open_url.assert_called_with(QUrl("docker-desktop://dashboard"))
            window.set_stage("connection")
            window.open_help()
            open_url.assert_called_with(QUrl.fromLocalFile(str(Path.cwd() / "backend")))
        window.close()

