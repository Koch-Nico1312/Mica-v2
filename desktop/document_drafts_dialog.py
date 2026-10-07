"""Review document-derived tasks/cards before any explicit persistence."""
import threading
import uuid
from datetime import datetime
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView
from desktop.ui_theme import C


class DocumentDraftsDialog(QDialog):
    _done = pyqtSignal(str, object, str)

    def __init__(self, parent, documents, operation, *, kind='tasks', instruction=''):
        super().__init__(parent)
        self.documents, self.operation, self.kind, self.instruction = documents, operation, kind, instruction
        self.items, self.saved = [], set()
        self.setWindowTitle('Aufgaben aus Dokumenten' if kind == 'tasks' else 'Lernkarten aus Dokumenten')
        self.resize(850, 550)
        self.setStyleSheet(f'QDialog {{background:{C.PANEL};}} QLabel {{color:{C.TEXT};}} QTableWidget,QPushButton {{background:{C.PANEL2};color:{C.TEXT};padding:6px;}}')
        layout = QVBoxLayout(self)
        note = QLabel('Nur ausgewählte Dokumente verwenden. Prüfe jeden Vorschlag und seine Textstelle. Titel/Fragen und Termine lassen sich bearbeiten. Erst „Auswahl speichern“ legt die ausgewählten Einträge an. Aufgaben mit Termin erhalten eine Erinnerung mit Erledigt, Schlummern und Aufgabenansicht. Ein leerer Termin bedeutet: keine Frist.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Auswahl', 'Aufgabe' if kind == 'tasks' else 'Frage', 'Termin mit Zeitzone' if kind == 'tasks' else 'Antwort', 'Quelle und Textstelle'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        self.status = QLabel('Bitte Dokumente auswählen.' if not documents else 'Vorschläge erstellen und prüfen.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.generate = QPushButton('Vorschläge erstellen')
        self.generate.setEnabled(bool(documents and operation))
        self.generate.clicked.connect(self.draft)
        layout.addWidget(self.generate)
        self.save = QPushButton('Auswahl speichern')
        self.save.setEnabled(False)
        self.save.clicked.connect(self.persist)
        layout.addWidget(self.save)
        close = QPushButton('Schließen')
        close.clicked.connect(self.reject)
        layout.addWidget(close)
        self._done.connect(self.finished_work)

    def work(self, action, call):
        self.generate.setEnabled(False)
        self.save.setEnabled(False)
        self.table.setEnabled(False)
        self.status.setText('Wird verarbeitet …')
        def worker():
            try:
                result, error = call(), ''
            except Exception as exc:
                result, error = None, str(exc)
            self._done.emit(action, result, error)
        threading.Thread(target=worker, name='mica-document-drafts', daemon=True).start()

    def draft(self):
        self.work('draft', lambda: self.operation('draft', {'documents': self.documents, 'kind': self.kind, 'instruction': self.instruction}))

    def persist(self):
        selected = []
        try:
            for row, item in enumerate(self.items):
                if row in self.saved or self.table.item(row, 0).checkState() != Qt.CheckState.Checked:
                    continue
                field = 'title' if self.kind == 'tasks' else 'question'
                changed = {**item, field: self.table.item(row, 1).text().strip()}
                if not changed[field] or len(changed[field]) > (160 if self.kind == 'tasks' else 500):
                    raise ValueError('Bitte einen gültigen Titel oder eine Frage eingeben.')
                if self.kind == 'tasks':
                    due = self.table.item(row, 2).text().strip()
                    if due and datetime.fromisoformat(due).tzinfo is None:
                        raise ValueError('Termine benötigen eine Zeitzone, etwa 2026-10-08T16:00:00+02:00.')
                    changed['due_at'] = due or None
                selected.append((row, changed))
            if not selected:
                raise ValueError('Bitte mindestens einen noch ungespeicherten Vorschlag auswählen.')
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.work('save', lambda: self.operation('save', {'items': selected, 'kind': self.kind}))

    def finished_work(self, action, result, error):
        self.table.setEnabled(True)
        self.generate.setEnabled(bool(self.documents and not self.saved))
        if error:
            self.status.setText(error)
        elif action == 'draft':
            self.items, self.saved = result['items'], set()
            for item in self.items:
                item['idempotency_key'] = uuid.uuid4().hex
            self.table.setRowCount(len(self.items))
            for row, item in enumerate(self.items):
                source = item['source']
                texts = ['', item['title' if self.kind == 'tasks' else 'question'], item.get('due_at') or '' if self.kind == 'tasks' else item['answer'],
                    source['title'] + ' · Zeile ' + str(source['line']) + '\n' + source['quote']]
                for column, text in enumerate(texts):
                    cell = QTableWidgetItem(text)
                    if column in (0, 3) or (column == 2 and self.kind == 'cards'):
                        cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if column == 0:
                        cell.setFlags(cell.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        cell.setCheckState(Qt.CheckState.Checked)
                    self.table.setItem(row, column, cell)
            self.table.resizeRowsToContents()
            self.status.setText('Vorschläge mit überprüften Zitaten. Bitte Inhalt und Termine prüfen.')
        else:
            self.saved.update(result['saved'])
            for row in self.saved:
                self.table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
                for col in range(4):
                    self.table.item(row, col).setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.status.setText(f'{len(self.saved)} Einträge gespeichert.' + ('\n' + result['error'] if result.get('error') else ''))
            self.generate.setEnabled(False)
        self.save.setEnabled(bool(self.items and len(self.saved) < len(self.items)))
