"""Explicit checkpoint save/restore with a visible preview and async Core calls."""
import threading
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPlainTextEdit, QPushButton, QMessageBox, QComboBox, QCheckBox
from desktop.core.workspace import ProjectWorkspaceStore
from desktop.ui_theme import C


class WorkspaceDialog(QDialog):
    _done = pyqtSignal(str, object, str)

    def __init__(self, parent, operation, documents, *, store=None, prefer_load=False, project=None):
        super().__init__(parent)
        self.operation, self.documents = operation, documents
        self.store = store or ProjectWorkspaceStore()
        self.saved = None
        self.busy = False
        self.setWindowTitle('Arbeitsstand speichern und weiterarbeiten')
        self.resize(520, 460)
        self.setStyleSheet(f'QDialog {{background:{C.PANEL};}} QLabel {{color:{C.TEXT};}} QPlainTextEdit,QPushButton {{background:{C.PANEL2};color:{C.TEXT};padding:8px;}}')
        layout = QVBoxLayout(self)
        note = QLabel('Speichert die ausgewählten Dokumentinhalte, die offene Aufgabe und deinen nächsten Schritt lokal. Laden stellt den Gesprächsbezug wieder her und führt keine gespeicherten Aktionen aus.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.name = QComboBox()
        self.name.setEditable(True)
        self.name.setMaxCount(21)
        self.name.lineEdit().setMaxLength(50)
        try:
            self.name.addItems(self.store.names())
        except (OSError, ValueError):
            pass
        self.name.setCurrentText(project or 'standard')
        layout.addWidget(QLabel('Projekt auswählen oder neuen Namen eingeben:'))
        layout.addWidget(self.name)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)
        self.last_step = QPlainTextEdit()
        self.last_step.setPlaceholderText('Hier war ich: letzter Arbeitsschritt')
        self.last_step.setMaximumHeight(70)
        layout.addWidget(self.last_step)
        self.remember_progress = QCheckBox('Weitere Gesprächsschritte für dieses Projekt merken')
        layout.addWidget(self.remember_progress)
        self.step = QPlainTextEdit()
        self.step.setPlaceholderText('Nächster Schritt, zum Beispiel: Docker-Konfiguration vergleichen')
        layout.addWidget(self.step)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.save_button = QPushButton('Aktuellen Arbeitsstand speichern')
        self.load_button = QPushButton('Gespeicherten Arbeitsstand laden')
        self.forget_button = QPushButton('Gespeicherten Arbeitsstand löschen')
        self.sync_button = QPushButton('Lokalen Projektstand mit Gespräch im Backend verbinden')
        self.export_button = QPushButton('Gespeichertes Projekt als Markdown exportieren')
        self.buttons = [self.save_button, self.load_button, self.sync_button, self.export_button, self.forget_button]
        for button in self.buttons:
            layout.addWidget(button)
        self.save_button.clicked.connect(lambda: self.run('save'))
        self.load_button.clicked.connect(lambda: self.run('load'))
        self.sync_button.clicked.connect(lambda: self.run('sync'))
        self.export_button.clicked.connect(self.export_project)
        self.forget_button.clicked.connect(self.forget)
        close = QPushButton('Schließen')
        close.clicked.connect(self.reject)
        layout.addWidget(close)
        self._done.connect(self.done_operation)
        self.name.currentTextChanged.connect(lambda: self.refresh(True))
        self.refresh(prefer_load)

    def refresh(self, prefer_load=False):
        try:
            self.saved = self.store.load(self.name.currentText())
            changed = self.store.warnings(self.saved)
            titles = ', '.join(doc['title'] for doc in self.saved['documents']) or 'keine Dateien'
            task_label = (self.saved.get('task_title') or 'Gespeicherte Aufgabe') if self.saved['task_id'] else 'keine'
            self.preview.setText('Gespeichert: ' + titles + '\nOffene Aufgabe: ' + task_label +
                '\nHier warst du: ' + (self.saved.get('last_step') or 'Noch kein Arbeitsschritt festgehalten.') +
                '\nNächster Schritt: ' + (self.saved['next_step'] or 'Noch nicht festgelegt.') +
                ('\nGeändert oder fehlt: ' + ', '.join(changed) + '. Beim Laden wird die gespeicherte Fassung verwendet; unter Dateien kannst du neu einlesen.' if changed else ''))
            if prefer_load:
                self.step.setPlainText(self.saved['next_step'])
            self.last_step.setPlainText(self.saved.get('last_step', ''))
            self.remember_progress.setChecked(self.saved.get('remember_progress', False))
            self.status.clear()
        except (OSError, ValueError, TypeError) as error:
            self.saved = None
            self.preview.setText('Kein lesbarer Arbeitsstand gespeichert.')
            if prefer_load:
                self.step.clear()
            self.last_step.clear()
            self.remember_progress.setChecked(False)
            if not isinstance(error, FileNotFoundError):
                self.status.setText(str(error))
        self.load_button.setEnabled(self.saved is not None)
        self.forget_button.setEnabled(self.saved is not None)
        self.sync_button.setEnabled(self.saved is not None)
        self.export_button.setEnabled(self.saved is not None)

    def export_project(self):
        if self.saved:
            try:
                from desktop.project_export_dialog import ProjectExportDialog
                ProjectExportDialog(self, self.name.currentText(), self.saved).exec()
            except (OSError, ValueError) as error:
                self.status.setText('Export nicht verfügbar: ' + str(error))

    def run(self, action):
        if self.busy:
            return
        if action == 'save' and max(len(self.step.toPlainText()), len(self.last_step.toPlainText())) > 2000:
            self.status.setText('Der nächste Schritt darf höchstens 2.000 Zeichen enthalten.')
            return
        if action == 'save' and self.saved and QMessageBox.question(self, 'Arbeitsstand ersetzen', 'Den gespeicherten Arbeitsstand durch die aktuelle Auswahl ersetzen?') != QMessageBox.StandardButton.Yes:
            return
        for button in self.buttons:
            button.setEnabled(False)
        self.name.setEnabled(False)
        self.busy = True
        self.status.setText('Arbeitsstand wird verarbeitet …')
        payload = {'documents': self.documents, 'next_step': self.step.toPlainText(), 'project': self.name.currentText(),
            'last_step': self.last_step.toPlainText(), 'remember_progress': self.remember_progress.isChecked()} if action == 'save' else {**self.saved, 'project': self.name.currentText()}
        def worker():
            try:
                result, error = self.operation(action, payload, self.store), ''
            except Exception as exc:
                result, error = None, str(exc)
            self._done.emit(action, result, error)
        threading.Thread(target=worker, name='mica-workspace', daemon=True).start()

    def done_operation(self, action, result, error):
        self.busy = False
        for button in self.buttons:
            button.setEnabled(True)
        self.name.setEnabled(True)
        if error:
            self.refresh()
            self.status.setText('Arbeitsstand nicht übernommen: ' + error)
            return
        if action in {'load', 'sync'}:
            parent = self.parent()
            parent._open_attachments()
            parent._attachment_overlay.replace_documents(result['documents'])
            parent._input.setText(result['next_step'])
            if hasattr(parent, '_log'):
                parent._log.append_log('SYS: Projekt ' + self.name.currentText() + ' fortgesetzt. Hier warst du: ' +
                    (result.get('last_step') or 'Noch kein letzter Schritt gespeichert.') + '\nNächster Schritt: ' +
                    (result['next_step'] or 'Noch nicht festgelegt.'))
            if action == 'sync':
                self.status.setText('Geprüfter lokaler Projektstand mit dem Backend-Gespräch verbunden und in der Oberfläche geladen. Keine Aufgabe wurde ausgeführt oder angelegt.')
            elif result.get('offline'):
                self.status.setText('Offline geladen. Dokumente und nächste Schritte sind lokal nutzbar; das Backend-Gespräch ist noch nicht verbunden. Zum Abgleich diesen Projektstand prüfen und die Verbindung ausdrücklich bestätigen.')
            else:
                self.accept()
        else:
            name = self.store.name(self.name.currentText())
            if self.name.findText(name) == -1:
                self.name.blockSignals(True)
                self.name.addItem(name)
                self.name.setCurrentText(name)
                self.name.blockSignals(False)
            self.refresh()
            self.status.setText('Arbeitsstand lokal gespeichert. Backend-Gespräch noch nicht verbunden; beim Wiederverbinden diesen Stand prüfen und ausdrücklich verbinden.' if result.get('offline') else 'Arbeitsstand gespeichert.')

    def forget(self):
        if QMessageBox.question(self, 'Arbeitsstand löschen', 'Den gespeicherten Arbeitsstand löschen?') != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.forget(self.name.currentText())
            self.refresh()
            self.status.setText('Gespeicherter Arbeitsstand gelöscht.')
        except (OSError, ValueError) as error:
            self.status.setText(str(error))

    def reject(self):
        if self.busy:
            self.status.setText('Arbeitsstand wird noch verarbeitet. Danach kannst du das Fenster schließen.')
            return
        super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)
