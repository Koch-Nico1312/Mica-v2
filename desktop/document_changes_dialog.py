"""Historical baseline chooser, local diff and an explicitly requested explanation."""
import threading
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QPlainTextEdit, QPushButton
from desktop.core.document_changes import compare_document
from desktop.core.workspace import ProjectWorkspaceStore
from desktop.ui_theme import C


class DocumentChangesDialog(QDialog):
    _done = pyqtSignal(object, str)

    def __init__(self, parent, documents, transform, *, store=None):
        super().__init__(parent)
        self.transform, self.comparison = transform, None
        self.setWindowTitle('Dokumentänderungen vergleichen')
        self.resize(760, 620)
        self.setStyleSheet(f'QDialog {{background:{C.PANEL};}} QLabel {{color:{C.TEXT};}} QPlainTextEdit,QComboBox,QPushButton {{background:{C.PANEL2};color:{C.TEXT};padding:8px;}}')
        layout = QVBoxLayout(self)
        note = QLabel('Wähle eine bekannte Ausgangsfassung. Verglichen wird mit der Datei auf deinem Rechner. Für „seit gestern“ brauchst du eine gestern gespeicherte Fassung; Mica erfindet keinen früheren Stand. Die Gesprächsauswahl wird dabei nicht verändert.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.choice = QComboBox()
        layout.addWidget(self.choice)
        for document in documents:
            if document.get('local_path'):
                self.choice.addItem(document['title'] + ' · eingelesen ' + document.get('loaded_at', '(unbekannt)'), (document, None))
        load_error = ''
        try:
            for name, versions in (store or ProjectWorkspaceStore()).all().items():
                for version in reversed(versions):
                    for document in version['documents']:
                        if document.get('local_path'):
                            self.choice.addItem(name + ' · ' + document['title'] + ' · ' + version['saved_at'], (document, version['saved_at']))
        except (OSError, ValueError, KeyError) as error:
            load_error = '\nGespeicherte Projektfassungen nicht lesbar: ' + str(error)
        self.status = QLabel(('Ausgangsfassung wählen und vergleichen.' if self.choice.count() else 'Keine Ausgangsfassung verfügbar. Zuerst eine Datei einlesen oder einen Projektstand speichern.') + load_error)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        layout.addWidget(self.result, 1)
        self.compare = QPushButton('Mit aktueller Datei vergleichen')
        self.compare.setEnabled(self.choice.count() > 0)
        self.compare.clicked.connect(self.run_compare)
        layout.addWidget(self.compare)
        self.explain = QPushButton('Änderungen erklären')
        self.explain.setEnabled(False)
        self.explain.clicked.connect(self.run_explain)
        layout.addWidget(self.explain)
        close = QPushButton('Schließen')
        close.clicked.connect(self.reject)
        layout.addWidget(close)
        self.choice.currentIndexChanged.connect(self.reset)
        self._done.connect(self.finished_work)

    def reset(self):
        self.comparison = None
        self.result.clear()
        self.explain.setEnabled(False)

    def work(self, action):
        self.choice.setEnabled(False)
        self.compare.setEnabled(False)
        self.explain.setEnabled(False)
        self.status.setText('Wird verarbeitet …')
        def worker():
            try:
                result, error = action(), ''
            except Exception as exc:
                result, error = None, str(exc)
            self._done.emit(result, error)
        threading.Thread(target=worker, name='mica-document-diff', daemon=True).start()

    def run_compare(self):
        document, timestamp = self.choice.currentData()
        self.work(lambda: compare_document(document, baseline_at=timestamp))

    def run_explain(self):
        if self.comparison:
            payload = 'Erkläre die Änderungen und ihre Bedeutung. Behaupte nichts über ausgelassene Bereiche.\nAusgangsfassung: ' + self.comparison['baseline_at'] + '\nAktuell: ' + self.comparison['current_at'] + '\nVergleich' + (' (gekürzter Ausschnitt)' if self.comparison['diff_truncated'] or self.comparison['extraction_truncated'] else '') + ':\n' + self.comparison['diff']
            self.work(lambda: self.transform(payload, 'explain', 'Deutsch'))

    def finished_work(self, value, error):
        self.choice.setEnabled(True)
        self.compare.setEnabled(self.choice.count() > 0)
        if error:
            self.status.setText('Vergleich nicht abgeschlossen: ' + error)
        elif 'diff' in value:
            self.comparison = value
            self.result.setPlainText(value['diff'] or 'Keine Textänderungen zwischen diesen Fassungen.')
            self.status.setText('Ausgangsfassung: ' + value['baseline_at'] + '\nAktuell: ' + value['current_at'] +
                ('\nAusschnitt: Die Extraktion oder der Vergleich ist gekürzt.' if value['diff_truncated'] or value['extraction_truncated'] else ''))
        else:
            self.result.setPlainText(self.comparison['diff'] + '\n\nErklärung:\n' + value['reply'])
            self.status.setText('Erklärung erstellt; Textstellen oben prüfen.')
        self.explain.setEnabled(bool(self.comparison and self.comparison['changed'] and self.transform))
