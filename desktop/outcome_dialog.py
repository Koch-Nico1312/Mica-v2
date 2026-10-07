"""Explicit read-only checks with a visible baseline and evidence."""
import threading
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QFileDialog, QCheckBox
from desktop.core.outcome_verification import file_snapshot, verify_file, verify_window, window_snapshot


class OutcomeDialog(QDialog):
    _done = pyqtSignal(str, object)

    def __init__(self, parent, tracker=None):
        super().__init__(parent)
        self.tracker, self.baseline, self.window_baseline, self.busy = tracker, None, None, False
        self.setWindowTitle('Ergebnis prüfen')
        self.resize(620, 500)
        layout = QVBoxLayout(self)
        label = QLabel('Wähle eine Datei oder das zuletzt aktivierte andere Fenster. Die Prüfung liest nur auf deinen Klick. Für eine Änderung zuerst die Ausgangsfassung merken, dann im Programm speichern und erneut prüfen.')
        label.setWordWrap(True)
        layout.addWidget(label)
        self.path = QLineEdit()
        self.path.setPlaceholderText('Ausgewählte Datei')
        layout.addWidget(self.path)
        choose = QPushButton('Datei auswählen (auch noch nicht vorhandene Datei)')
        choose.clicked.connect(self.choose)
        layout.addWidget(choose)
        self.expected = QLineEdit()
        self.expected.setPlaceholderText('Erwartete Textstelle / sichtbare Meldung, optional für Dateien')
        self.expected.setMaxLength(1000)
        self.expected.setToolTip('Bei Schaltern zum Beispiel: Automatisch speichern (eingeschaltet). Lesbare Zustände stehen im Beleg.')
        layout.addWidget(self.expected)
        self.changed = QCheckBox('Änderung gegenüber der Ausgangsfassung nachweisen (Datei oder Fenster)')
        layout.addWidget(self.changed)
        self.baseline_label = QLabel('Noch keine Ausgangsfassung gemerkt.')
        self.baseline_label.setWordWrap(True)
        layout.addWidget(self.baseline_label)
        self.buttons = []
        for title, action in [('Datei-Ausgangsfassung merken', 'baseline'), ('Gespeicherte Datei prüfen', 'file'),
                ('Fenster-Ausgangsfassung merken', 'window_baseline'), ('Ausgewähltes Fenster prüfen', 'window')]:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, action=action: self.run(action))
            self.buttons.append(button)
            layout.addWidget(button)
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        layout.addWidget(self.result)
        close = QPushButton('Schließen')
        close.clicked.connect(self.reject)
        layout.addWidget(close)
        self._done.connect(self.finished_check)

    def choose(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Datei zur Prüfung auswählen', self.path.text(), 'Alle Dateien (*)', options=QFileDialog.Option.DontConfirmOverwrite)
        if path:
            self.path.setText(path)

    def reject(self):
        if self.busy:
            self.result.setPlainText('Prüfung läuft noch. Danach kannst du das Fenster schließen.')
            return
        super().reject()

    def run(self, action):
        if self.busy:
            return
        path, expected, changed = self.path.text().strip(), self.expected.text(), self.changed.isChecked()
        target = dict(self.tracker.target) if self.tracker and self.tracker.target else None
        if action in {'window', 'window_baseline'} and not target:
            self.result.setPlainText('Zuerst das gewünschte andere Fenster aktivieren und danach hier prüfen.')
            return
        if action in {'file', 'baseline'} and not path:
            self.result.setPlainText('Bitte eine Datei auswählen.')
            return
        if action in {'window', 'window_baseline'} and self.tracker.clock() - target['seen'] > 300:
            self.result.setPlainText('Fensterauswahl ist älter als fünf Minuten. Bitte das Fenster erneut aktivieren.')
            return
        self.busy = True
        for button in self.buttons:
            button.setEnabled(False)
        self.result.setPlainText('Prüfung läuft …')
        def worker():
            try:
                if action == 'baseline':
                    result = file_snapshot(path)
                elif action == 'file':
                    result = verify_file(path, baseline=self.baseline, expected_text=expected, require_changed=changed)
                elif action == 'window_baseline':
                    result = window_snapshot(target)
                else:
                    result = verify_window(target, expected, baseline=self.window_baseline, require_changed=changed)
            except Exception as error:
                result = {'status': 'uncertain', 'detail': str(error), 'evidence': {}}
            self._done.emit(action, result)
        threading.Thread(target=worker, name='mica-result-check', daemon=True).start()

    def finished_check(self, action, result):
        import json
        self.busy = False
        for button in self.buttons:
            button.setEnabled(True)
        if action == 'baseline' and 'path' in result:
            self.baseline = result
            self.baseline_label.setText('Ausgangsfassung: ' + result['path'] + ' · ' + ('vorhanden' if result['exists'] else 'noch nicht vorhanden'))
            self.result.setPlainText('Ausgangsfassung für diese Sitzung gemerkt. Es wurde keine Datei verändert.')
            return
        if action == 'window_baseline' and 'text' in result:
            if result['status'] == 'read':
                self.window_baseline = result
                self.baseline_label.setText('Fenster-Ausgangsfassung: ' + result['window'])
                self.result.setPlainText('Ausgangsfassung gemerkt:\n' + result['text'])
            else:
                self.window_baseline = None
                self.result.setPlainText('Unklar: Das Fenster bietet keine lesbare Ausgangsfassung.')
            return
        labels = {'confirmed': 'Bestätigt', 'not_confirmed': 'Nicht bestätigt', 'uncertain': 'Unklar'}
        self.result.setPlainText(labels.get(result['status'], 'Unklar') + '\n' + result['detail'] + '\n\nBeleg:\n' + json.dumps(result['evidence'], ensure_ascii=False, indent=2))
