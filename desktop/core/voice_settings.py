"""Non-secret local voice preferences and transient diagnostics."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
import json
import math
import os
from pathlib import Path
import tempfile
import threading
from mica_shared.voice_names import validate_aliases


@dataclass
class VoiceSettings:
    pause_seconds: float = 0.8
    speech_threshold: float = 0.035
    max_recording_seconds: float = 30.0
    barge_in: bool = True
    response_style: str = "brief"
    calibrated_device: str = ""
    aliases: list[dict[str, str]] = field(default_factory=list)

    def validate(self):
        for value, lower, upper in ((self.pause_seconds, 0.4, 3.0),
                                    (self.speech_threshold, 0.008, 0.6),
                                    (self.max_recording_seconds, 10.0, 90.0)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lower <= value <= upper:
                raise ValueError("Ungültige Sprach-Einstellung.")
        if type(self.barge_in) is not bool or not isinstance(self.calibrated_device, str):
            raise ValueError("Ungültige Sprach-Einstellung.")
        if self.response_style not in {"brief", "normal", "detailed"}:
            raise ValueError("Ungültige Antwortlänge.")
        self.aliases = validate_aliases(self.aliases)
        return self


class VoiceSettingsStore:
    def __init__(self, path=None):
        root = Path(__file__).resolve().parents[2]
        self.path = Path(path) if path else root / ".mica-data" / "voice-settings.json"

    def load(self) -> VoiceSettings:
        try:
            if self.path.stat().st_size > 32768:
                raise ValueError("Einstellungsdatei ist zu groß.")
            return VoiceSettings(**json.loads(self.path.read_text(encoding="utf-8"))).validate()
        except FileNotFoundError:
            return VoiceSettings()
        except (OSError, ValueError, TypeError):
            # A corrupt file must not turn on a fresh microphone listener.
            return VoiceSettings(barge_in=False)

    def save(self, settings: VoiceSettings):
        settings.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as output:
                name = output.name
                json.dump(asdict(settings), output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(name, self.path)
        finally:
            if name and Path(name).exists():
                Path(name).unlink()


class VoiceDiagnostics:
    """Only the latest session in memory; never persist transcripts/audio."""
    def __init__(self):
        self._lock = threading.Lock()
        self._value = {}

    def update(self, **values):
        with self._lock:
            self._value.update(values)

    def clear(self):
        with self._lock:
            self._value.clear()

    def snapshot(self):
        with self._lock:
            return dict(self._value)


VOICE_DIAGNOSTICS = VoiceDiagnostics()
