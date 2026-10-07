"""Preview a portable project export and let the user select every included task."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QListWidget, QListWidgetItem, QCheckBox, QPlainTextEdit, QPushButton, QFileDialog, QMessageBox
from desktop.core.project_export import project_markdown, write_export
from desktop.core.offline_tasks import OfflineTasks
from desktop.core.flashcards import FlashcardStore


class ProjectExportDialog(QDialog):
    def __init__(self, parent, name, checkpoint):
        super().__init__(parent)
        self.name, self.checkpoint = name, checkpoint
        self.setWindowTitle('Projekt als Markdown exportieren')
        self.resize(720, 650)
        layout = QVBoxLayout(self)
        note = QLabel('Exportiert den ausgewählten gespeicherten Projektstand mit Dokumentinhalten und Quellen. Wähle zusätzlich die Aufgaben und optional die zu diesen Dokumenten gehörenden Lernkarten. Es werden nur lokale Daten gelesen.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tasks = OfflineTasks().view()
        self.fetched_at = OfflineTasks().read()['fetched_at']
        self.list = QListWidget()
        self.list.setMaximumHeight(150)
        for task in self.tasks:
            item = QListWidgetItem(task['title'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if checkpoint.get('task_id') and (task['id'] == checkpoint['task_id'] or task.get('parent_id') == checkpoint['task_id']) else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        self.list.itemChanged.connect(self.refresh)
        layout.addWidget(self.list)
        self.cards = QCheckBox('Quellenbezogene Lernkarten mit exportieren')
        self.cards.stateChanged.connect(self.refresh)
        layout.addWidget(self.cards)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.save = QPushButton('Diese Vorschau als .md speichern')
        self.save.clicked.connect(self.export)
        layout.addWidget(self.save)
        close = QPushButton('Schließen')
        close.clicked.connect(self.reject)
        layout.addWidget(close)
        self.refresh()

    def refresh(self):
        try:
            tasks = [task for row, task in enumerate(self.tasks) if self.list.item(row).checkState() == Qt.CheckState.Checked]
            self.markdown = project_markdown(self.name, self.checkpoint, tasks,
                cards=FlashcardStore().all() if self.cards.isChecked() else (), fetched_at=self.fetched_at)
            self.preview.setPlainText(self.markdown)
            self.save.setEnabled(True)
            self.status.setText('Vorschau des vollständigen Exports. Erst Speichern schreibt eine Datei.')
        except (ValueError, OSError) as error:
            self.save.setEnabled(False)
            self.status.setText(str(error))

    def export(self):
        from pathlib import Path
        path, _ = QFileDialog.getSaveFileName(self, 'Markdown speichern', self.name + '.md', 'Markdown (*.md)')
        if not path:
            return
        if Path(path).exists() and QMessageBox.question(self, 'Datei ersetzen', 'Diese vorhandene Markdown-Datei ersetzen?') != QMessageBox.StandardButton.Yes:
            return
        try:
            write_export(path, self.markdown)
            self.status.setText('Markdown-Datei gespeichert: ' + str(Path(path).resolve()))
        except (ValueError, OSError) as error:
            self.status.setText('Export nicht gespeichert: ' + str(error))
