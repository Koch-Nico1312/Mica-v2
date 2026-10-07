"""Explicit checkpoint save/restore with a visible preview and async Core calls."""
import threading
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPlainTextEdit, QPushButton, QMessageBox
from desktop.core.workspace import WorkspaceStore
from desktop.ui_theme import C


class WorkspaceDialog(QDialog):
    _done = pyqtSignal(str, object, str)

    def __init__(self, parent, operation, documents, *, store=None, prefer_load=False):
        super().__init__(parent)
        self.operation, self.documents = operation, documents
        self.store = store or WorkspaceStore()
        self.saved = None
        self.setWindowTitle('Arbeitsstand speichern und weiterarbeiten')
        self.resize(520, 460)
        self.setStyleSheet(f'QDialog {{background:{C.PANEL};}} QLabel {{color:{C.TEXT};}} QPlainTextEdit,QPushButton {{background:{C.PANEL2};color:{C.TEXT};padding:8px;}}')
        layout = QVBoxLayout(self)
        note = QLabel('Speichert die ausgewählten Dokumentinhalte, die offene Aufgabe und deinen nächsten Schritt lokal. Laden stellt den Gesprächsbezug wieder her und führt keine gespeicherten Aktionen aus.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)
        self.step = QPlainTextEdit()
        self.step.setPlaceholderText('Nächster Schritt, zum Beispiel: Docker-Konfiguration vergleichen')
        layout.addWidget(self.step)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.save_button = QPushButton('Aktuellen Arbeitsstand speichern')
        self.load_button = QPushButton('Gespeicherten Arbeitsstand laden')
        self.forget_button = QPushButton('Gespeicherten Arbeitsstand löschen')
        self.buttons = [self.save_button, self.load_button, self.forget_button]
        for button in self.buttons:
            layout.addWidget(button)
        self.save_button.clicked.connect(lambda: self.run('save'))
        self.load_button.clicked.connect(lambda: self.run('load'))
        self.forget_button.clicked.connect(self.forget)
        close = QPushButton('Schließen')
        close.clicked.connect(self.reject)
        layout.addWidget(close)
        self._done.connect(self.done_operation)
        self.refresh(prefer_load)

    def refresh(self, prefer_load=False):
        try:
            self.saved = self.store.load()
            changed = self.store.warnings(self.saved)
            titles = ', '.join(doc['title'] for doc in self.saved['documents']) or 'keine Dateien'
            task_label = (self.saved.get('task_title') or 'Gespeicherte Aufgabe') if self.saved['task_id'] else 'keine'
            self.preview.setText('Gespeichert: ' + titles + '\nOffene Aufgabe: ' + task_label +
                ('\nGeändert oder fehlt: ' + ', '.join(changed) + '. Beim Laden wird die gespeicherte Fassung verwendet; unter Dateien kannst du neu einlesen.' if changed else ''))
            if prefer_load:
                self.step.setPlainText(self.saved['next_step'])
        except (OSError, ValueError, TypeError) as error:
            self.saved = None
            self.preview.setText('Kein lesbarer Arbeitsstand gespeichert.')
            if not isinstance(error, FileNotFoundError):
                self.status.setText(str(error))
        self.load_button.setEnabled(self.saved is not None)
        self.forget_button.setEnabled(self.saved is not None)

    def run(self, action):
        if action == 'save' and len(self.step.toPlainText()) > 2000:
            self.status.setText('Der nächste Schritt darf höchstens 2.000 Zeichen enthalten.')
            return
        if action == 'save' and self.saved and QMessageBox.question(self, 'Arbeitsstand ersetzen', 'Den gespeicherten Arbeitsstand durch die aktuelle Auswahl ersetzen?') != QMessageBox.StandardButton.Yes:
            return
        for button in self.buttons:
            button.setEnabled(False)
        self.status.setText('Arbeitsstand wird verarbeitet …')
        payload = {'documents': self.documents, 'next_step': self.step.toPlainText()} if action == 'save' else self.saved
        def worker():
            try:
                result, error = self.operation(action, payload, self.store), ''
            except Exception as exc:
                result, error = None, str(exc)
            self._done.emit(action, result, error)
        threading.Thread(target=worker, name='mica-workspace', daemon=True).start()

    def done_operation(self, action, result, error):
        for button in self.buttons:
            button.setEnabled(True)
        if error:
            self.status.setText('Arbeitsstand nicht übernommen: ' + error)
            self.refresh()
            return
        if action == 'load':
            parent = self.parent()
            parent._open_attachments()
            parent._attachment_overlay.replace_documents(result['documents'])
            parent._input.setText(result['next_step'])
            self.accept()
        else:
            self.refresh()
            self.status.setText('Arbeitsstand gespeichert.')

    def forget(self):
        if QMessageBox.question(self, 'Arbeitsstand löschen', 'Den gespeicherten Arbeitsstand löschen?') != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.forget()
            self.refresh()
            self.status.setText('Gespeicherter Arbeitsstand gelöscht.')
        except OSError as error:
            self.status.setText(str(error))
