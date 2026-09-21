"""Regression coverage for the supplied Mica UI references and text-only mode."""
from __future__ import annotations

import asyncio
import os
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import main
import ui


class ReferenceUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        check = mock.patch.object(ui.MainWindow, "_check_config", return_value=True)
        self.addCleanup(check.stop)
        check.start()
        self.window = ui.MainWindow("")
        self.window.resize(1600, 900)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_reference_orb_is_packaged_and_used(self):
        asset = Path(ui.__file__).resolve().parent / "assets" / "mica-orb-v2.png"
        self.assertTrue(asset.is_file())
        self.assertIsNotNone(self.window.hud._face_px)
        self.assertEqual(self.window.hud._face_source, asset)

    def test_reference_greeting_is_time_aware_and_uses_mica_copy(self):
        self.assertEqual(ui.time_greeting(datetime(2026, 9, 21, 9)), "Guten Morgen")
        self.assertEqual(ui.time_greeting(datetime(2026, 9, 21, 14)), "Guten Tag")
        self.assertEqual(ui.time_greeting(datetime(2026, 9, 21, 20)), "Guten Abend")

    def test_reference_shell_and_composer_geometry(self):
        self.assertEqual(self.window._left_panel.width(), 210)
        self.assertEqual(self.window._right_panel.width(), 350)
        self.assertLessEqual(self.window._footer.y() + self.window._footer.height(), 880)
        self.assertTrue(self.window._ptt_btn.isHidden())
        self.assertFalse(self.window._mute_btn.isHidden())
        self.assertFalse(self.window._mute_btn.icon().isNull())

    def test_memory_category_labels_have_explicit_readable_palette(self):
        self.window._activate_navigation("memory")
        combo = self.window._memory_category_input
        self.assertEqual(
            [combo.itemText(i) for i in range(combo.count())],
            ["Notizen", "Vorlieben", "Identität", "Projekte", "Wünsche", "Beziehungen"],
        )
        style = combo.styleSheet()
        self.assertIn("QAbstractItemView", style)
        self.assertIn(f"color: {ui.C.TEXT}", style)
        self.assertGreaterEqual(combo.minimumWidth(), 170)

    def test_setup_overlay_keeps_reference_size_after_resize(self):
        self.window._show_setup()
        self.window.resize(1500, 850)
        self.app.processEvents()
        self.assertEqual(
            (self.window._overlay.width(), self.window._overlay.height()),
            (ui.SetupOverlay._OW, ui.SetupOverlay._OH),
        )


class MissingMicrophoneTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_microphone_keeps_session_alive_in_text_mode(self):
        class FakeUi:
            muted = False

            def __init__(self):
                self.logs = []
                self.states = []

            def write_log(self, text):
                self.logs.append(text)

            def set_state(self, state):
                self.states.append(state)

        live = object.__new__(main.JarvisLive)
        live.ui = FakeUi()

        with mock.patch.object(main.audio_devices, "list_devices", return_value=[]):
            task = asyncio.create_task(live._listen_audio())
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertIn("Textmodus bleibt aktiv", live.ui.logs[0])
        self.assertEqual(live.ui.states, ["LISTENING"])


if __name__ == "__main__":
    unittest.main()
