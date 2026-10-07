"""Local endpoint detection, microphone measurements and playback echo guard."""
from __future__ import annotations
from collections import deque
import re
import numpy as np


def pcm_samples(audio: bytes):
    return np.frombuffer(audio, dtype="<i2").astype(np.float32) / 32768.0


def level(audio: bytes) -> float:
    samples = pcm_samples(audio)
    return min(1.0, float(np.sqrt(np.mean(samples * samples))) * 32768 / 8000) if samples.size else 0.0


class EndOfSpeech:
    def __init__(self, settings, started):
        self.settings, self.started = settings, started
        self.last_voice = None
        self.speech_seconds = 0.0

    def feed(self, measured: float, now: float, duration=0.08) -> str | None:
        if measured >= self.settings.speech_threshold:
            self.speech_seconds += duration
            if self.speech_seconds >= 0.16:
                self.last_voice = now
        elif self.last_voice is not None and now - self.last_voice >= self.settings.pause_seconds:
            return "pause"
        elif self.last_voice is None:
            self.speech_seconds = 0.0
        if now - self.started >= self.settings.max_recording_seconds:
            return "limit"
        return None


def calibration_metrics(quiet: bytes, speech: bytes, transcript: str, expected: str) -> dict:
    silence, voice = pcm_samples(quiet), pcm_samples(speech)
    if not silence.size or not voice.size:
        raise ValueError("Kalibrierung enthält kein Audio.")
    noise = float(np.sqrt(np.mean(silence * silence)))
    rms = float(np.sqrt(np.mean(voice * voice)))
    clipping = float(np.mean(np.abs(voice) >= 0.98))
    # Calibrate the same RMS scale that capture/endpoint detection uses.
    blocks = [silence[index:index + 1280] for index in range(0, len(silence), 1280)]
    noise_peak = float(np.percentile([np.sqrt(np.mean(block * block)) for block in blocks], 95))
    threshold = min(0.6, max(0.008, noise_peak * 32768 / 8000 * 3, 0.02))
    reference, heard = [re.findall(r"\w+", value.casefold()) for value in (expected, transcript)]
    distance = list(range(len(heard) + 1))
    for index, word in enumerate(reference, 1):
        current = [index]
        for column, recognized in enumerate(heard, 1):
            current.append(min(current[-1] + 1, distance[column] + 1,
                               distance[column - 1] + (word != recognized)))
        distance = current
    accuracy = max(0, 1 - distance[-1] / max(1, len(reference)))
    recommendations = []
    if clipping > 0.005:
        recommendations.append("Mikrofonverstärkung reduzieren: die Aufnahme übersteuert.")
    if rms < 0.015:
        recommendations.append("Näher ans Mikrofon sprechen oder die Verstärkung erhöhen.")
    if noise > 0.008 or rms < noise * 3:
        recommendations.append("Hintergrundgeräusche reduzieren; ein Headset kann helfen.")
    if accuracy < 0.8:
        recommendations.append("Testsatz erneut sprechen und das richtige Mikrofon prüfen.")
    acceptable = rms >= 0.015 and rms >= noise * 3 and clipping <= 0.005 and accuracy >= 0.8
    return {"noise_dbfs": round(20 * np.log10(max(noise, 1e-6)), 1),
            "speech_dbfs": round(20 * np.log10(max(rms, 1e-6)), 1),
            "clipping_percent": round(clipping * 100, 2), "accuracy": round(accuracy, 3),
            "speech_threshold": threshold, "acceptable": acceptable,
            "recommendations": recommendations or ["Pegel und Erkennung passen zum Testsatz."]}


class EchoGuard:
    """Remove the known playback component before sustained-speech detection.

    Fits delayed playback references, including short reflections, to the mic.
    This is an echo guard, not a guarantee of hardware acoustic cancellation.
    """
    def __init__(self, threshold: float):
        self.threshold = max(0.025, threshold)
        self.reference = np.zeros(6400, dtype=np.float32)
        self.history = deque(maxlen=6)
        self.consecutive = 0
        self.blocks = 0

    def feed(self, microphone, playback) -> tuple[bool, bytes]:
        count = len(microphone)
        self.reference = np.concatenate((self.reference[count:], playback))
        self.blocks += 1
        residual = microphone.astype(np.float32).copy()
        # Match up to 300 ms of acoustic delay using normalized correlation.
        window = self.reference[-(4800 + count):]
        energy = float(np.dot(residual, residual))
        if energy > 1e-8 and len(window) >= count:
            correlations = np.correlate(window, residual, mode="valid")
            squares = np.concatenate(([0], np.cumsum(window.astype(np.float64) ** 2)))
            energies = squares[count:] - squares[:-count]
            scores = np.abs(correlations) / np.sqrt(np.maximum(energies * energy, 1e-12))
            offset = int(np.argmax(scores))
            if scores[offset] >= 0.35:
                columns = []
                for shift in (0, -64, 64, -320, -640, -1280):
                    start = offset + shift
                    if 0 <= start <= len(window) - count:
                        columns.append(window[start:start + count])
                design = np.column_stack(columns)
                coefficients = np.linalg.lstsq(design, residual, rcond=0.02)[0]
                residual -= design @ coefficients
        rms_level = float(np.sqrt(np.mean(residual * residual))) * 32768 / 8000
        self.history.append(np.clip(residual * 32768, -32768, 32767).astype("<i2").tobytes())
        self.consecutive = self.consecutive + 1 if rms_level >= self.threshold else 0
        # Ignore device start transients; require at least 240 ms of speech.
        triggered = self.blocks >= 4 and self.consecutive >= 3
        return triggered, b"".join(self.history) if triggered else b""
