from __future__ import annotations

import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from desktop.core import audio_devices
from desktop import ui_settings

APP = QApplication.instance() or QApplication([])


def test_device_overlay_refreshes_in_background_and_keeps_missing_selection(monkeypatch):
    queued = []

    class DeferredThread:
        def __init__(self, *, target, **kwargs):
            self.target = target

        def start(self):
            queued.append(self.target)

    inventory = {"input": ["USB microphone"], "output": ["Speakers"]}
    monkeypatch.setattr(ui_settings.threading, "Thread", DeferredThread)
    monkeypatch.setattr(audio_devices, "cached_devices", lambda: inventory)
    discover = Mock()
    monkeypatch.setattr(audio_devices, "list_devices", discover)
    monkeypatch.setattr("desktop.memory.config_manager.get_input_device", lambda: "Headset")
    monkeypatch.setattr("desktop.memory.config_manager.get_output_device", lambda: "Speakers")

    overlay = ui_settings.AudioDeviceOverlay()
    overlay.show()
    APP.processEvents()
    assert len(queued) == 1
    discover.assert_not_called()
    assert not overlay._apply_button.isEnabled()
    assert overlay._in_box.currentData() == "Headset"
    queued.pop()()
    discover.assert_called_once_with("input", refresh=True)
    assert overlay._apply_button.isEnabled()
    assert overlay._in_box.currentData() == "Headset"
    assert "nicht verbunden" in overlay._in_box.currentText()

    overlay._in_box.setCurrentIndex(overlay._in_box.findData("USB microphone"))
    overlay._refresh_button.click()
    queued.pop()()
    assert overlay._in_box.currentData() == "USB microphone"
    overlay.close()
    overlay.deleteLater()
    APP.processEvents()


def test_refresh_invalidates_old_transport_probes(monkeypatch):
    monkeypatch.setattr(audio_devices, "_cache", {"input": ["Old"], "output": []})
    monkeypatch.setattr(audio_devices, "_probe_results", {("mme", "input"): True})
    monkeypatch.setattr(audio_devices, "_chosen_api", {"input": "mme", "output": "mme"})
    query = Mock(return_value={"input": ["New"], "output": ["Speakers"]})
    monkeypatch.setattr(audio_devices, "_query", query)

    assert audio_devices.list_devices("input", refresh=True) == ["New"]
    assert audio_devices.list_devices("output") == ["Speakers"]
    assert audio_devices._probe_results == {}
    assert audio_devices._chosen_api == {"input": None, "output": None}
    query.assert_called_once()


def test_changing_devices_interrupts_current_session_without_auto_recording():
    from desktop.local_main import LocalMica

    mica = LocalMica.__new__(LocalMica)
    mica.ui = Mock()
    mica.voice = Mock(active=True)
    mica.wake_word = Mock()
    mica._voice_completed = Mock()
    mica._audio_devices_changed()
    mica.voice.cancel.assert_called_once()
    mica.wake_word.stop.assert_called_once()
    mica.voice.start.assert_not_called()
    mica._voice_completed.assert_not_called()

