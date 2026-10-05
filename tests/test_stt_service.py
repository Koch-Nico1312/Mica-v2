"""PCM transport, readiness and local recognition failure contracts."""
import struct
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.services import stt_service as stt


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(stt, "ENGINE", "parakeet-redux")
    monkeypatch.setattr(stt, "_ready", True)
    monkeypatch.setattr(stt, "_speech", Mock())
    return TestClient(stt.app)


def test_pcm_is_normalized_and_transcript_contract_preserved(client, monkeypatch):
    speech = Mock()
    speech.transcribe.return_value = {"text": "  Öffne meine Notizen.  "}
    monkeypatch.setattr(stt, "_speech", speech)
    response = client.post("/v1/transcribe", content=struct.pack("<hhh", -32768, 0, 16384))
    assert response.json() == {"text": "Öffne meine Notizen."}
    options = speech.transcribe.call_args.kwargs
    np.testing.assert_array_equal(options["audio"], [-1.0, 0.0, 0.5])
    assert options["sample_rate"] == 16000
    assert options["timestamps"] == "none"
    assert "language" not in options


@pytest.mark.parametrize("audio,status", [(b"", 413), (b"x", 422), (b"x" * 10, 413)])
def test_invalid_audio_never_reaches_model(client, monkeypatch, audio, status):
    monkeypatch.setattr(stt, "MAX_AUDIO_BYTES", 8)
    assert client.post("/v1/transcribe", content=audio).status_code == status
    stt._speech.transcribe.assert_not_called()


def test_unavailable_and_inference_failure_are_explicit(client, monkeypatch):
    monkeypatch.setattr(stt, "_ready", False)
    assert client.get("/health").json()["status"] == "unavailable"
    assert client.post("/v1/transcribe", content=b"\0\0").status_code == 503
    monkeypatch.setattr(stt, "_ready", True)
    stt._speech.transcribe.side_effect = RuntimeError("private internal details")
    response = client.post("/v1/transcribe", content=b"\0\0")
    assert response.status_code == 502
    assert "private" not in response.text


def test_startup_proves_inference_and_closes_model(monkeypatch):
    speech = Mock()
    factory = Mock(return_value=speech)
    monkeypatch.setitem(sys.modules, "moondream", SimpleNamespace(photon=factory))
    monkeypatch.setattr(stt, "ENGINE", "parakeet-redux")
    monkeypatch.setattr(stt, "_ready", False)
    with TestClient(stt.app) as client:
        assert client.get("/health").json()["status"] == "ok"
        factory.assert_called_once_with(stt.MODEL_ID, device="cpu")
        assert speech.transcribe.call_args.kwargs["audio"].shape == (16000,)
    speech.close.assert_called_once()
    assert not stt._ready


def test_failed_startup_does_not_claim_health(monkeypatch):
    monkeypatch.setattr(stt, "ENGINE", "parakeet-redux")
    monkeypatch.setattr(stt, "_ready", False)
    monkeypatch.setattr(stt, "_speech", None)
    monkeypatch.setitem(sys.modules, "moondream", SimpleNamespace(photon=Mock(side_effect=RuntimeError("no CPU kernel"))))
    with TestClient(stt.app) as client:
        assert client.get("/health").json()["status"] == "unavailable"
        assert client.post("/v1/transcribe", content=b"\0\0").status_code == 503


def test_whisper_requires_actual_model_file(monkeypatch, tmp_path):
    monkeypatch.setenv("WHISPER_MODEL", "")
    with pytest.raises(RuntimeError):
        stt._whisper_model()
    monkeypatch.setenv("WHISPER_MODEL", str(tmp_path))
    with pytest.raises(RuntimeError):
        stt._whisper_model()


def test_explicit_whisper_alternative(client, monkeypatch, tmp_path):
    model = tmp_path / "small.bin"
    model.write_bytes(b"model")
    monkeypatch.setenv("WHISPER_MODEL", str(model))
    monkeypatch.setenv("WHISPER_LANGUAGE", "de")
    monkeypatch.setattr(stt, "ENGINE", "whisper.cpp")
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="Hallo", stderr=""))
    monkeypatch.setattr(stt.subprocess, "run", run)
    assert client.post("/v1/transcribe", content=b"\0\0").json() == {"text": "Hallo"}
    assert "de" in run.call_args.args[0]
