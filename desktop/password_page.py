"""Local random password generation, with no transcript or persisted output."""
import secrets
import string
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (QApplication, QCheckBox, QHBoxLayout, QLabel, QLineEdit,
                            QPushButton, QSpinBox, QVBoxLayout, QWidget)


def random_password(length=20, symbols=True):
    if type(length) is not int or not 12 <= length <= 128 or type(symbols) is not bool:
        raise ValueError('Kennwortlänge: 12–128 Zeichen.')
    groups = [string.ascii_lowercase, string.ascii_uppercase, string.digits]
    if symbols:
        groups.append('!@#$%^&*+-_=')
    alphabet = ''.join(groups)
    # Guarantee selected character classes, then shuffle with OS randomness.
    characters = [secrets.choice(group) for group in groups]
    characters.extend(secrets.choice(alphabet) for _ in range(length - len(groups)))
    secrets.SystemRandom().shuffle(characters)
    return ''.join(characters)


class PasswordPage(QWidget):
    def __init__(self, parent=None, clipboard=None):
        super().__init__(parent)
        self.clipboard = clipboard or QApplication.clipboard()
        self._value, self._copied = '', ''
        layout = QVBoxLayout(self)
        note = QLabel('Ein zufälliges Kennwort lokal erzeugen. MICA speichert es weder im Chat noch in Dateien. '
                      'Anzeige und die aktuelle eigene Kopie in der Zwischenablage werden nach 60 Sekunden '
                      'oder beim Verlassen dieser Seite entfernt. Der Windows-Zwischenablageverlauf bleibt davon unberührt.')
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        row.addWidget(QLabel('Länge:'))
        self.length = QSpinBox()
        self.length.setRange(12, 128)
        self.length.setValue(20)
        row.addWidget(self.length)
        self.symbols = QCheckBox('Sonderzeichen verwenden')
        self.symbols.setChecked(True)
        row.addWidget(self.symbols)
        row.addStretch()
        layout.addLayout(row)
        self.generate_button = QPushButton('Kennwort erzeugen')
        self.generate_button.clicked.connect(self.generate)
        layout.addWidget(self.generate_button)
        self.output = QLineEdit()
        self.output.setReadOnly(True)
        self.output.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.output)
        self.show_value = QCheckBox('Kennwort anzeigen')
        self.show_value.toggled.connect(lambda checked: self.output.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
        layout.addWidget(self.show_value)
        row = QHBoxLayout()
        self.copy_button = QPushButton('Kopieren')
        self.copy_button.clicked.connect(self.copy)
        self.copy_button.setEnabled(False)
        row.addWidget(self.copy_button)
        clear = QPushButton('Jetzt entfernen')
        clear.clicked.connect(self.clear)
        row.addWidget(clear)
        layout.addLayout(row)
        self.status = QLabel('Noch kein Kennwort erzeugt.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(60000)
        self.timer.timeout.connect(self.clear)

    def generate(self):
        self.clear()
        self._value = random_password(self.length.value(), self.symbols.isChecked())
        self.output.setText(self._value)
        self.copy_button.setEnabled(True)
        self.status.setText('Lokal erzeugt. Anzeige wird nach 60 Sekunden entfernt.')
        self.timer.start()

    def copy(self):
        if self._value:
            self.clipboard.setText(self._value)
            self._copied = self._value
            self.status.setText('Kopiert. Die aktuelle eigene Zwischenablagekopie wird spätestens mit der Anzeige entfernt.')

    def clear(self):
        if self._copied and self.clipboard.text() == self._copied:
            self.clipboard.clear()
        self._value = self._copied = ''
        self.output.clear()
        self.show_value.setChecked(False)
        self.copy_button.setEnabled(False)
        self.timer.stop()
        self.status.setText('Kennwortanzeige entfernt.')

    def hideEvent(self, event):
        if hasattr(self, 'timer'):
            self.clear()
        super().hideEvent(event)
