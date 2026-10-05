"""Local 16 kHz mono signed-int16 PCM transcription for MICA."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import wave

from fastapi import FastAPI, HTTPException, Request

MAX_AUDIO_BYTES = max(1, int(os.getenv("MICA_VOICE_MAX_BYTES", str(10 * 1024 * 1024))))
ENGINE = os.getenv("MICA_STT_ENGINE", "parakeet-redux").strip().lower()
MODEL_ID = "moondream/parakeet-redux"
_speech = None
_ready = False
_lock = threading.Lock()
logger = logging.getLogger(__name__)


def _whisper_model() -> Path:
    value = os.getenv("WHISPER_MODEL", "").strip()
    if not value or not Path(value).is_file():
        raise RuntimeError("whisper.cpp model is not mounted")
    return Path(value)


def _load() -> None:
    global _speech, _ready
    _ready = False
    if ENGINE == "parakeet-redux":
        import moondream as md
        import numpy as np

        _speech = md.photon(MODEL_ID, device="cpu")
        # Photon loads lazily: an actual inference proves readiness.
        _speech.transcribe(audio=np.zeros(16000, dtype=np.float32), sample_rate=16000, timestamps="none")
    elif ENGINE == "whisper.cpp":
        _whisper_model()
        if not re.fullmatch(r"[a-z]{2,3}", os.getenv("WHISPER_LANGUAGE", "de")):
            raise RuntimeError("WHISPER_LANGUAGE must be a 2-3 letter language code")
    else:
        raise RuntimeError(f"Unsupported MICA_STT_ENGINE: {ENGINE}")
    _ready = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _speech, _ready
    try:
        await asyncio.to_thread(_load)
    except Exception:
        logger.exception("Local STT initialization failed")
    try:
        yield
    finally:
        _ready = False
        if _speech is not None:
            await asyncio.to_thread(_speech.close)
            _speech = None


app = FastAPI(title="MICA local STT", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok" if _ready else "unavailable", "engine": ENGINE}


def _recognize(audio: bytes) -> str:
    # Keep one resident CPU model and serialize inference across callers.
    with _lock:
        if ENGINE == "parakeet-redux":
            import numpy as np

            samples = np.frombuffer(audio, dtype="<i2").astype(np.float32) / 32768.0
            return str(_speech.transcribe(
                audio=samples, sample_rate=16000, timestamps="none",
            )["text"]).strip()
        model = _whisper_model()
        with tempfile.TemporaryDirectory() as temp_dir:
            wav_path = Path(temp_dir) / "input.wav"
            with wave.open(str(wav_path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                output.writeframes(audio)
            result = subprocess.run([
                os.getenv("WHISPER_BIN", "whisper-cli"), "-m", str(model),
                "-f", str(wav_path), "-l", os.getenv("WHISPER_LANGUAGE", "de"), "-nt",
            ], capture_output=True, text=True, check=False, timeout=120)
        if result.returncode:
            raise RuntimeError("whisper.cpp transcription failed")
        return result.stdout.strip()


@app.post("/v1/transcribe")
async def transcribe(request: Request) -> dict[str, str]:
    # Bound the stream before retaining a complete recording in memory.
    audio = bytearray()
    async for chunk in request.stream():
        if len(audio) + len(chunk) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "audio payload is too large")
        audio.extend(chunk)
    if not audio:
        raise HTTPException(413, "audio payload is empty")
    if len(audio) % 2:
        raise HTTPException(422, "audio must be 16-bit mono PCM at 16000 Hz")
    if not _ready:
        raise HTTPException(503, "Local STT model is unavailable; check service logs")
    try:
        text = await asyncio.to_thread(_recognize, bytes(audio))
    except subprocess.TimeoutExpired as error:
        raise HTTPException(504, "Local STT timed out") from error
    except Exception as error:
        logger.exception("Local STT transcription failed")
        raise HTTPException(502, "Local STT transcription failed") from error
    return {"text": text}
