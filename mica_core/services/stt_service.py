from __future__ import annotations

import os
import re
import subprocess
import tempfile
import wave
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

app = FastAPI(title="MICA whisper.cpp STT")
MAX_AUDIO_BYTES = max(1, int(os.getenv("MICA_VOICE_MAX_BYTES", str(10 * 1024 * 1024))))
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "de").strip().lower()
if not re.fullmatch(r"[a-z]{2,3}", WHISPER_LANGUAGE):
    raise RuntimeError("WHISPER_LANGUAGE must be a 2-3 letter language code")


@app.get("/health")
def health() -> dict[str, str]:
    model = Path(os.getenv("WHISPER_MODEL", ""))
    return {"status": "ok" if model.exists() else "model-missing", "engine": "whisper.cpp"}


@app.post("/v1/transcribe")
async def transcribe(request: Request) -> dict[str, str]:
    model = Path(os.getenv("WHISPER_MODEL", ""))
    if not model.exists():
        raise HTTPException(503, "whisper.cpp model is not mounted")
    audio = await request.body()
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "audio payload is empty or too large")
    with tempfile.TemporaryDirectory() as temp_dir:
        wav_path = Path(temp_dir) / "input.wav"
        with wave.open(str(wav_path), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000); output.writeframes(audio)
        try:
            result = subprocess.run([
                os.getenv("WHISPER_BIN", "whisper-cli"), "-m", str(model),
                "-f", str(wav_path), "-l", WHISPER_LANGUAGE, "-nt",
            ], capture_output=True, text=True, check=False, timeout=120)
        except subprocess.TimeoutExpired as error:
            raise HTTPException(504, "whisper.cpp timed out") from error
    if result.returncode:
        raise HTTPException(502, result.stderr[-500:])
    return {"text": result.stdout.strip()}
