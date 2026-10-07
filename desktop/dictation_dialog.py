"""Explicit microphone clips; corrections remain in a reviewable text draft."""
import threading
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QPlainTextEdit, QPushButton
from desktop.core.dictation import DictationDraft, DictationCapture, record_clip


class DictationDialog(QDialog):
    _done = pyqtSignal(str, str, int)

    def __init__(self, parent, transcribe, transform, *, recording=record_clip):
        super().__init__(parent)
        self.transcribe, self.transform, self.recording = transcribe, transform, recording
        self.draft, self.capture = DictationDraft(), None
        self.busy, self.generation = False, 0
        self.setWindowTitle('Diktieren und korrigieren')
        self.resize(640, 500)
        layout = QVBoxLayout(self)
        note = QLabel('Sprich in Abschnitten bis zehn Sekunden. „Ersetze den letzten Satz durch …“, „Mach daraus Stichpunkte“ und „Rückgängig“ bearbeiten nur diese Vorschau. Prüfe den Text und kopiere ihn anschließend zum Einfügen. Audio und Diktat werden nicht gespeichert.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.editor = QPlainTextEdit()
        layout.addWidget(self.editor, 1)
        self.status = QLabel('Bereit. Das Mikrofon startet erst mit Diktieren.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.record = QPushButton('Diktieren')
        self.record.clicked.connect(self.toggle_record)
        layout.addWidget(self.record)
        self.bullets = QPushButton('Als Stichpunkte formulieren')
        self.bullets.clicked.connect(self.make_bullets)
        layout.addWidget(self.bullets)
        self.undo = QPushButton('Letzte Änderung rückgängig')
        self.undo.clicked.connect(self.undo_change)
        layout.addWidget(self.undo)
        self.copy = QPushButton('Geprüften Text kopieren zum Einfügen')
        self.copy.clicked.connect(lambda: QApplication.clipboard().setText(self.editor.toPlainText()))
        layout.addWidget(self.copy)
        self._done.connect(self.finished_work)
        self._bullets_done.connect(self.finished_bullets)

    def set_busy(self, value):
        self.busy = value
        self.editor.setReadOnly(value)
        for button in (self.bullets, self.undo, self.copy):
            button.setEnabled(not value)

    def toggle_record(self):
        if self.busy:
            if self.capture:
                self.capture.stop.set()
                self.record.setEnabled(False)
                self.status.setText('Spracherkennung läuft …')
            return
        self.draft.update(self.editor.toPlainText())
        self.capture = DictationCapture()
        capture, generation = self.capture, self.generation
        self.set_busy(True)
        self.record.setText('Aufnahme beenden')
        self.status.setText('Mikrofon aktiv · höchstens zehn Sekunden.')
        def worker():
            try:
                audio = self.recording(capture.stop, capture.cancelled)
                text = self.transcribe(audio)['text'] if audio and not capture.cancelled.is_set() else ''
                error = ''
            except Exception as exc:
                text, error = '', str(exc)
            if not capture.cancelled.is_set():
                self._done.emit(text, error, generation)
        threading.Thread(target=worker, name='mica-dictation', daemon=True).start()

    def finished_work(self, text, error, generation):
        if generation != self.generation:
            return
        self.capture = None
        self.set_busy(False)
        self.record.setEnabled(True)
        self.record.setText('Diktieren')
        if error:
            self.status.setText('Diktat nicht übernommen: ' + error)
            return
        try:
            action = self.draft.accept(text) if text.strip() else 'empty'
            self.editor.setPlainText(self.draft.text)
            if action == 'bullets':
                self.make_bullets()
            else:
                self.status.setText('Sprich jetzt den Ersatzsatz.' if action == 'replacement_pending' else 'Vorschau aktualisiert. Bitte prüfen.' if action != 'empty' else 'Kein Text erkannt.')
        except ValueError as exc:
            self.status.setText(str(exc))

    def make_bullets(self):
        self.draft.update(self.editor.toPlainText())
        if not self.draft.text.strip() or not self.transform:
            return
        self.set_busy(True)
        self.record.setEnabled(False)
        text, generation = self.draft.text, self.generation
        self.status.setText('Stichpunkte werden als Vorschau erstellt …')
        def worker():
            try:
                result, error = self.transform(text, 'bullets', 'Deutsch')['reply'], ''
            except Exception as exc:
                result, error = '', str(exc)
            # Reuse completion as a literal replacement, never as a spoken command.
            self._bullets_done.emit(result, error, generation)
        threading.Thread(target=worker, name='mica-dictation-bullets', daemon=True).start()

    _bullets_done = pyqtSignal(str, str, int)

    def finished_bullets(self, text, error, generation):
        if generation != self.generation:
            return
        self.set_busy(False)
        self.record.setEnabled(True)
        try:
            if not error:
                self.draft.update(text)
                self.editor.setPlainText(text)
            self.status.setText(error or 'Stichpunkte als Vorschau erstellt. Bitte prüfen.')
        except ValueError as exc:
            self.status.setText(str(exc))

    def undo_change(self):
        self.draft.update(self.editor.toPlainText())
        self.draft.undo()
        self.editor.setPlainText(self.draft.text)

    def done(self, result):
        self.generation += 1
        if self.capture:
            self.capture.cancelled.set()
            self.capture.stop.set()
        super().done(result)

    def cancel_capture(self):
        self.generation += 1
        if self.capture:
            self.capture.cancelled.set()
            self.capture.stop.set()
        self.capture = None
        self.set_busy(False)
        self.record.setEnabled(True)
        self.record.setText('Diktieren')
        self.status.setText('Aufnahme oder Bearbeitung abgebrochen. Die bisherige Vorschau bleibt erhalten.')
