"""Physical PTT and Escape-interruption acceptance for MICA.

No microphone PCM, spoken text beyond the fixed test sentences, or reply audio
is persisted. The resulting JSON contains only transcripts and timing evidence.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.local_core_client import LocalCoreClient
from core.local_voice import CoreVoiceSession


SENTENCES = [
    "Hallo Mica, wie spät ist es heute?",
    "Bitte erkläre mir kurz den Unterschied zwischen WLAN und LAN.",
    "Meine Einkaufsliste enthält Äpfel, Öl und zwölf Brötchen.",
    "Erinnere mich daran, morgen um sieben Uhr aufzustehen.",
    "Wie viel sind siebenundzwanzig mal vier?",
    "Österreich hat neun Bundesländer.",
    "Der nächste Termin beginnt um vierzehn Uhr dreißig.",
    "Bitte antworte heute besonders kurz und direkt.",
    "Mein Computer benötigt eine sichere Datensicherung.",
    "Prüfe den Status, aber ändere keine Dateien.",
    "Die Außentemperatur beträgt ungefähr zwölf Grad.",
    "Kannst du Umlaute wie ä, ö und ü verstehen?",
    "Nenne mir drei einfache Schritte für dieses Problem.",
    "Der Ordner heißt Projekte und liegt auf Laufwerk C.",
    "Ich möchte den persönlichen Gesprächsmodus verwenden.",
    "Wechsle nicht deine Persönlichkeit oder deinen Namen.",
    "Achte bitte auf Datenschutz und lokale Verarbeitung.",
    "Die Zahl eintausendvierundzwanzig soll korrekt erkannt werden.",
    "Fasse das Ergebnis in einem einzigen Satz zusammen.",
    "Danke Mica, dieser Sprachtest ist jetzt abgeschlossen.",
]


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zäöüß0-9]+", text.casefold())


def _word_error_rate(expected: str, actual: str) -> float:
    left, right = _words(expected), _words(actual)
    if not left:
        return 0.0 if not right else 1.0
    previous = list(range(len(right) + 1))
    for index, word in enumerate(left, 1):
        current = [index]
        for column, other in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (word != other),
            ))
        previous = current
    return previous[-1] / len(left)


def _write_result(path: Path, section: str, value: dict[str, object]) -> None:
    existing: dict[str, object] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, json.JSONDecodeError):
            pass
    existing.update({"schema_version": 1, section: value})
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def run_ptt(output: Path) -> int:
    results: list[dict[str, object]] = []
    print("Dieser Test nutzt den echten MICA-Core und das echte Mikrofon. Audio wird nicht gespeichert.")
    for number, expected in enumerate(SENTENCES, 1):
        transcript: list[str] = []
        errors: list[str] = []
        completed = threading.Event()
        session = CoreVoiceSession(
            LocalCoreClient(),
            on_transcript=lambda text: transcript.append(text),
            on_error=lambda text: errors.append(text),
            on_complete=completed.set,
        )
        input(f"\n{number}/20: Lies nach Enter vor:\n  {expected}\nEnter startet Push-to-Talk …")
        if not session.start():
            raise RuntimeError("Push-to-Talk konnte nicht gestartet werden")
        input("Sprich jetzt. Drücke Enter, sobald du fertig bist …")
        session.finish()
        completed.wait(190)
        recognized = transcript[-1].strip() if transcript else ""
        wer = _word_error_rate(expected, recognized)
        print(f"Erkannt: {recognized or '[nichts]'}\nWortfehlerrate: {wer:.1%}")
        confirmed = input("War der Satz praktisch korrekt erkannt? [j/N] ").strip().casefold() in {"j", "ja", "y", "yes"}
        passed = bool(recognized) and wer <= 0.20 and confirmed and not errors
        results.append({
            "trial": number, "expected": expected, "transcript": recognized,
            "word_error_rate": round(wer, 4), "human_confirmed": confirmed,
            "errors": errors, "passed": passed,
        })
    section = {
        "checked_at": datetime.now(UTC).isoformat(),
        "trials": results,
        "passed_count": sum(bool(item["passed"]) for item in results),
        "required_count": 20,
        "passed": len(results) == 20 and all(bool(item["passed"]) for item in results),
        "audio_saved": False,
    }
    _write_result(output, "push_to_talk", section)
    print(json.dumps(section, ensure_ascii=False, indent=2))
    return 0 if section["passed"] else 2


def run_interrupt(output: Path, sample: Path) -> int:
    from PyQt6.QtCore import QTimer, Qt
    from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
    import sounddevice as sd  # type: ignore[import-not-found]

    payload = sample.read_bytes()
    results: list[dict[str, object]] = []

    class Probe(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("MICA – physischer Escape-Test")
            self.resize(620, 180)
            self.label = QLabel()
            self.label.setWordWrap(True)
            layout = QVBoxLayout(self)
            layout.addWidget(self.label)
            self.thread: threading.Thread | None = None
            self.pressed_at: float | None = None
            self.finished_at: float | None = None
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.poll)
            self.timer.start(5)
            self.refresh("Drücke Leertaste für Versuch 1. Sobald du die Stimme hörst, drücke Escape.")

        def refresh(self, message: str) -> None:
            self.label.setText(message)

        def start_trial(self) -> None:
            if self.thread and self.thread.is_alive() or len(results) >= 20:
                return
            self.pressed_at = None
            self.finished_at = None

            def playback() -> None:
                try:
                    CoreVoiceSession._play_wav(payload)
                finally:
                    self.finished_at = time.perf_counter()

            self.thread = threading.Thread(target=playback, daemon=True)
            self.thread.start()
            self.refresh(f"Versuch {len(results) + 1}/20 läuft – jetzt Escape drücken.")

        def keyPressEvent(self, event):
            if event.key() == Qt.Key.Key_Space:
                self.start_trial()
                return
            if event.key() == Qt.Key.Key_Escape and self.thread and self.thread.is_alive() and self.pressed_at is None:
                self.pressed_at = time.perf_counter()
                sd.stop()
                self.refresh("Escape erkannt; Wiedergabestopp wird gemessen …")
                return
            super().keyPressEvent(event)

        def poll(self) -> None:
            if not self.thread or self.thread.is_alive() or self.finished_at is None:
                return
            if self.pressed_at is None:
                results.append({"trial": len(results) + 1, "latency_ms": None, "passed": False, "reason": "audio_ended_without_escape"})
            else:
                latency = max(0.0, (self.finished_at - self.pressed_at) * 1000)
                results.append({"trial": len(results) + 1, "latency_ms": round(latency, 3), "passed": latency < 200.0})
            self.thread = None
            if len(results) >= 20:
                QApplication.instance().quit()
            else:
                self.refresh(
                    f"Versuch {len(results)}/20 erfasst. Drücke Leertaste für Versuch {len(results) + 1}."
                )

    app = QApplication.instance() or QApplication(sys.argv)
    probe = Probe()
    probe.show()
    probe.activateWindow()
    app.exec()
    section = {
        "checked_at": datetime.now(UTC).isoformat(), "sample": str(sample.resolve()),
        "trials": results, "required_count": 20, "threshold_ms": 200,
        "passed": len(results) == 20 and all(bool(item["passed"]) for item in results),
        "audio_saved_by_probe": False,
    }
    _write_result(output, "tts_interrupt", section)
    print(json.dumps(section, ensure_ascii=False, indent=2))
    return 0 if section["passed"] else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="MICA physical voice acceptance")
    parser.add_argument("command", choices=("ptt", "interrupt"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/phase0-voice-acceptance-current.json"))
    parser.add_argument("--sample", type=Path, default=Path("artifacts/phase1-voice-samples/kokoro-df_kerstin.wav"))
    args = parser.parse_args()
    if args.command == "ptt":
        return run_ptt(args.output.resolve())
    if not args.sample.is_file():
        raise SystemExit(f"Sprachprobe fehlt: {args.sample}")
    return run_interrupt(args.output.resolve(), args.sample.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
