"""Focused PyQt contract tests for the Mica voice HUD."""
from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from actions import reminder
from ui import MainWindow, _MIN_H, _MIN_W, latest_project_context


class MicaHudTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow("assets/mica-orb.png")
        self.window._ready = True
        self.window._refresh_live_context("LISTENING")

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_navigation_switches_between_chat_history_and_settings(self):
        self.window._activate_navigation("history")
        self.assertEqual(self.window._view_stack.currentIndex(), 1)
        self.assertTrue(self.window._footer.isHidden())

        self.window._activate_navigation("chat")
        self.assertEqual(self.window._view_stack.currentIndex(), 0)
        self.assertFalse(self.window._footer.isHidden())

        self.window._activate_navigation("settings")
        self.assertEqual(self.window._view_stack.currentIndex(), 4)
        self.assertTrue(self.window._quick_drawer.isHidden())

    def test_states_and_mute_are_reflected_in_one_live_context(self):
        self.window._apply_state("LISTENING")
        self.assertEqual(self.window._ctx_live_title.text(), "Live")
        self.window._apply_state("THINKING")
        self.assertEqual(self.window._ctx_live_title.text(), "Mica denkt nach")
        self.window._apply_state("PROCESSING")
        self.assertEqual(self.window._ctx_live_title.text(), "Mica arbeitet")
        self.window._apply_state("SPEAKING")
        self.assertTrue(self.window.hud.speaking)
        self.assertEqual(self.window._ctx_live_title.text(), "Mica spricht")

        self.window._toggle_mute()
        self.assertTrue(self.window.hud.muted)
        self.assertTrue(self.window._ctx_audio._muted)
        self.assertIn("pausiert", self.window._ctx_live_title.text().lower())

    def test_public_muted_and_disconnected_states_keep_all_context_honest(self):
        # set_state is called from the assistant worker as well as from the
        # round UI control, so it must synchronise every visual audio surface.
        self.window._apply_state("MUTED")
        self.assertTrue(self.window._muted)
        self.assertTrue(self.window.hud.muted)
        self.assertTrue(self.window._ctx_audio._muted)
        self.assertTrue(self.window._composer_wave_left._muted)

        self.window._toggle_mute()
        self.window._apply_state("SLEEPING")
        self.assertEqual(self.window.hud.state, "SLEEPING")
        self.assertEqual(self.window._ctx_live_title.text(), "Nicht verbunden")

    def test_audio_value_feeds_hud_context_and_composer(self):
        self.window._apply_audio_level(.72)
        self.assertAlmostEqual(self.window.hud._live_amp, .72)
        self.assertAlmostEqual(self.window._ctx_audio._level, .72)
        self.assertAlmostEqual(self.window._composer_wave_left._level, .72)
        self.assertAlmostEqual(self.window._composer_wave_right._level, .72)

    def test_send_keeps_text_command_functional(self):
        called = threading.Event()
        received: list[str] = []

        def command(text: str):
            received.append(text)
            called.set()

        self.window.on_text_command = command
        self.window._input.setText("Hallo Mica")
        self.window._send()
        self.assertTrue(called.wait(1))
        self.assertEqual(received, ["Hallo Mica"])
        self.assertEqual(self.window._input.text(), "")

    def test_push_to_talk_button_has_separate_press_and_release_callbacks(self):
        events: list[str] = []
        self.window.on_push_to_talk_start = lambda: events.append("start")
        self.window.on_push_to_talk_stop = lambda: events.append("stop")
        self.window._ptt_btn.pressed.emit()
        self.window._ptt_btn.released.emit()
        self.assertEqual(events, ["start", "stop"])
        self.assertIn("F8", self.window._ptt_btn.toolTip())
        self.window._toggle_mute()
        self.assertTrue(self.window._ptt_btn.isEnabled() is False)

    def test_mute_notifies_the_local_voice_controller(self):
        events: list[bool] = []
        self.window.on_mute_change = events.append
        self.window._toggle_mute()
        self.window._toggle_mute()
        self.assertEqual(events, [True, False])

    def test_file_drop_handler_keeps_upload_out_of_the_visible_sidebar(self):
        with tempfile.TemporaryDirectory() as directory:
            file_path = Path(directory) / "notiz.md"
            file_path.write_text("Mica", encoding="utf-8")
            self.window._on_file_selected(str(file_path))
        self.assertTrue(self.window._current_file.endswith("notiz.md"))
        self.assertIn("notiz.md", self.window._input.placeholderText())
        self.assertFalse(hasattr(self.window, "_drop_zone"))

    def test_empty_project_context_is_explicit(self):
        self.assertIsNone(latest_project_context({"projects": {}}))
        self.window._update_metrics()
        self.assertEqual(self.window._ctx_project_title.text(), "Kein gespeichertes Projekt")

    def test_latest_project_context_prefers_the_newest_saved_entry(self):
        project = latest_project_context({"projects": {
            "archive": {"value": "Abgeschlossen", "updated": "2025-03-01"},
            "mica_hud": {"value": "Aktueller HUD-Umbau", "updated": "2026-09-03"},
        }})
        self.assertEqual(project, ("Mica Hud", "Aktueller HUD-Umbau"))

    def test_reminder_index_returns_only_future_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / "reminders.json"
            with patch.object(reminder, "_reminder_index_path", return_value=index):
                reminder._save_reminder_index([
                    {"when": "2020-01-01 10:00", "message": "alt", "job_id": "old"},
                    {"when": "2099-01-01 10:00", "message": "neu", "job_id": "new"},
                ])
                self.assertEqual(reminder.list_upcoming_reminders(), [
                    {"when": "Thu, 01. Jan · 10:00", "message": "neu"}
                ])

    def test_reference_and_minimum_sizes_render(self):
        for size in ((1600, 990), (_MIN_W, _MIN_H)):
            self.window.resize(*size)
            self.window.show()
            self.app.processEvents()
            image = self.window.grab()
            self.assertEqual((image.width(), image.height()), size)


if __name__ == "__main__":
    unittest.main()
