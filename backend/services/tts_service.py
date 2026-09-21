from __future__ import annotations

import os
import subprocess
import tempfile
import io
import re
import threading
import base64
import wave
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Response

app = FastAPI(title="MICA TTS")
MAX_TEXT_CHARS = max(1, int(os.getenv("MICA_TTS_MAX_TEXT_CHARS", "16000")))
KOKORO_SAMPLE_RATE = 24000
GEMINI_SAMPLE_RATE = 24000
_kokoro_lock = threading.RLock()

GEMINI_VOICES = {
    "Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede",
    "Callirrhoe", "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba",
    "Despina", "Erinome", "Algenib", "Rasalgethi", "Laomedeia", "Achernar",
    "Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
    "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat",
}
OPENAI_VOICES = {
    "alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova",
    "sage", "shimmer", "verse", "marin", "cedar",
}


def _engine() -> str:
    configured = os.getenv("MICA_TTS_ENGINE", "piper").strip().lower()
    if configured == "auto":
        provider = os.getenv("MICA_LLM_PROVIDER", "ollama").strip().lower()
        if provider in {"gemini", "google", "google_gemini"}:
            return "gemini"
        if provider in {"openai_api", "openai-cloud", "openai_cloud"}:
            return "openai"
        return "kokoro"
    if configured in {"gemini", "google", "google_tts", "gemini_tts"}:
        return "gemini"
    if configured in {"openai", "openai_tts"}:
        return "openai"
    return configured if configured in {"kokoro", "piper"} else "piper"


def _gemini_key() -> str:
    return (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()


def _gemini_voice() -> str:
    configured = os.getenv("MICA_GEMINI_TTS_VOICE", "Sulafat").strip()
    return configured if configured in GEMINI_VOICES else "Sulafat"


def _gemini_model() -> str:
    configured = os.getenv("MICA_GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts").strip()
    return configured.removeprefix("models/") or "gemini-2.5-flash-preview-tts"


def _openai_key() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip()


def _openai_voice() -> str:
    configured = os.getenv("MICA_OPENAI_TTS_VOICE", "coral").strip().lower()
    return configured if configured in OPENAI_VOICES else "coral"


def _openai_model() -> str:
    configured = os.getenv("MICA_OPENAI_TTS_MODEL", "gpt-4o-mini-tts").strip()
    return configured or "gpt-4o-mini-tts"


def _pcm_to_wav(pcm: bytes, sample_rate: int = GEMINI_SAMPLE_RATE) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return output.getvalue()


def _synthesize_gemini(text: str) -> bytes:
    key = _gemini_key()
    if not key:
        raise RuntimeError("Gemini API key is not configured")
    model = _gemini_model()
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{quote(model, safe='')}:generateContent"
    )
    payload = {
        "contents": [{"parts": [{
            "text": (
                "Sprich den folgenden deutschen Text exakt. Klinge warm, nat�rlich, "
                "direkt und leicht humorvoll; f�ge keine W�rter hinzu.\n\n" + text
            ),
        }]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": _gemini_voice()},
                },
            },
        },
    }
    try:
        response = httpx.post(
            endpoint,
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json=payload,
            timeout=httpx.Timeout(120.0, connect=10.0),
        )
        response.raise_for_status()
        data = response.json()
        encoded = data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
        if not isinstance(encoded, str):
            raise ValueError("audio data is not text")
        pcm = base64.b64decode(encoded, validate=True)
        if not pcm or len(pcm) % 2 or len(pcm) > 32 * 1024 * 1024:
            raise ValueError("invalid PCM audio")
        return _pcm_to_wav(pcm)
    except httpx.TimeoutException:
        raise RuntimeError("Gemini TTS request timed out") from None
    except httpx.HTTPStatusError as error:
        raise RuntimeError(f"Gemini TTS request failed with HTTP {error.response.status_code}") from None
    except httpx.HTTPError:
        raise RuntimeError("Gemini TTS request failed") from None
    except (KeyError, IndexError, TypeError, ValueError):
        raise RuntimeError("Gemini TTS returned invalid audio") from None


def _synthesize_openai(text: str) -> bytes:
    key = _openai_key()
    if not key:
        raise RuntimeError("OpenAI API key is not configured")
    try:
        response = httpx.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": _openai_model(),
                "voice": _openai_voice(),
                "input": text,
                "instructions": (
                    "Sprich Deutsch. Klinge warm, nat�rlich, direkt, hilfreich und leicht humorvoll."
                ),
                "response_format": "wav",
            },
            timeout=httpx.Timeout(120.0, connect=10.0),
        )
        response.raise_for_status()
        audio = bytes(response.content)
        if len(audio) < 44 or len(audio) > 32 * 1024 * 1024 or not audio.startswith(b"RIFF"):
            raise ValueError("invalid WAV audio")
        return audio
    except httpx.TimeoutException:
        raise RuntimeError("OpenAI TTS request timed out") from None
    except httpx.HTTPStatusError as error:
        raise RuntimeError(f"OpenAI TTS request failed with HTTP {error.response.status_code}") from None
    except httpx.HTTPError:
        raise RuntimeError("OpenAI TTS request failed") from None
    except (TypeError, ValueError):
        raise RuntimeError("OpenAI TTS returned invalid audio") from None


def _model_paths() -> tuple[Path, Path] | None:
    configured = os.getenv("PIPER_MODEL", "").strip()
    if not configured:
        return None
    model = Path(configured)
    configured_json = os.getenv("PIPER_CONFIG", "").strip()
    config = Path(configured_json) if configured_json else Path(str(model) + ".json")
    if not model.is_file() or not config.is_file():
        return None
    return model, config


def _kokoro_paths() -> tuple[Path, Path, Path] | None:
    values = (
        os.getenv("KOKORO_MODEL", "").strip(),
        os.getenv("KOKORO_CONFIG", "").strip(),
        os.getenv("KOKORO_VOICE", "").strip(),
    )
    if not all(values):
        return None
    paths = tuple(Path(value) for value in values)
    return paths if all(path.is_file() for path in paths) else None  # type: ignore[return-value]


def _text_chunks(text: str, limit: int = 350) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > limit:
            head, sentence = sentence[:limit], sentence[limit:]
            if current:
                chunks.append(current)
                current = ""
            chunks.append(head)
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > limit:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


@lru_cache(maxsize=1)
def _load_kokoro(model_path: str, config_path: str):
    import kokoro.pipeline as kokoro_pipeline
    from kokoro import KModel, KPipeline

    # The German voice was released after kokoro 0.9.4. Its model card uses
    # lang_code="d"; registering the matching espeak-ng code supplies the
    # missing German grapheme-to-phoneme route without modifying model weights.
    kokoro_pipeline.LANG_CODES.setdefault("d", "de")
    kokoro_pipeline.ALIASES.setdefault("de", "d")
    model = KModel(config=config_path, model=model_path)
    return KPipeline(lang_code="d", model=model, device="cpu")


def _synthesize_kokoro(text: str, paths: tuple[Path, Path, Path]) -> bytes:
    import numpy as np
    import soundfile as sf

    model, config, voice = paths
    with _kokoro_lock:
        pipeline = _load_kokoro(str(model), str(config))
        audio_parts = [
            result.audio.detach().cpu().numpy()
            for chunk in _text_chunks(text)
            for result in pipeline(chunk, voice=str(voice))
            if result.audio is not None
        ]
    if not audio_parts:
        raise RuntimeError("Kokoro produced no audio")
    output = io.BytesIO()
    sf.write(output, np.concatenate(audio_parts), KOKORO_SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return output.getvalue()


@app.get("/health")
def health() -> dict[str, str]:
    engine = _engine()
    if engine == "gemini":
        return {
            "status": "ok" if _gemini_key() else "key-missing",
            "engine": engine,
            "voice": _gemini_voice(),
        }
    if engine == "openai":
        return {
            "status": "ok" if _openai_key() else "key-missing",
            "engine": engine,
            "voice": _openai_voice(),
        }
    paths = _kokoro_paths() if engine == "kokoro" else _model_paths()
    return {
        "status": "ok" if paths else "model-missing",
        "engine": engine,
        "voice": paths[-1].stem if paths and engine == "kokoro" else paths[0].stem if paths else "unconfigured",
    }


@app.post("/v1/synthesize")
def synthesize(payload: dict[str, str]) -> Response:
    text = str(payload.get("text", "")).strip()
    engine = _engine()
    paths = _kokoro_paths() if engine == "kokoro" else _model_paths() if engine == "piper" else None
    if not text:
        raise HTTPException(400, "text is required")
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(413, "text is too large")
    if engine == "openai" and len(text) > 4096:
        raise HTTPException(413, "text exceeds the OpenAI speech limit")
    if engine == "gemini":
        if not _gemini_key():
            raise HTTPException(503, "Gemini API key is not configured")
        try:
            return Response(_synthesize_gemini(text), media_type="audio/wav")
        except Exception as error:
            raise HTTPException(502, f"Gemini TTS synthesis failed: {error}") from error
    if engine == "openai":
        if not _openai_key():
            raise HTTPException(503, "OpenAI API key is not configured")
        try:
            return Response(_synthesize_openai(text), media_type="audio/wav")
        except Exception as error:
            raise HTTPException(502, f"OpenAI TTS synthesis failed: {error}") from error
    if paths is None:
        raise HTTPException(503, f"{engine.capitalize()} model files are not mounted")
    if engine == "kokoro":
        try:
            return Response(_synthesize_kokoro(text, paths), media_type="audio/wav")  # type: ignore[arg-type]
        except Exception as error:
            raise HTTPException(502, f"Kokoro synthesis failed: {type(error).__name__}") from error
    model, config = paths
    with tempfile.TemporaryDirectory() as temp_dir:
        output = Path(temp_dir) / "speech.wav"
        try:
            result = subprocess.run(
                [
                    os.getenv("PIPER_BIN", "piper"),
                    "--model", str(model),
                    "--config", str(config),
                    "--output_file", str(output),
                ],
                input=text,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
        except subprocess.TimeoutExpired as error:
            raise HTTPException(504, "Piper timed out") from error
        if result.returncode or not output.exists():
            raise HTTPException(502, result.stderr[-500:])
        data = output.read_bytes()
    return Response(data, media_type="audio/wav")
