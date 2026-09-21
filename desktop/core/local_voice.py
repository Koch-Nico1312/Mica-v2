"""Privacy-preserving push-to-talk transport for the local Core websocket."""
from __future__ import annotations

from array import array
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import ssl
import threading
import time
from typing import Callable
from urllib.parse import urlparse

from .local_core_client import LocalCoreClient, LocalCoreError

CONVERSATION_MODES = {"personal", "technical", "monitoring"}


class CoreVoiceSession:
    def __init__(
        self,
        client: LocalCoreClient,
        *,
        on_state: Callable[[str], None] | None = None,
        on_level: Callable[[float], None] | None = None,
        on_transcript: Callable[[str], None] | None = None,
        on_reply: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_complete: Callable[[], None] | None = None,
        conversation_mode: str = "personal",
    ):
        self.client = client
        self.on_state = on_state or (lambda _state: None)
        self.on_level = on_level or (lambda _level: None)
        self.on_transcript = on_transcript or (lambda _text: None)
        self.on_reply = on_reply or (lambda _text: None)
        self.on_error = on_error or (lambda _text: None)
        self.on_complete = on_complete or (lambda: None)
        self.conversation_mode = (
            conversation_mode if conversation_mode in CONVERSATION_MODES else "personal"
        )
        self._lock = threading.Lock()
        self._active = False
        self._finish = threading.Event()
        self._cancel = threading.Event()
        self._socket = None
        self._stream = None
        self._worker: threading.Thread | None = None
        self._auto_finalize = False
        self._speech_started = False
        self._last_voice = 0.0
        self._started_at = 0.0

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def start(self, *, auto_finalize: bool = False) -> bool:
        with self._lock:
            if self._active:
                return False
            self._active = True
        self._finish.clear()
        self._cancel.clear()
        self._auto_finalize = auto_finalize
        self._speech_started = False
        self._last_voice = 0.0
        self._started_at = time.monotonic()
        self._worker = threading.Thread(target=self._run, name="mica-push-to-talk", daemon=True)
        self._worker.start()
        return True

    def finish(self) -> None:
        if self.active:
            self._finish.set()

    def cancel(self) -> None:
        self._cancel.set()
        self._finish.set()
        # sounddevice.stop() interrupts a blocking sd.play() immediately.  It
        # is intentionally best-effort so Esc also remains safe before the
        # optional audio dependency is installed.
        try:
            import sounddevice as sd  # type: ignore[import-not-found]

            sd.stop()
        except Exception:
            pass
        try:
            if self._socket is not None:
                self._socket.close()
        except Exception:
            pass

    @staticmethod
    def _level(data: bytes) -> float:
        samples = array("h")
        samples.frombytes(data)
        if not samples:
            return 0.0
        rms = math.sqrt(sum(value * value for value in samples) / len(samples))
        return max(0.0, min(1.0, rms / 8000.0))

    def _ssl_options(self) -> dict[str, object]:
        if isinstance(self.client.verify, str):
            return {"cert_reqs": ssl.CERT_REQUIRED, "ca_certs": self.client.verify}
        return {"cert_reqs": ssl.CERT_REQUIRED}

    def _reader(self, websocket, completed: threading.Event) -> None:
        try:
            while not self._cancel.is_set() and not completed.is_set():
                message = websocket.recv()
                if isinstance(message, bytes):
                    self._play_wav(message)
                    completed.set()
                    continue
                payload = json.loads(message)
                event_type = str(payload.get("type", ""))
                if event_type == "state":
                    state = str(payload.get("state", "")).lower()
                    mapped = {
                        "listening": "LISTENING",
                        "transcribing": "THINKING",
                        "planning": "THINKING",
                        "approval_required": "THINKING",
                        "speaking": "SPEAKING",
                    }.get(state)
                    if mapped:
                        self.on_state(mapped)
                    elif state == "cancelled":
                        self.cancel()
                        completed.set()
                    elif state == "failed":
                        self.on_error(str(payload.get("message", "Sprachverarbeitung fehlgeschlagen")))
                        completed.set()
                elif event_type == "transcript":
                    self.on_transcript(str(payload.get("text", "")))
                elif event_type == "response":
                    self.on_reply(str(payload.get("text", "")))
                    self.on_state("SPEAKING")
                elif event_type == "error":
                    self.on_error(str(payload.get("message", "Sprachverarbeitung fehlgeschlagen")))
                    completed.set()
        except Exception as error:
            if not self._cancel.is_set():
                self.on_error(f"Voice-Verbindung beendet: {error}")
            completed.set()

    @staticmethod
    def _play_wav(payload: bytes) -> None:
        import io
        import wave
        import numpy as np  # type: ignore[import-not-found]
        import sounddevice as sd  # type: ignore[import-not-found]

        with wave.open(io.BytesIO(payload), "rb") as wav:
            channels = wav.getnchannels()
            width = wav.getsampwidth()
            if width != 2:
                raise LocalCoreError("TTS-WAV muss 16-bit PCM enthalten")
            rate = wav.getframerate()
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
        if channels > 1:
            samples = samples.reshape((-1, channels))
        sd.play(samples, rate, blocking=True)

    def _run(self) -> None:
        completed = threading.Event()
        websocket = None
        try:
            import sounddevice as sd  # type: ignore[import-not-found]
            import websocket as websocket_client  # type: ignore[import-not-found]

            parsed = urlparse(self.client.base_url)
            voice_url = f"wss://{parsed.netloc}/v1/voice"
            websocket = websocket_client.create_connection(
                voice_url, timeout=10, sslopt=self._ssl_options(),
                origin=self.client.base_url,
            )
            self._socket = websocket
            websocket.send(json.dumps({
                "schema_version": 1,
                "command": "start",
                "input_mode": "wake_word" if auto_finalize else "push_to_talk",
                "state": "listening",
                "conversation_mode": self.conversation_mode,
            }))
            reader = threading.Thread(target=self._reader, args=(websocket, completed), daemon=True)
            reader.start()

            def capture(indata, _frames, _time_info, status):
                if status:
                    self.on_error(str(status))
                if self._finish.is_set() or self._cancel.is_set():
                    return
                payload = bytes(indata)
                level = self._level(payload)
                self.on_level(level)
                if self._auto_finalize:
                    now = time.monotonic()
                    if level >= 0.035:
                        self._speech_started = True
                        self._last_voice = now
                    elif self._speech_started and now - self._last_voice >= 1.2:
                        self._finish.set()
                    elif now - self._started_at >= 15.0:
                        self._finish.set()
                websocket.send_binary(payload)

            self.on_state("LISTENING")
            with sd.RawInputStream(samplerate=16000, channels=1, dtype="int16", blocksize=1280, callback=capture) as stream:
                self._stream = stream
                while not self._finish.wait(0.05):
                    if completed.is_set():
                        break
            self.on_level(0.0)
            if not self._cancel.is_set() and not completed.is_set():
                self.on_state("THINKING")
                websocket.send(json.dumps({
                    "schema_version": 1,
                    "command": "finalize",
                    "input_mode": "wake_word" if self._auto_finalize else "push_to_talk",
                    "state": "transcribing",
                }))
                completed.wait(180)
        except Exception as error:
            if not self._cancel.is_set():
                self.on_error(f"Push-to-talk nicht verfuegbar: {error}")
        finally:
            try:
                if websocket is not None:
                    websocket.close()
            except Exception:
                pass
            self._socket = None
            self._stream = None
            self.on_level(0.0)
            self.on_state("LISTENING")
            with self._lock:
                self._active = False
            self.on_complete()


class WakeWordListener:
    """Local ONNX wake-word loop. Audio is consumed block-by-block and discarded."""

    def __init__(
        self,
        on_wake: Callable[[], None],
        *,
        model_path: str | Path | None = None,
        provenance_path: str | Path | None = None,
        threshold: float | None = None,
        vad_threshold: float | None = None,
        cooldown_seconds: float | None = None,
        device: int | str | None = None,
        on_error: Callable[[str], None] | None = None,
    ):
        self.on_wake = on_wake
        configured_model = str(model_path or os.getenv("MICA_WAKE_WORD_MODEL", "")).strip()
        self.model_path = Path(configured_model).expanduser() if configured_model else Path("__mica_wake_word_not_configured__")
        configured_provenance = provenance_path or os.getenv("MICA_WAKE_WORD_PROVENANCE", "")
        self.provenance_path = (
            Path(configured_provenance).expanduser()
            if configured_provenance
            else self.model_path.with_name(self.model_path.name + ".provenance.json")
        )
        self.threshold = float(threshold if threshold is not None else os.getenv("MICA_WAKE_WORD_THRESHOLD", "0.5"))
        self.vad_threshold = float(vad_threshold if vad_threshold is not None else os.getenv("MICA_WAKE_WORD_VAD_THRESHOLD", "0.5"))
        self.cooldown_seconds = float(cooldown_seconds if cooldown_seconds is not None else os.getenv("MICA_WAKE_WORD_COOLDOWN_SECONDS", "3"))
        configured_device = device if device is not None else os.getenv("MICA_WAKE_WORD_DEVICE", "").strip()
        if isinstance(configured_device, str) and configured_device.isdecimal():
            configured_device = int(configured_device)
        self.device = configured_device if configured_device != "" else None
        self.on_error = on_error or (lambda _text: None)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_wake = 0.0

    @property
    def configured(self) -> bool:
        if not self.model_path.is_file() or not self.provenance_path.is_file():
            return False
        try:
            provenance = json.loads(self.provenance_path.read_text(encoding="utf-8"))
            digest = hashlib.sha256(self.model_path.read_bytes()).hexdigest()
            acceptance = provenance["acceptance"]
            required_text = ("source", "version", "license", "test_dataset")
            return (
                all(isinstance(provenance.get(key), str) and provenance[key].strip() for key in required_text)
                and provenance.get("sha256") == digest
                and int(acceptance.get("utterances", 0)) >= 40
                and int(acceptance.get("detections", 0)) >= 38
                and float(acceptance.get("background_hours", 0)) >= 8.0
                and int(acceptance.get("false_activations", 99)) <= 1
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return False

    def start(self) -> bool:
        if not self.configured or (self._thread and self._thread.is_alive()):
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="mica-wake-word", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=0.6)

    def _run(self) -> None:
        blocks: queue.Queue[bytes] = queue.Queue(maxsize=8)
        detected = False
        try:
            import numpy as np  # type: ignore[import-not-found]
            import sounddevice as sd  # type: ignore[import-not-found]
            from openwakeword.model import Model  # type: ignore[import-not-found]

            model = Model(wakeword_models=[str(self.model_path)], vad_threshold=self.vad_threshold)

            def capture(indata, _frames, _time_info, status):
                if status:
                    self.on_error(str(status))
                try:
                    blocks.put_nowait(bytes(indata))
                except queue.Full:
                    try:
                        blocks.get_nowait()
                        blocks.put_nowait(bytes(indata))
                    except queue.Empty:
                        pass

            with sd.RawInputStream(
                samplerate=16000, channels=1, dtype="int16", blocksize=1280,
                callback=capture, device=self.device,
            ):
                while not self._stop.is_set():
                    try:
                        payload = blocks.get(timeout=0.25)
                    except queue.Empty:
                        continue
                    prediction = model.predict(np.frombuffer(payload, dtype=np.int16))
                    score = max((float(value) for value in prediction.values()), default=0.0)
                    now = time.monotonic()
                    if score >= self.threshold and now - self._last_wake >= self.cooldown_seconds:
                        self._last_wake = now
                        self._stop.set()
                        detected = True
                        break
            if detected:
                # The detector stream is closed before push-to-talk reopens the
                # same physical microphone.
                self.on_wake()
        except Exception as error:
            if not self._stop.is_set():
                self.on_error(f"Wake-Word nicht verfuegbar: {error}")
