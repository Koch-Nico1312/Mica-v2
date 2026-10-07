"""Review an explicit conversational correction before durable confirmation."""
import threading
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox
from desktop.ui_theme import C


class PreferenceDialog(QDialog):
    _done = pyqtSignal(str)

    def __init__(self, parent, draft, operation):
        super().__init__(parent)
        self.draft, self.operation = dict(draft), operation
        self.setWindowTitle('Vorliebe aus dem Gespräch übernehmen')
        self.resize(470, 300)
        self.setStyleSheet(f'QDialog {{background:{C.PANEL};}} QLabel {{color:{C.TEXT};}} QLineEdit,QComboBox,QPushButton {{background:{C.PANEL2};color:{C.TEXT};padding:8px;}}')
        layout = QVBoxLayout(self)
        label = QLabel(f"Dauerhaft merken?\n{draft['key']}: {draft['value']}\nEine vorhandene Vorliebe mit demselben Schlüssel und Bereich wird ersetzt.")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.scope = QComboBox()
        for name, value in [('Alle Gespräche', 'global'), ('Technische Fragen', 'technical'), ('Persönliche Fragen', 'personal'), ('Monitoring', 'monitoring')]:
            self.scope.addItem(name, value)
        self.scope.setCurrentIndex(self.scope.findData(draft['scope']))
        layout.addWidget(self.scope)
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret.setPlaceholderText('Freigabe-Passwort, falls der Zugriff noch gesperrt ist')
        layout.addWidget(self.secret)
        self.status = QLabel('Speichern verwendet die bestehende lokale Freigabe. Ohne Bestätigung wird nichts dauerhaft geändert.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.save = QPushButton('Vorliebe dauerhaft speichern')
        self.save.clicked.connect(self.confirm)
        layout.addWidget(self.save)
        cancel = QPushButton('Verwerfen')
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)
        self._done.connect(self.finished_save)

    def confirm(self):
        self.save.setEnabled(False)
        draft = {key: self.draft[key] for key in ('key', 'value')}
        draft.update(scope=self.scope.currentData(), source='Bestätigte Gesprächskorrektur')
        secret = self.secret.text()
        self.secret.clear()
        def worker():
            try:
                self.operation(draft, secret)
                error = ''
            except Exception as exc:
                error = str(exc)
            self._done.emit(error)
        threading.Thread(target=worker, name='mica-preference-confirmation', daemon=True).start()

    def finished_save(self, error):
        self.save.setEnabled(True)
        if error:
            self.status.setText('Nicht gespeichert: ' + error)
        else:
            self.parent()._log.append_log('SYS: Bestätigte Vorliebe gespeichert.')
            self.accept()
