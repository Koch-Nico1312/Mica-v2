"""Explicit folder selection and cancellable read-only size report."""
import threading
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget
from desktop.core.folder_analysis import analyze_folder, size_text


class FolderAnalysisPage(QWidget):
    completed = pyqtSignal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cancelled = threading.Event()
        self.busy = False
        self.completed.connect(self.receive)
        layout = QVBoxLayout(self)
        intro = QLabel('Einen ausgewählten Ordner auf große Dateien prüfen. Es werden nur Dateinamen und Größen gelesen; keine Datei wird geöffnet, verschoben oder gelöscht. Links und Windows-Reparse-Punkte werden übersprungen.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.choose = QPushButton('Ordner auswählen und prüfen …')
        self.choose.clicked.connect(self.start)
        layout.addWidget(self.choose)
        self.stop = QPushButton('Prüfung abbrechen')
        self.stop.clicked.connect(self.cancelled.set)
        self.stop.setEnabled(False)
        layout.addWidget(self.stop)
        self.status = QLabel('Noch kein Ordner geprüft.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        layout.addWidget(self.report, 1)

    def start(self):
        if self.busy:
            return
        path = QFileDialog.getExistingDirectory(self, 'Lokalen Ordner prüfen')
        if not path:
            return
        self.busy = True
        self.cancelled.clear()
        self.choose.setEnabled(False)
        self.stop.setEnabled(True)
        self.report.clear()
        self.status.setText('Dateigrößen werden geprüft …')
        def worker():
            result, error = None, ''
            try:
                result = analyze_folder(path, cancelled=self.cancelled)
            except (ValueError, OSError):
                error = 'Der Ordner ist nicht erreichbar oder nicht als lokaler Ordner geeignet.'
            try:
                self.completed.emit(result, error)
            except RuntimeError:
                pass
        threading.Thread(target=worker, daemon=True, name='mica-folder-analysis').start()

    def receive(self, result, error):
        self.busy = False
        self.choose.setEnabled(True)
        self.stop.setEnabled(False)
        if error:
            self.status.setText(error)
            return
        label = 'Prüfung abgeschlossen' if result['complete'] else 'Teilprüfung'
        reason = {'finished': 'Ordner durchlaufen', 'cancelled': 'abgebrochen',
                  'entry_limit': 'Dateigrenze erreicht', 'time_limit': 'Zeitbudget erreicht'}[result['reason']]
        self.status.setText(f"{label}: {reason}. {result['files']} Dateien · {size_text(result['bytes'])} logische Dateigröße · {result['skipped_links']} Links ausgelassen · {result['errors']} nicht lesbare Bereiche.")
        self.report.setPlainText(result['root'] + '\n\nGrößte gefundene Dateien (höchstens 20):\n' +
                                 '\n'.join(size_text(item['bytes']) + '  ' + item['path'] for item in result['largest']))

    def hideEvent(self, event):
        self.cancelled.set()
        super().hideEvent(event)
