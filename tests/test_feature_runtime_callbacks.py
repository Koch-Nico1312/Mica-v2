from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from desktop.local_main import LocalMica


def _mica(*, muted: bool = False, voice_active: bool = False):
    mica = LocalMica.__new__(LocalMica)
    mica.ui = SimpleNamespace(muted=muted, write_log=Mock())
    mica.voice = SimpleNamespace(active=voice_active)
    mica.wake_word = SimpleNamespace(start=Mock(return_value=True), stop=Mock())
    return mica


def test_disabling_wake_word_stops_live_microphone_listener_immediately() -> None:
    mica = _mica()

    mica._feature_changed("MICA_WAKE_WORD_ENABLED", False)

    mica.wake_word.stop.assert_called_once_with()
    mica.wake_word.start.assert_not_called()


def test_enabling_wake_word_starts_listener_when_audio_is_idle() -> None:
    mica = _mica()

    mica._feature_changed("MICA_WAKE_WORD_ENABLED", True)

    mica.wake_word.start.assert_called_once_with()
    mica.wake_word.stop.assert_not_called()


def test_enabling_wake_word_waits_while_voice_session_owns_microphone() -> None:
    mica = _mica(voice_active=True)

    mica._feature_changed("MICA_WAKE_WORD_ENABLED", True)

    mica.wake_word.start.assert_not_called()
    assert "aktuellen Sprachvorgang" in mica.ui.write_log.call_args.args[0]


def test_late_wake_detection_cannot_record_after_feature_is_disabled(monkeypatch) -> None:
    mica = _mica()
    mica.voice.start = Mock()
    monkeypatch.setenv("MICA_WAKE_WORD_ENABLED", "0")

    mica._wake_detected()

    mica.voice.start.assert_not_called()
