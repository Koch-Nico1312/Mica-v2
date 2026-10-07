from __future__ import annotations
import io
import json
import threading
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
import pytest
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from desktop.core.voice_settings import VoiceSettings, VoiceSettingsStore, VOICE_DIAGNOSTICS
from desktop.core.voice_signal import EndOfSpeech, EchoGuard, calibration_metrics
from desktop.core.local_voice import CoreVoiceSession
from desktop.core.local_core_client import LocalCoreClient
from mica_shared.voice_names import correct_names, validate_aliases
from backend.services.api.routers.voice import VoiceRoutes, ROUTES
from backend.services.api.routing import bind_router
from backend.services.api.auth import ApiTokenGate
from backend.services.common.contracts import VoiceControl


def pcm(values):
    return np.clip(np.asarray(values) * 32768, -32768, 32767).astype("<i2").tobytes()


def test_settings_atomic_restart_invalid_values_and_correct_default_path(tmp_path):
    path = tmp_path / "voice.json"
    store = VoiceSettingsStore(path)
    settings = VoiceSettings(pause_seconds=1.6, speech_threshold=0.04,
                             aliases=[{"heard": "Koko", "name": "Coucou"}])
    store.save(settings)
    assert VoiceSettingsStore(path).load() == settings
    settings.pause_seconds = float("nan")
    with pytest.raises(ValueError):
        store.save(settings)
    assert store.load().pause_seconds == 1.6
    path.write_text("broken", encoding="utf-8")
    assert not store.load().barge_in
    assert VoiceSettingsStore().path == Path(__file__).resolve().parents[1] / ".mica-data/voice-settings.json"


def test_short_and_long_pause_noise_and_recording_limit():
    quick = EndOfSpeech(VoiceSettings(pause_seconds=0.5), 0)
    assert quick.feed(0.1, 0) is None
    assert quick.feed(0, 0.8) is None  # one impulse is not speech
    quick.feed(0.1, 1)
    quick.feed(0.1, 1.08)
    assert quick.feed(0, 1.4) is None
    assert quick.feed(0, 1.59) == "pause"
    patient = EndOfSpeech(VoiceSettings(pause_seconds=1.6), 0)
    patient.feed(0.1, 1)
    patient.feed(0.1, 1.08)
    assert patient.feed(0, 2) is None
    patient.feed(0.1, 2.08)
    assert patient.feed(0, 3) is None
    assert patient.feed(0, 3.69) == "pause"
    assert EndOfSpeech(VoiceSettings(), 0).feed(0, 30) == "limit"


def test_calibration_measures_clipping_noise_and_transcript_quality():
    rng = np.random.default_rng(22)
    quiet = pcm(rng.normal(0, 0.001, 32000))
    spoken = pcm(rng.normal(0, 0.04, 96000))
    result = calibration_metrics(quiet, spoken, "Öffne meine Notizen", "Öffne meine Notizen")
    assert result["acceptable"] and result["accuracy"] == 1
    assert 0.008 <= result["speech_threshold"] < 0.05
    too_loud = calibration_metrics(quiet, pcm(np.ones(32000)), "falsch", "Öffne meine Notizen")
    assert not too_loud["acceptable"] and too_loud["clipping_percent"] == 100
    assert any("reduzieren" in text for text in too_loud["recommendations"])
    noisy = calibration_metrics(spoken, spoken, "Öffne meine Notizen", "Öffne meine Notizen")
    assert not noisy["acceptable"]


def test_names_do_not_rewrite_contacts_substrings_or_chain_aliases():
    assert correct_names("Hallo Maika. Öffne Notizen", [])[0] == "Hallo Mica. Öffne Notizen"
    assert correct_names("Ruf Maika an", [])[0] == "Ruf Maika an"
    aliases = [{"heard": "Koko", "name": "Coucou"}, {"heard": "Coucou", "name": "Mica"}]
    text, changes = correct_names("Öffne Koko und Kokosnuss", aliases)
    assert text == "Öffne Coucou und Kokosnuss" and len(changes) == 1
    for invalid in ([{"heard": "Koko", "name": "Coucou", "secret": "x"}],
                    [{"heard": "Koko", "name": "Coucou"}] * 2,
                    [{"heard": ".*", "name": "Mica"}]):
        with pytest.raises(ValueError):
            validate_aliases(invalid)
    control = VoiceControl(command="start", input_mode="wake_word", state="listening", name_aliases=aliases)
    assert control.name_aliases == aliases


@pytest.mark.parametrize("delay", [0, 160, 1600, 4400])
def test_playback_echo_does_not_interrupt_but_double_talk_does(delay):
    rng = np.random.default_rng(15)
    reference = rng.normal(0, 0.04, 1280 * 18).astype(np.float32)
    delayed = np.concatenate((np.zeros(delay), reference))[:len(reference)]
    echo = delayed * 0.7
    guard = EchoGuard(0.035)
    for index in range(12):
        start = index * 1280
        assert not guard.feed(echo[start:start + 1280], reference[start:start + 1280])[0]
    triggered = False
    for index in range(12, 18):
        start = index * 1280
        human = rng.normal(0, 0.06, 1280)
        result, seed = guard.feed(echo[start:start + 1280] + human, reference[start:start + 1280])
        triggered |= result
        if result:
            assert seed and len(seed) <= 6 * 1280 * 2
    assert triggered


def test_short_impulse_and_quiet_background_do_not_interrupt():
    guard = EchoGuard(0.035)
    for index in range(10):
        mic = np.ones(1280, dtype=np.float32) * (0.06 if index == 5 else 0.001)
        assert not guard.feed(mic, np.zeros(1280))[0]


@pytest.fixture
def voice_api():
    calls = []
    def transport(request):
        calls.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "engine": "parakeet-redux"})
        return httpx.Response(200, json={"text": "Öffne meine Notizen"})
    class Runtime(VoiceRoutes):
        httpx = SimpleNamespace(Timeout=httpx.Timeout, HTTPError=httpx.HTTPError,
                               AsyncClient=lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(transport), **kwargs))
        turn = Mock()
        audit = Mock()
    runtime = Runtime()
    app = FastAPI()
    app.add_middleware(ApiTokenGate, token="x" * 40)
    app.include_router(bind_router(runtime, ROUTES))
    return TestClient(app), calls, runtime


def test_calibration_is_authenticated_transcription_only_and_bounded(voice_api):
    client, calls, runtime = voice_api
    assert client.post("/v1/voice/calibrate", content=b"\0\0").status_code == 401
    assert not calls
    client.headers["X-Mica-API-Token"] = "x" * 40
    response = client.post("/v1/voice/calibrate", content=b"\0\0" * 16000)
    assert response.status_code == 200 and response.json()["storage"] == "none"
    assert response.json()["text"] == "Öffne meine Notizen"
    assert len(calls) == 1 and calls[0].url.host == "stt"
    runtime.turn.assert_not_called()
    runtime.audit.append.assert_not_called()
    for payload, status in ((b"", 422), (b"x", 422), (b"x" * 320002, 413)):
        assert client.post("/v1/voice/calibrate", content=payload).status_code == status
    assert len(calls) == 1
    assert client.get("/v1/voice/health").json()["services"]["stt"]["status"] == "ok"


def test_calibration_cannot_upload_audio_to_cloud(voice_api, monkeypatch):
    client, calls, runtime = voice_api
    client.headers["X-Mica-API-Token"] = "x" * 40
    monkeypatch.setenv("STT_URL", "https://example.com")
    assert client.post("/v1/voice/calibrate", content=b"\0\0").status_code == 503
    assert not calls


def test_duplex_interrupt_stops_output_and_preserves_leading_speech(monkeypatch):
    session = CoreVoiceSession(LocalCoreClient("https://localhost", api_token="test"))
    session._capture_device_ready = True
    session._input_device, session._output_device = 7, 9
    opened, stopped = [], []
    class CallbackStop(Exception):
        pass
    class Stream:
        active = True
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            opened.append(kwargs)
        def start(self):
            for index in range(8):
                out = bytearray(2560)
                try:
                    self.kwargs["callback"](pcm(np.ones(1280) * 0.05), out, 1280, None, False)
                except CallbackStop:
                    self.active = False
                    break
        def abort(self):
            stopped.append(True)
            self.active = False
        def close(self):
            self.active = False
    monkeypatch.setitem(__import__('sys').modules, "sounddevice", SimpleNamespace(RawStream=Stream, CallbackStop=CallbackStop, stop=lambda: None))
    wav = io.BytesIO()
    with wave.open(wav, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * 16000)
    session._play_response(wav.getvalue(), session._cancel)
    assert opened[0]["device"] == (7, 9)
    assert stopped and session._cancel.is_set()
    assert session.take_barge_audio()
    assert not session.take_barge_audio()


def test_explicit_cancel_discards_pending_barge_in(monkeypatch):
    session = CoreVoiceSession(LocalCoreClient("https://localhost", api_token="test"))
    session._barge_audio = b"pending speech"
    monkeypatch.setitem(__import__('sys').modules, "sounddevice", SimpleNamespace(stop=lambda: None))
    session.cancel()
    assert not session.take_barge_audio()


def test_barge_in_keeps_words_spoken_during_reconnection(monkeypatch):
    from tests.test_voice_reliability import VoiceSocket
    session = CoreVoiceSession(LocalCoreClient("https://localhost", api_token="test"))
    socket = VoiceSocket()
    streams = []
    class InputStream:
        active = True
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]
            streams.append(self)
        def start(self):
            self.callback(b"\x01\x00" * 1280, 1280, None, False)
        def close(self):
            self.active = False
        def abort(self):
            self.active = False
        def __enter__(self):
            self.callback(b"\x02\x00" * 1280, 1280, None, False)
            session.finish()
            return self
        def __exit__(self, *args):
            self.close()
    audio = SimpleNamespace(RawInputStream=InputStream, stop=lambda: None)
    monkeypatch.setitem(__import__('sys').modules, "sounddevice", audio)
    def connect(*args, **kwargs):
        assert streams and streams[0].active
        streams[0].callback(b"\x03\x00" * 1280, 1280, None, False)
        return socket
    monkeypatch.setattr("websocket.create_connection", connect)
    monkeypatch.setattr(session, "_selected_device", lambda kind: None)
    monkeypatch.setattr(session, "_play_response", lambda *args: None)
    assert session.start(auto_finalize=True, initial_audio=b"\x04\x00" * 1280)
    session._worker.join(timeout=3)
    assert not session.active
    assert socket.audio[0] == (b"\x04\x00" * 1280 + b"\x01\x00" * 1280 + b"\x03\x00" * 1280)
    assert socket.audio[1] == b"\x02\x00" * 1280
    assert all(not stream.active for stream in streams)


def test_voice_ui_saves_preferences_and_shows_real_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from desktop.voice_settings_overlay import VoiceSettingsOverlay
    app = QApplication.instance() or QApplication([])
    store = VoiceSettingsStore(tmp_path / "voice.json")
    overlay = VoiceSettingsOverlay(store=store)
    overlay.show()
    app.processEvents()
    overlay.pause.setValue(1.5)
    overlay.response_style.setCurrentIndex(overlay.response_style.findData("detailed"))
    overlay.names.setPlainText("Koko → Coucou")
    overlay._save()
    assert store.load().pause_seconds == 1.5
    assert store.load().response_style == "detailed"
    assert store.load().aliases == [{"heard": "Koko", "name": "Coucou"}]
    VOICE_DIAGNOSTICS.update(transcript="Öffne Coucou", stt_ms=230, state="THINKING")
    overlay._diagnose()
    assert "230 ms" in overlay.diagnostics.text() and "Öffne Coucou" in overlay.diagnostics.text()
    overlay._finished({"text": "falsch", "accuracy": 0.1, "stt_ms": 12,
                       "acceptable": False, "recommendations": ["Erneut testen"]}, "")
    assert not overlay.use_recommendation.isEnabled()
    overlay.hide()
    assert overlay._stop.is_set()
    VOICE_DIAGNOSTICS.clear()
