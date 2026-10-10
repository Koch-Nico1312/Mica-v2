"""Edit a task's saved file check, inspect evidence, then explicitly stage completion."""
import threading
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox, QFileDialog
from desktop.core.task_criteria import TaskCriteriaStore


class TaskCriteriaDialog(QDialog):
    _done = pyqtSignal(str, object, str)

    def __init__(self, parent, identifier, operation, task_store, *, criteria=None):
        super().__init__(parent)
        self.identifier, self.operation, self.task_store = identifier, operation, task_store
        self.criteria = criteria or TaskCriteriaStore()
        self.busy = False
        self.setWindowTitle('Erledigt, wenn …')
        self.resize(620, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Die Prüfung liest nur die ausgewählte Datei. Erledigen wird erst nach deiner Bestätigung lokal vorgemerkt.'))
        self.path, self.text = QLineEdit(), QLineEdit()
        self.path.setMaxLength(4096)
        self.text.setMaxLength(2000)
        self.text.setPlaceholderText('Erwartete Textstelle; leer bedeutet: Datei vorhanden und lesbar')
        layout.addWidget(self.path)
        choose = QPushButton('Prüfdatei auswählen')
        choose.clicked.connect(self.choose)
        layout.addWidget(choose)
        layout.addWidget(self.text)
        self.changed = QCheckBox('Gespeicherter Inhalt muss sich seit Speichern dieses Kriteriums geändert haben')
        layout.addWidget(self.changed)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.buttons = []
        for title, action in [('Kriterium und Ausgangsfassung speichern', 'criteria_set'),
                              ('Gespeichertes Kriterium prüfen', 'criteria_check'),
                              ('Nach erneuter Prüfung als erledigt vormerken', 'criteria_complete'),
                              ('Prüfkriterium entfernen', 'criteria_remove')]:
            button = QPushButton(title)
            button.clicked.connect(lambda _, value=action: self.run(value))
            layout.addWidget(button)
            self.buttons.append(button)
        saved = self.criteria.read().get(identifier)
        if saved:
            self.path.setText(saved['path'])
            self.text.setText(saved['expected_text'])
            self.changed.setChecked(saved['require_changed'])
        self._done.connect(self.finished)

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Prüfdatei auswählen', self.path.text())
        if path:
            self.path.setText(path)

    def run(self, action):
        if self.busy:
            return
        if action in {'criteria_check', 'criteria_complete'}:
            from pathlib import Path
            try:
                saved = self.criteria.read().get(self.identifier)
            except (OSError, ValueError) as error:
                self.status.setText('Gespeichertes Kriterium nicht lesbar: ' + str(error))
                return
            if not saved or (str(Path(self.path.text()).expanduser().resolve()), self.text.text(), self.changed.isChecked()) != (saved['path'], saved['expected_text'], saved['require_changed']):
                self.status.setText('Eingaben geändert. Zuerst das Kriterium speichern, danach prüfen.')
                return
        self.busy = True
        for widget in (self.path, self.text, self.changed):
            widget.setEnabled(False)
        for button in self.buttons:
            button.setEnabled(False)
        payload = {'identifier': self.identifier, 'path': self.path.text(), 'expected_text': self.text.text(),
            'require_changed': self.changed.isChecked(), 'criteria_store': self.criteria}
        self.status.setText('Gespeichertes Kriterium wird verarbeitet …')
        def worker():
            try:
                result, error = self.operation(action, payload, self.task_store), ''
            except Exception as exc:
                result, error = None, str(exc)
            self._done.emit(action, result, error)
        threading.Thread(target=worker, name='mica-task-criteria', daemon=True).start()

    def finished(self, action, result, error):
        self.busy = False
        for widget in (self.path, self.text, self.changed):
            widget.setEnabled(True)
        for button in self.buttons:
            button.setEnabled(True)
        self.status.setText(error or ('Erledigt lokal vorgemerkt. Erst unter Abgleich ins Backend übernehmen.' if action == 'criteria_complete'
            else {'confirmed': 'Bestätigt', 'not_confirmed': 'Nicht bestätigt', 'uncertain': 'Unklar'}[result['status']] + ': ' + result['detail'] if action == 'criteria_check'
            else 'Prüfkriterium gespeichert.' if action == 'criteria_set' else 'Prüfkriterium entfernt.'))

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)
