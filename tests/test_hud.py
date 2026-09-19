"""Offscreen checks for the MICA HUD's user-facing contracts."""
from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QMimeData, QPointF, Qt, QUrl
from PyQt6.QtGui import QDropEvent
from PyQt6.QtWidgets import QApplication

import ui


class HudTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.config_check = mock.patch.object(ui.MainWindow, "_check_config", return_value=True)
        self.config_check.start()
        self.window = ui.MainWindow("")

    def tearDown(self):
        self.window.close()
        self.config_check.stop()

    def test_navigation_switches_between_chat_history_and_settings(self):
        self.window._activate_navigation("history")
        self.assertEqual(self.window._view_stack.currentIndex(), 1)
        self.assertFalse(self.window._footer.isVisible())
        self.window._activate_navigation("chat")
        self.assertEqual(self.window._view_stack.currentIndex(), 0)
        self.assertFalse(self.window._footer.isHidden())
        self.window._activate_navigation("settings")
        self.assertEqual(self.window._view_stack.currentIndex(), 4)
        self.assertTrue(self.window._quick_drawer.isHidden())

    def test_state_mute_and_live_audio_are_kept_in_sync(self):
        self.window._apply_state("THINKING")
        self.assertEqual(self.window.hud.state, "THINKING")
        self.window._apply_audio_level(.8)
        self.assertGreaterEqual(self.window._ctx_audio._level, .8)
        self.window._toggle_mute()
        self.assertTrue(self.window._muted)
        self.assertTrue(self.window.hud.muted)
        self.assertTrue(self.window._ctx_audio._muted)

    def test_send_and_file_drop_reach_existing_entry_points(self):
        received: list[str] = []
        arrived = threading.Event()

        def command(text: str) -> None:
            received.append(text)
            arrived.set()

        self.window.on_text_command = command
        self.window._input.setText("Hallo Mica")
        self.window._send()
        self.assertTrue(arrived.wait(1))
        self.assertEqual(received, ["Hallo Mica"])

        with tempfile.NamedTemporaryFile(delete=False) as handle:
            dropped_path = handle.name
        try:
            mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(dropped_path)])
            event = QDropEvent(QPointF(4, 4), Qt.DropAction.CopyAction, mime,
                               Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
            self.window._input.dropEvent(event)
            self.assertEqual(Path(self.window._current_file or "").resolve(), Path(dropped_path).resolve())
        finally:
            Path(dropped_path).unlink(missing_ok=True)

    def test_context_empty_state_never_invents_project_or_reminder(self):
        self.assertIsNone(ui.latest_project_context({"projects": {}}))
        newest = ui.latest_project_context({"projects": {
            "older": {"value": "Altes Projekt", "updated_at": "2026-09-04T09:00:00"},
            "newer": {"value": "Neues Projekt", "updated_at": "2026-09-04T10:00:00"},
        }})
        self.assertEqual(newest, ("Newer", "Neues Projekt"))
        self.window._update_metrics()
        self.assertEqual(self.window._ctx_project_title.text(), "Kein gespeichertes Projekt")


if __name__ == "__main__":
    unittest.main()
