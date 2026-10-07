"""Selected text stays local until an explicit transform; output is a preview."""
import threading
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QPlainTextEdit, QComboBox, QLineEdit, QPushButton
from desktop.ui_theme import C


class TextSelectionDialog(QDialog):
    _done = pyqtSignal(str, str)

    def __init__(self, parent, text, operation):
        super().__init__(parent)
        self.operation = operation
        shortcut = getattr(getattr(parent, '_selection_shortcut', None), 'label', 'Strg+Alt+M')
        self.setWindowTitle('Markierten Text bearbeiten · ' + shortcut)
        self.resize(600, 620)
        self.setStyleSheet(f'QDialog {{background:{C.PANEL};}} QLabel {{color:{C.TEXT};}} QPlainTextEdit,QComboBox,QLineEdit,QPushButton {{background:{C.PANEL2};color:{C.TEXT};padding:8px;}}')
        layout = QVBoxLayout(self)
        note = QLabel('Prüfe die Auswahl. Erst „Vorschau erstellen“ sendet diesen Text an das konfigurierte Modell. Private Cloudinhalte benötigen die bestehende Freigabe. Das Original bleibt unverändert.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.source = QPlainTextEdit(text)
        layout.addWidget(self.source)
        self.choice = QComboBox()
        for label, value in [('Erklären', 'explain'), ('Zusammenfassen', 'summarize'), ('Übersetzen', 'translate'), ('Umformulieren', 'rewrite')]:
            self.choice.addItem(label, value)
        layout.addWidget(self.choice)
        self.language = QLineEdit('Deutsch')
        self.language.setPlaceholderText('Zielsprache für Übersetzung')
        layout.addWidget(self.language)
        self.create = QPushButton('Vorschau erstellen')
        self.create.clicked.connect(self.run)
        layout.addWidget(self.create)
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setPlaceholderText('Hier erscheint das Ergebnis. Vor Verwendung prüfen; lange Texte können gekürzt werden.')
        layout.addWidget(self.result)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.copy = QPushButton('Ergebnis kopieren')
        self.copy.setEnabled(False)
        self.copy.clicked.connect(lambda: QApplication.clipboard().setText(self.result.toPlainText()))
        layout.addWidget(self.copy)
        close = QPushButton('Schließen')
        close.clicked.connect(self.reject)
        layout.addWidget(close)
        self._done.connect(self.ready)

    def run(self):
        text, language = self.source.toPlainText(), self.language.text().strip()
        if not text.strip() or len(text) > 16000 or not 1 <= len(language) <= 80:
            self.status.setText('Bitte 1–16.000 Zeichen und eine Zielsprache mit höchstens 80 Zeichen verwenden.')
            return
        choice = self.choice.currentData()
        self.create.setEnabled(False)
        self.copy.setEnabled(False)
        self.result.clear()
        self.status.setText('Vorschau wird erstellt …')
        def worker():
            try:
                reply, error = self.operation(text, choice, language)['reply'], ''
            except Exception as exc:
                reply, error = '', str(exc)
            self._done.emit(reply, error)
        threading.Thread(target=worker, name='mica-text-preview', daemon=True).start()

    def ready(self, reply, error):
        self.create.setEnabled(True)
        self.result.setPlainText(reply)
        self.copy.setEnabled(bool(reply) and not error)
        self.status.setText('Vorschau nicht erstellt: ' + error if error else 'Vorschau erstellt. Vor Verwendung prüfen.')
