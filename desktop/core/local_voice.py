"""Privacy-preserving push-to-talk transport for the local Core websocket."""
from __future__ import annotations

from array import array
from contextlib import nullcontext
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
from .response_timing import RESPONSE_TIMINGS
from .voice_settings import VoiceSettingsStore, VOICE_DIAGNOSTICS
from .voice_signal import EndOfSpeech, EchoGuard

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
        on_native_command: Callable[[dict, str, threading.Event], str] | None = None,
        on_document: Callable[[dict], None] | None = None,
        before_recording: Callable[[], None] | None = None,
        conversation_mode: str = "personal",
        remember: Callable[[], bool] | None = None,
        response_timeout: float = 180.0,
    ):
        self.client = client
        self.on_state = on_state or (lambda _state: None)
        self.on_level = on_level or (lambda _level: None)
        self.on_transcript = on_transcript or (lambda _text: None)
        self.on_reply = on_reply or (lambda _text: None)
        self.on_error = on_error or (lambda _text: None)
        self.on_complete = on_complete or (lambda: None)
        self.on_native_command = on_native_command
        self.on_document = on_document or (lambda _document: None)
        self.before_recording = before_recording or (lambda: None)
        self.remember = remember or (lambda: True)
        self.response_timeout = response_timeout
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
        self._playback_lock = threading.Lock()
        self._output_device = None
        self._timing = None
        self._settings = VoiceSettingsStore().load()
        self._input_device = None
        self._capture_device_ready = False
        self._duplex_stream = None
        self._initial_audio = b""
        self._barge_audio = b""

    def take_barge_audio(self) -> bytes:
        with self._lock:
            audio, self._barge_audio = self._barge_audio, b""
            return audio

    def _state(self, state):
        VOICE_DIAGNOSTICS.update(state=state)
        self.on_state(state)

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def start(self, *, auto_finalize: bool = False, initial_audio: bytes = b"") -> bool:
        with self._lock:
            if self._active:
                return False
            self._active = True
            self._settings = VoiceSettingsStore().load()
            self._initial_audio = initial_audio
            self._barge_audio = b""
            self._capture_device_ready = False
            VOICE_DIAGNOSTICS.clear()
            VOICE_DIAGNOSTICS.update(state="CONNECTING", pause_seconds=self._settings.pause_seconds)
            # A late reader from an old session must retain its cancelled event.
            self._finish = threading.Event()
            self._cancel = threading.Event()
            self._auto_finalize = auto_finalize
            self._speech_started = False
            self._last_voice = 0.0
            self._started_at = time.monotonic()
            self._timing = RESPONSE_TIMINGS.begin('voice')
        self._worker = threading.Thread(target=self._run, name="mica-push-to-talk", daemon=True)
        self._worker.start()
        return True

    def finish(self) -> None:
        if self.active:
            self._finish.set()

    def cancel(self, *, preserve_barge: bool = False) -> None:
        # sounddevice.stop() interrupts a blocking sd.play() immediately.  It
        # is intentionally best-effort so Esc also remains safe before the
        # optional audio dependency is installed.
        if not preserve_barge:
            with self._lock:
                self._barge_audio = b""
        with self._playback_lock:
            self._cancel.set()
            self._finish.set()
            try:
                import sounddevice as sd  # type: ignore[import-not-found]

                sd.stop()
                if self._duplex_stream is not None:
                    self._duplex_stream.abort()
                if self._stream is not None:
                    self._stream.abort()
            except Exception:
                pass
        try:
            if self._socket is not None:
                # Wake recv without waiting for a close handshake on the UI thread.
                self._socket.abort()
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

    def _reader(self, websocket, completed: threading.Event, timing=None) -> None:
        from websocket import WebSocketTimeoutException

        cancelled = self._cancel
        try:
            while not cancelled.is_set() and not completed.is_set():
                try:
                    message = websocket.recv()
                except (WebSocketTimeoutException, TimeoutError):
                    continue
                if cancelled.is_set() or completed.is_set():
                    break
                if isinstance(message, bytes):
                    if timing:
                        timing.mark('audio')
                    self._play_response(message, cancelled)
                    if timing:
                        timing.finish('cancelled' if cancelled.is_set() else 'success')
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
                        self._state(mapped)
                    elif state == "cancelled":
                        self.cancel()
                        completed.set()
                    elif state == "failed":
                        VOICE_DIAGNOSTICS.update(error=str(payload.get("message", "Sprachverarbeitung fehlgeschlagen")),
                                                 service=payload.get("service", "core"))
                        if timing:
                            timing.finish('failed')
                        self.on_error(str(payload.get("message", "Sprachverarbeitung fehlgeschlagen")))
                        completed.set()
                elif event_type == "transcript":
                    if timing:
                        timing.mark('transcript')
                    self.on_transcript(str(payload.get("text", "")))
                    VOICE_DIAGNOSTICS.update(transcript=str(payload.get("text", ""))[:2000],
                                             raw_text=str(payload.get("raw_text", payload.get("text", "")))[:2000],
                                             corrections=payload.get("corrections", []), stt_ms=payload.get("stt_ms"))
                elif event_type == "response":
                    if timing:
                        timing.mark('reply')
                    self.on_reply(str(payload.get("text", "")))
                elif event_type == "document":
                    self.on_document(payload["document"])
                elif event_type == "native_command":
                    if cancelled.is_set():
                        continue
                    try:
                        reply = self.on_native_command(payload["command"], payload["message"], cancelled) if self.on_native_command else "Dieser Befehl ist nur in der nativen Mica-Oberfläche verfügbar."
                    except Exception:
                        reply = "Der lokale Befehl konnte nicht abgeschlossen werden."
                    if not cancelled.is_set():
                        websocket.send(json.dumps({"type": "native_command_result", "reply": reply[:2000]}, ensure_ascii=False))
                elif event_type == "error":
                    VOICE_DIAGNOSTICS.update(error=str(payload.get("message", "")), service=payload.get("service", "core"))
                    if timing:
                        timing.finish('failed')
                    self.on_error(str(payload.get("message", "Sprachverarbeitung fehlgeschlagen")))
                    completed.set()
        except Exception as error:
            if not cancelled.is_set() and not completed.is_set():
                VOICE_DIAGNOSTICS.update(error=f"Verbindung unterbrochen ({type(error).__name__})", service="connection")
                if timing:
                    timing.finish('failed')
                self.on_error(f"Sprachverbindung unterbrochen ({type(error).__name__}). Bitte erneut sprechen.")
            completed.set()

    def _play_response(self, payload: bytes, cancelled: threading.Event):
        import sounddevice as sd
        if not self._settings.barge_in or not self._capture_device_ready or not hasattr(sd, "RawStream"):
            return self._play_wav(payload, device=self._output_device, cancelled=cancelled,
                                  playback_lock=self._playback_lock)
        import io
        import wave
        import numpy as np
        with wave.open(io.BytesIO(payload), "rb") as wav:
            if wav.getsampwidth() != 2:
                raise LocalCoreError("TTS-WAV muss 16-bit PCM enthalten")
            rate, channels = wav.getframerate(), wav.getnchannels()
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768
        if channels > 1:
            samples = samples.reshape((-1, channels)).mean(axis=1)
        if rate != 16000 and samples.size:
            samples = np.interp(np.arange(round(len(samples) * 16000 / rate)) * rate / 16000,
                                np.arange(len(samples)), samples).astype(np.float32)
        guard = EchoGuard(self._settings.speech_threshold)
        offset = 0
        finished, interrupted = threading.Event(), threading.Event()
        seed = b""

        def duplex(indata, outdata, frames, _time_info, status):
            nonlocal offset, seed
            outdata[:] = bytes(frames * 2)
            if cancelled.is_set():
                finished.set()
                raise sd.CallbackStop
            if status:
                VOICE_DIAGNOSTICS.update(playback_warning="Audio-Gerät meldet Aussetzer.")
            reference = np.zeros(frames, dtype=np.float32)
            count = min(frames, len(samples) - offset)
            reference[:count] = samples[offset:offset + count]
            offset += count
            triggered, leading = guard.feed(np.frombuffer(indata, dtype="<i2").astype(np.float32) / 32768, reference)
            if triggered:
                seed = leading
                interrupted.set()
                finished.set()
                raise sd.CallbackStop
            outdata[:] = np.clip(reference * 32768, -32768, 32767).astype("<i2").tobytes()
            if offset >= len(samples):
                finished.set()
                raise sd.CallbackStop

        stream, started = None, False
        try:
            with self._playback_lock:
                if cancelled.is_set():
                    return
                stream = sd.RawStream(samplerate=16000, channels=1, dtype="int16", blocksize=1280,
                                      device=(self._input_device, self._output_device), callback=duplex,
                                      finished_callback=finished.set)
                self._duplex_stream = stream
                stream.start()
                started = True
            VOICE_DIAGNOSTICS.update(barge_in="active")
            while not finished.wait(0.03) and not cancelled.is_set():
                if not stream.active:
                    raise LocalCoreError("Audio-Gerät während der Wiedergabe getrennt.")
            if interrupted.is_set() and not cancelled.is_set():
                with self._lock:
                    self._barge_audio = seed
                VOICE_DIAGNOSTICS.update(barge_in="interrupted")
                self.cancel(preserve_barge=True)
            elif not cancelled.is_set():
                # CallbackStop drains the final output block before closing.
                while stream.active and not cancelled.wait(0.01):
                    pass
        except Exception as error:
            if started:
                raise LocalCoreError("Wiedergabe unterbrochen. Bitte Audio-Geräte prüfen.") from error
            VOICE_DIAGNOSTICS.update(barge_in="unavailable", playback_warning="Sprechen zum Unterbrechen ist mit diesen Geräten nicht verfügbar; Esc bleibt aktiv.")
            self._play_wav(payload, device=self._output_device, cancelled=cancelled,
                           playback_lock=self._playback_lock)
        finally:
            with self._playback_lock:
                self._duplex_stream = None
                if stream is not None:
                    stream.close()

    @staticmethod
    def _play_wav(payload: bytes, *, device=None, cancelled=None, playback_lock=None) -> None:
        if cancelled is not None and cancelled.is_set():
            return
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
        with playback_lock if playback_lock is not None else nullcontext():
            if cancelled is not None and cancelled.is_set():
                return
            sd.play(samples, rate, device=device, blocking=cancelled is None)
        if cancelled is not None:
            sd.wait()

    @staticmethod
    def _selected_device(kind: str):
        from desktop.core.audio_devices import resolve
        from desktop.memory.config_manager import get_input_device, get_output_device

        name = get_input_device() if kind == "input" else get_output_device()
        device = resolve(name, kind)
        if name and device is None:
            label = "Mikrofon" if kind == "input" else "Lautsprecher"
            raise LocalCoreError(f"Das gewaehlte {label} ist nicht verfuegbar. Bitte die Audio-Geraete pruefen.")
        return device

    @staticmethod
    def input_identity(device=None) -> str:
        import sounddevice as sd
        data = sd.query_devices(device, "input")
        return f"{data['name']} ({data['hostapi']})"

    def _run(self) -> None:
        timing = self._timing
        completed = threading.Event()
        websocket = None
        reader = None
        early_stream = None
        try:
            self.client.ensure_credentials()
            self.before_recording()
            import sounddevice as sd  # type: ignore[import-not-found]
            import websocket as websocket_client  # type: ignore[import-not-found]

            input_device = self._selected_device("input")
            self._input_device = input_device
            self._capture_device_ready = True
            self._output_device = self._selected_device("output")
            if self._cancel.is_set():
                return
            early_blocks = queue.Queue(maxsize=64)
            early_overflow = threading.Event()
            if self._initial_audio:
                # Keep the words spoken during the new TLS/WebSocket handshake.
                def early_capture(indata, _frames, _time_info, status):
                    if self._cancel.is_set():
                        return
                    if status:
                        early_overflow.set()
                    try:
                        early_blocks.put_nowait(bytes(indata))
                    except queue.Full:
                        early_overflow.set()
                early_stream = sd.RawInputStream(samplerate=16000, channels=1, dtype="int16", blocksize=1280,
                                                 device=input_device, callback=early_capture)
                self._stream = early_stream
                early_stream.start()
            self._state("CONNECTING")

            parsed = urlparse(self.client.base_url)
            voice_url = f"wss://{parsed.netloc}/v1/voice"
            websocket = websocket_client.create_connection(
                voice_url, timeout=10, sslopt=self._ssl_options(),
                origin=self.client.base_url,
                header=self.client.auth_headers,
            )
            self._socket = websocket
            if timing:
                timing.mark('connected')
            if self._cancel.is_set():
                return
            websocket.send(json.dumps({
                "schema_version": 1,
                "command": "start",
                "input_mode": "wake_word" if self._auto_finalize else "push_to_talk",
                "state": "listening",
                "conversation_mode": self.conversation_mode,
                "remember": bool(self.remember()),
                "name_aliases": self._settings.aliases,
                "session_id": getattr(self.client, "dialog_id", None),
                "native_commands": self.on_native_command is not None,
                "response_style": self._settings.response_style,
            }, ensure_ascii=False))
            websocket.settimeout(1.0)
            reader = threading.Thread(target=self._reader, args=(websocket, completed, timing), daemon=True)
            reader.start()
            if self._initial_audio:
                early_stream.close()
                early_stream = None
                self._stream = None
                if early_overflow.is_set():
                    raise LocalCoreError("Verbindung beim Unterbrechen zu langsam. Bitte erneut sprechen.")
                leading = bytearray(self._initial_audio)
                while not early_blocks.empty():
                    leading.extend(early_blocks.get_nowait())
                websocket.send_binary(bytes(leading))

            blocks: queue.Queue[bytes] = queue.Queue(maxsize=64)
            overflow = threading.Event()
            if self._settings.calibrated_device and self._settings.calibrated_device != self.input_identity(input_device):
                self._settings.speech_threshold = 0.035
                VOICE_DIAGNOSTICS.update(calibration="Mikrofon geändert; bitte neu kalibrieren.")
            detector = EndOfSpeech(self._settings, time.monotonic())
            if self._initial_audio:
                detector.last_voice = time.monotonic()
                detector.speech_seconds = 0.16

            def capture(indata, _frames, _time_info, status):
                if status:
                    self.on_error(str(status))
                if self._finish.is_set() or self._cancel.is_set():
                    return
                payload = bytes(indata)
                level = self._level(payload)
                self.on_level(level)
                VOICE_DIAGNOSTICS.update(level=round(level, 3))
                if self._auto_finalize:
                    now = time.monotonic()
                    reason = detector.feed(level, now)
                    if reason:
                        VOICE_DIAGNOSTICS.update(endpoint_reason=reason)
                        self._finish.set()
                # The audio callback must never wait for network I/O.
                try:
                    blocks.put_nowait(payload)
                except queue.Full:
                    overflow.set()
                    self._finish.set()

            if self._finish.is_set() or completed.is_set():
                return
            self._state("LISTENING")
            self._started_at = time.monotonic()
            with sd.RawInputStream(samplerate=16000, channels=1, dtype="int16", blocksize=1280,
                                   callback=capture, device=input_device) as stream:
                self._stream = stream
                while not self._finish.is_set() and not completed.is_set():
                    if not stream.active:
                        raise LocalCoreError("Das Mikrofon wurde getrennt. Bitte Audio-Geraete pruefen und erneut sprechen.")
                    try:
                        websocket.send_binary(blocks.get(timeout=0.05))
                    except queue.Empty:
                        continue
            if overflow.is_set():
                raise LocalCoreError("Die Sprachverbindung ist zu langsam. Bitte erneut versuchen.")
            while not blocks.empty() and not self._cancel.is_set() and not completed.is_set():
                websocket.send_binary(blocks.get_nowait())
            self.on_level(0.0)
            if not self._cancel.is_set() and not completed.is_set():
                self.before_recording()
                if self._cancel.is_set():
                    return
                self._state("THINKING")
                if timing:
                    timing.mark('submitted')
                websocket.send(json.dumps({
                    "schema_version": 1,
                    "command": "finalize",
                    "remember": bool(self.remember()),
                    "input_mode": "wake_word" if self._auto_finalize else "push_to_talk",
                    "state": "transcribing",
                }))
                if not completed.wait(self.response_timeout) and not self._cancel.is_set():
                    raise LocalCoreError("Die Sprachantwort hat zu lange gedauert. Bitte erneut versuchen.")
        except Exception as error:
            if not self._cancel.is_set():
                if timing:
                    timing.finish('failed')
                detail = str(error) if isinstance(error, LocalCoreError) else (
                    f"Sprachaufnahme nicht verfuegbar ({type(error).__name__}). "
                    "Bitte Audio-Geraete und Core-Verbindung pruefen."
                )
                self.on_error(detail)
                VOICE_DIAGNOSTICS.update(error=detail, service="capture" if self._stream else "connection")
        finally:
            if timing:
                timing.finish('cancelled')
            completed.set()
            self.cancel(preserve_barge=True)
            if early_stream is not None:
                early_stream.close()
            try:
                if websocket is not None:
                    websocket.close()
            except Exception:
                pass
            if reader is not None:
                reader.join(timeout=1.5)
            self._socket = None
            self._stream = None
            self.on_level(0.0)
            self._state("LISTENING")
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
        self._lifecycle_lock = threading.RLock()
        self._desired_running = False
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
        if not self.configured:
            return False
        with self._lifecycle_lock:
            self._desired_running = True
            if self._thread and self._thread.is_alive():
                # A concurrent stop may still be tearing the previous stream
                # down. Its finalizer will launch this requested generation.
                return True
            self._launch_locked()
        return True

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._desired_running = False
            self._stop.set()
            thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=0.6)

    def _launch_locked(self) -> None:
        self._stop = threading.Event()
        thread = threading.Thread(
            target=self._run,
            args=(self._stop,),
            name="mica-wake-word",
            daemon=True,
        )
        self._thread = thread
        thread.start()

    def _run(self, stop_event: threading.Event) -> None:
        blocks: queue.Queue[bytes] = queue.Queue(maxsize=8)
        detected = False
        try:
            import numpy as np  # type: ignore[import-not-found]
            import sounddevice as sd  # type: ignore[import-not-found]
            from openwakeword.model import Model  # type: ignore[import-not-found]

            model = Model(wakeword_models=[str(self.model_path)], vad_threshold=self.vad_threshold)
            device = self.device if self.device is not None else CoreVoiceSession._selected_device("input")
            if stop_event.is_set():
                return

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
                callback=capture, device=device,
            ):
                while not stop_event.is_set():
                    try:
                        payload = blocks.get(timeout=0.25)
                    except queue.Empty:
                        continue
                    prediction = model.predict(np.frombuffer(payload, dtype=np.int16))
                    score = max((float(value) for value in prediction.values()), default=0.0)
                    now = time.monotonic()
                    if score >= self.threshold and now - self._last_wake >= self.cooldown_seconds:
                        self._last_wake = now
                        stop_event.set()
                        detected = True
                        break
            if detected:
                # The detector stream is closed before push-to-talk reopens the
                # same physical microphone.
                with self._lifecycle_lock:
                    self._desired_running = False
                self.on_wake()
        except Exception as error:
            if not stop_event.is_set():
                with self._lifecycle_lock:
                    self._desired_running = False
                self.on_error(f"Wake-Word nicht verfuegbar: {error}")
        finally:
            self._finish_generation(threading.current_thread())

    def _finish_generation(self, current: threading.Thread) -> None:
        """Retire one detector generation and honor a queued restart request."""
        with self._lifecycle_lock:
            if self._thread is current:
                self._thread = None
                if self._desired_running:
                    self._launch_locked()
