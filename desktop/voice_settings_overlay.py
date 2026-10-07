"""Voice setup, guided microphone calibration and current-session diagnostics."""
from __future__ import annotations
import threading
import time
from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QPlainTextEdit,
                            QPushButton, QScrollArea, QVBoxLayout, QWidget)
from desktop.ui_settings import _HudOverlay
from desktop.ui_theme import C, ensure_ui_font
from desktop.core.voice_settings import VoiceSettingsStore, VOICE_DIAGNOSTICS
from desktop.core.voice_signal import calibration_metrics
from desktop.core.local_core_client import LocalCoreClient

TEST_PHRASE = "Bitte öffne meine Notizen und zeige mir die Aufgaben für morgen."


class VoiceSettingsOverlay(_HudOverlay):
    busy_changed = pyqtSignal(bool)
    _progress = pyqtSignal(str)
    _result = pyqtSignal(dict, str)
    _OW, _OH = 720, 640

    def __init__(self, parent=None, *, store=None, client_factory=LocalCoreClient, can_record=lambda: True):
        super().__init__(parent)
        ensure_ui_font()
        self.store, self.client_factory = store or VoiceSettingsStore(), client_factory
        self.can_record = can_record
        self.settings = self.store.load()
        self._stop, self._busy, self._recommendation = threading.Event(), False, None
        self.setFixedSize(self._OW, self._OH)
        self.setFont(QFont("Segoe UI", 9))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            VoiceSettingsOverlay {{background:{C.PANEL}; border:1px solid {C.BORDER}; border-radius:18px;}}
            QLabel,QCheckBox {{color:{C.TEXT}; background:transparent;}}
            QScrollArea {{background:{C.PANEL}; border:none;}}
            QPlainTextEdit,QDoubleSpinBox {{background:{C.PANEL2}; color:{C.TEXT}; border:1px solid {C.BORDER}; border-radius:8px; padding:6px;}}
            QPushButton {{background:{C.PANEL2}; color:{C.TEXT}; border:1px solid {C.BORDER}; border-radius:8px; padding:8px;}}
            QPushButton:hover {{background:{C.PRI_GHO};}}
            QPushButton:disabled {{color:{C.TEXT_DIM};}}
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        title = QLabel("Sprache einrichten")
        title.setStyleSheet("font-size:22px; font-weight:600;")
        root.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setStyleSheet(f"background:{C.PANEL};")
        layout = QVBoxLayout(content)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Pause nach dem Satz"))
        row = QHBoxLayout()
        self.pause = QDoubleSpinBox()
        self.pause.setRange(0.4, 3.0)
        self.pause.setSingleStep(0.1)
        self.pause.setSuffix(" Sekunden")
        self.pause.setValue(self.settings.pause_seconds)
        self.pause.setAccessibleName("Pause nach dem Satz")
        row.addWidget(self.pause)
        note = QLabel("Kürzer für schnelle Befehle; länger für Denkpausen. Gilt beim automatischen Zuhören.")
        note.setWordWrap(True)
        row.addWidget(note, 1)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Länge der Sprachantworten"))
        self.response_style = QComboBox()
        for label, value in (("Kurz", "brief"), ("Normal", "normal"), ("Ausführlich", "detailed")):
            self.response_style.addItem(label, value)
        self.response_style.setCurrentIndex(self.response_style.findData(self.settings.response_style))
        row.addWidget(self.response_style, 1)
        layout.addLayout(row)
        self.barge = QCheckBox("Mica durch Sprechen unterbrechen")
        self.barge.setChecked(self.settings.barge_in)
        layout.addWidget(self.barge)
        note = QLabel("Während der Antwort hört das Mikrofon auf deine Stimme. Micas eigene Ausgabe wird als Echo berücksichtigt. Esc und Stummschalten bleiben jederzeit verfügbar.")
        note.setWordWrap(True)
        layout.addWidget(note)

        layout.addWidget(QLabel("Mikrofon testen"))
        note = QLabel("Zwei Sekunden ruhig bleiben, dann den Testsatz sprechen. Der Test dauert acht Sekunden. Audio bleibt nur während des Tests im Speicher; der Satz löst keine Aktion aus.")
        note.setWordWrap(True)
        layout.addWidget(note)
        phrase = QLabel(TEST_PHRASE)
        phrase.setWordWrap(True)
        phrase.setStyleSheet(f"color:{C.PRI};")
        layout.addWidget(phrase)
        row = QHBoxLayout()
        self.calibrate = QPushButton("Test starten")
        self.calibrate.clicked.connect(self._calibrate)
        row.addWidget(self.calibrate)
        self.cancel_test = QPushButton("Abbrechen")
        self.cancel_test.setEnabled(False)
        self.cancel_test.clicked.connect(self._stop.set)
        row.addWidget(self.cancel_test)
        self.use_recommendation = QPushButton("Empfehlung übernehmen")
        self.use_recommendation.setEnabled(False)
        self.use_recommendation.clicked.connect(self._use_recommendation)
        row.addWidget(self.use_recommendation)
        layout.addLayout(row)
        self.calibration_result = QLabel("Noch kein Mikrofontest durchgeführt.")
        self.calibration_result.setWordWrap(True)
        self.calibration_result.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.calibration_result)

        layout.addWidget(QLabel("Namen und Projekte: gehörte Schreibweise → richtiger Name"))
        self.names = QPlainTextEdit()
        self.names.setPlaceholderText("Eine Korrektur pro Zeile, zum Beispiel:\nKoko → Coucou")
        self.names.setPlainText("\n".join(f"{entry['heard']} → {entry['name']}" for entry in self.settings.aliases))
        self.names.setFixedHeight(95)
        self.names.setAccessibleName("Lokales Namenwörterbuch")
        layout.addWidget(self.names)
        note = QLabel("Nur eingetragene Schreibweisen werden ersetzt. „Hallo Maika“ wird als Anrede zu „Hallo Mica“; ein Kontakt namens Maika bleibt erhalten.")
        note.setWordWrap(True)
        layout.addWidget(note)

        layout.addWidget(QLabel("Sprachdiagnose – aktuelle Sitzung"))
        self.diagnostics = QLabel("Noch keine Sprachsitzung.")
        self.diagnostics.setWordWrap(True)
        self.diagnostics.setTextFormat(Qt.TextFormat.PlainText)
        self.diagnostics.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.diagnostics)
        self.services = QLabel("Sprachdienste noch nicht geprüft.")
        self.services.setWordWrap(True)
        layout.addWidget(self.services)
        row = QHBoxLayout()
        self.probe = QPushButton("Sprachdienste prüfen")
        self.probe.clicked.connect(self._probe)
        row.addWidget(self.probe)
        clear = QPushButton("Diagnose leeren")
        clear.clicked.connect(VOICE_DIAGNOSTICS.clear)
        row.addWidget(clear)
        layout.addLayout(row)
        scroll.setWidget(content)
        root.addWidget(scroll)
        self.status = QLabel("Änderungen gelten für die nächste Aufnahme.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        row = QHBoxLayout()
        self.save = QPushButton("Speichern")
        self.save.clicked.connect(self._save)
        row.addWidget(self.save)
        close = QPushButton("Schließen")
        close.clicked.connect(self.hide)
        row.addWidget(close)
        root.addLayout(row)
        self._progress.connect(self.calibration_result.setText)
        self._result.connect(self._finished)
        self._health_result.connect(self._health_finished)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._diagnose)
        self.timer.start(500)

    def _save(self):
        try:
            aliases = []
            for line in self.names.toPlainText().splitlines():
                if not line.strip():
                    continue
                parts = line.split("→")
                if len(parts) != 2:
                    raise ValueError("Jede Zeile braucht gehörte Schreibweise → richtiger Name.")
                aliases.append({"heard": parts[0].strip(), "name": parts[1].strip()})
            self.settings.pause_seconds = self.pause.value()
            self.settings.barge_in = self.barge.isChecked()
            self.settings.response_style = self.response_style.currentData()
            self.settings.aliases = aliases
            self.store.save(self.settings)
            self.status.setText("Gespeichert. Die nächste Aufnahme verwendet diese Einstellungen.")
        except (OSError, ValueError) as error:
            self.status.setText(f"Nicht gespeichert: {error}")

    def _use_recommendation(self):
        if self._recommendation:
            self.settings.speech_threshold = self._recommendation["speech_threshold"]
            self.settings.calibrated_device = self._recommendation["device"]
            self._save()

    def _calibrate(self):
        if self._busy:
            return
        self._busy = True
        self._stop = threading.Event()
        self._recommendation = None
        self.use_recommendation.setEnabled(False)
        self.calibrate.setEnabled(False)
        self.save.setEnabled(False)
        self.probe.setEnabled(False)
        self.cancel_test.setEnabled(True)
        self.busy_changed.emit(True)
        self._progress.emit("Ruhig bleiben: Hintergrundgeräusche werden zwei Sekunden gemessen …")

        def worker():
            result, error, client = {}, "", None
            try:
                import sounddevice as sd
                from desktop.core.local_voice import CoreVoiceSession
                waiting = time.monotonic()
                while not self.can_record():
                    if self._stop.wait(0.04) or time.monotonic() - waiting > 3:
                        raise RuntimeError("Vorherige Sprachaufnahme wird noch beendet. Bitte erneut testen.")
                device = CoreVoiceSession._selected_device("input")
                identity = CoreVoiceSession.input_identity(device)
                chunks, statuses = [], []

                def capture(indata, frames, timing, status):
                    if status:
                        statuses.append(str(status))
                    if not self._stop.is_set() and len(chunks) < 100:
                        chunks.append(bytes(indata))

                with sd.RawInputStream(samplerate=16000, channels=1, dtype="int16", blocksize=1280,
                                       device=device, callback=capture) as stream:
                    started, prompted = time.monotonic(), False
                    while not self._stop.wait(0.04) and time.monotonic() - started < 8:
                        if not stream.active:
                            raise RuntimeError("Mikrofon getrennt. Bitte erneut versuchen.")
                        if not prompted and time.monotonic() - started >= 2:
                            prompted = True
                            self._progress.emit("Jetzt den Testsatz sprechen: " + TEST_PHRASE)
                if self._stop.is_set():
                    raise RuntimeError("Mikrofontest abgebrochen.")
                if statuses or len(chunks) < 90:
                    raise RuntimeError("Aufnahme enthält Aussetzer. Bitte das Audiogerät prüfen und erneut testen.")
                quiet, speech = b"".join(chunks[:25]), b"".join(chunks[25:])
                self._progress.emit("Testsatz wird lokal erkannt …")
                client = self.client_factory()
                transcript = client.calibrate_voice(speech)
                if self._stop.is_set():
                    raise RuntimeError("Mikrofontest abgebrochen.")
                result = calibration_metrics(quiet, speech, transcript["text"], TEST_PHRASE)
                result.update(text=transcript["text"], stt_ms=transcript.get("stt_ms"),
                              device=identity)
            except Exception as failure:
                error = str(failure)
            finally:
                if client is not None:
                    client.session.close()
                try:
                    self._result.emit(result, error)
                except RuntimeError:
                    pass
        threading.Thread(target=worker, name="mica-microphone-calibration", daemon=True).start()

    def _finished(self, result, error):
        self._busy = False
        self.calibrate.setEnabled(True)
        self.save.setEnabled(True)
        self.probe.setEnabled(True)
        self.cancel_test.setEnabled(False)
        self.busy_changed.emit(False)
        if error:
            self.calibration_result.setText(error)
            return
        self._recommendation = result if result.get("acceptable") else None
        self.use_recommendation.setEnabled(bool(self._recommendation))
        self.calibration_result.setText(
            f"Erkannt: {result['text']}\nTestsatz: {round(result['accuracy'] * 100)} % erkannt · Erkennung: {result['stt_ms']} ms\n"
            + "\n".join(result["recommendations"]))

    def _probe(self):
        self.probe.setEnabled(False)
        self.services.setText("Sprachdienste werden geprüft …")
        def worker():
            client = None
            try:
                client = self.client_factory()
                services = client.voice_health()["services"]
                labels = []
                for key, label in (("stt", "Spracherkennung"), ("tts", "Sprachausgabe")):
                    data = services.get(key, {})
                    ready = data.get("status") in {"ok", "ready"}
                    labels.append(f"{label}: {'bereit' if ready else 'nicht bereit'} ({data.get('engine', 'lokaler Dienst')})")
                self._health_result.emit("\n".join(labels))
            except Exception as error:
                self._health_result.emit(f"Core-Verbindung: {error}")
            finally:
                if client is not None:
                    client.session.close()
        threading.Thread(target=worker, name="mica-voice-health", daemon=True).start()

    _health_result = pyqtSignal(str)

    def _diagnose(self):
        if not self.isVisible():
            return
        data = VOICE_DIAGNOSTICS.snapshot()
        labels = {"CONNECTING": "Verbindet", "LISTENING": "Hört zu", "THINKING": "Verarbeitet", "SPEAKING": "Spricht"}
        lines = [labels.get(data.get("state"), "Noch keine Sprachsitzung.")]
        if data.get("transcript"):
            lines.append("Verstanden: " + data["transcript"])
        if data.get("corrections"):
            lines.append("Namenskorrekturen: " + ", ".join(data["corrections"]))
            lines.append("Ursprünglich: " + data.get("raw_text", ""))
        if data.get("stt_ms") is not None:
            lines.append(f"Spracherkennung: {data['stt_ms']} ms")
        if data.get("error"):
            service = {"stt": "Spracherkennung", "llm": "Antwort", "tts": "Sprachausgabe", "command": "Lokaler Befehl", "capture": "Mikrofon", "connection": "Verbindung"}.get(data.get("service"), "Core")
            lines.append(service + ": " + data["error"])
        for key in ("calibration", "playback_warning"):
            if data.get(key):
                lines.append(data[key])
        self.diagnostics.setText("\n".join(lines))

    def _health_finished(self, text):
        self.services.setText(text)
        self.probe.setEnabled(not self._busy)

    def hideEvent(self, event):
        self._stop.set()
        super().hideEvent(event)
