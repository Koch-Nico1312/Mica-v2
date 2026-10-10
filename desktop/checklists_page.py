"""Shopping/packing/checklists explicitly saved on this Windows device."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                            QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
from desktop.core.checklists import CHECKLIST_TEMPLATES, ChecklistStore
from desktop.core.markdown_export import checklist_markdown, save_markdown


class ChecklistsPage(QWidget):
    def __init__(self, parent=None, store=None, can_save=lambda: True):
        super().__init__(parent)
        self.store, self.can_save = store or ChecklistStore(), can_save
        self.snapshot = {'revision': 0, 'lists': []}
        self._rendering = False
        layout = QVBoxLayout(self)
        note = QLabel('Einkaufs-, Pack- und Prüflisten lokal führen. Ein Haken erledigt nur diesen Listeneintrag; keine andere Aktion wird gestartet.')
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        self.choice = QComboBox()
        self.choice.currentIndexChanged.connect(self.render_items)
        row.addWidget(self.choice, 1)
        self.name = QLineEdit()
        self.name.setMaxLength(80)
        self.name.setPlaceholderText('Name einer neuen Liste')
        row.addWidget(self.name)
        self.create_button = QPushButton('Liste anlegen')
        self.create_button.clicked.connect(self.create)
        row.addWidget(self.create_button)
        refresh = QPushButton('Aktualisieren')
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.template_choice = QComboBox()
        self.template_choice.addItems(CHECKLIST_TEMPLATES)
        row.addWidget(self.template_choice)
        self.template_preview = QLabel()
        self.template_preview.setWordWrap(True)
        row.addWidget(self.template_preview, 1)
        self.template_choice.currentTextChanged.connect(self.preview_template)
        self.template_button = QPushButton('Vorlage als neue Liste')
        self.template_button.clicked.connect(self.from_template)
        row.addWidget(self.template_button)
        layout.addLayout(row)
        self.preview_template()
        row = QHBoxLayout()
        self.entry = QLineEdit()
        self.entry.setMaxLength(240)
        self.entry.setPlaceholderText('Eintrag, z. B. 2 Liter Milch')
        self.entry.returnPressed.connect(self.add)
        row.addWidget(self.entry, 1)
        self.add_button = QPushButton('Hinzufügen')
        self.add_button.clicked.connect(self.add)
        row.addWidget(self.add_button)
        layout.addLayout(row)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(['Erledigt', 'Eintrag'])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 75)
        self.table.verticalHeader().hide()
        self.table.itemChanged.connect(self.toggle)
        layout.addWidget(self.table, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        for title, action in [('Liste umbenennen', self.rename), ('Eintrag entfernen', self.remove_item),
                              ('Liste entfernen', self.remove_list), ('Als neue Liste kopieren', self.duplicate),
                              ('Alle wieder öffnen', self.reset)]:
            button = QPushButton(title)
            button.clicked.connect(action)
            row.addWidget(button)
        layout.addLayout(row)
        self.export_button = QPushButton('Ausgewählte Liste als Markdown exportieren')
        self.export_button.clicked.connect(self.export)
        layout.addWidget(self.export_button)
        self.refresh()

    def selected_list(self):
        return next((entry for entry in self.snapshot['lists'] if entry['id'] == self.choice.currentData()), None)

    def refresh(self, selected=None):
        selected = selected or self.choice.currentData()
        try:
            self.snapshot = self.store.read()
        except (ValueError, OSError) as error:
            self.status.setText('Listen konnten nicht geladen werden: ' + str(error))
            return
        self.choice.blockSignals(True)
        try:
            self.choice.clear()
            for record in self.snapshot['lists']:
                self.choice.addItem(record['name'], record['id'])
            index = self.choice.findData(selected)
            if index >= 0:
                self.choice.setCurrentIndex(index)
        finally:
            self.choice.blockSignals(False)
        self.render_items()

    def render_items(self, *_):
        record = self.selected_list()
        items = record['items'] if record else []
        self._rendering = True
        try:
            self.table.setRowCount(0)
            self.table.setRowCount(len(items))
            for row, item in enumerate(items):
                checked = QTableWidgetItem()
                checked.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
                checked.setData(Qt.ItemDataRole.UserRole, item['id'])
                checked.setCheckState(Qt.CheckState.Checked if item['done'] else Qt.CheckState.Unchecked)
                text = QTableWidgetItem(item['text'])
                text.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(row, 0, checked)
                self.table.setItem(row, 1, text)
        finally:
            self._rendering = False
        self.add_button.setEnabled(record is not None)
        self.status.setText(f"{sum(not item['done'] for item in items)} offen · {sum(item['done'] for item in items)} erledigt" if record else 'Lege eine Liste an, z. B. Einkauf oder Urlaub.')

    def change(self, operation, **kwargs):
        if not self.can_save():
            self.render_items()
            self.status.setText('Checklisten benötigen den Modus mit Speicherung.')
            return False
        try:
            _, identifier = self.store.change(operation, revision=self.snapshot['revision'],
                                             list_id=self.choice.currentData(), **kwargs)
        except (ValueError, OSError) as error:
            self.refresh()
            self.status.setText('Änderung nicht gespeichert: ' + str(error))
            return False
        self.refresh(identifier)
        return True

    def create(self):
        if self.change('create', text=self.name.text()):
            self.name.clear()

    def preview_template(self, *_):
        self.template_preview.setText(' · '.join(CHECKLIST_TEMPLATES[self.template_choice.currentText()]))

    def from_template(self):
        template = self.template_choice.currentText()
        if self.change('from_template', template=template, text=self.name.text().strip() or template):
            self.name.clear()

    def duplicate(self):
        record = self.selected_list()
        if record:
            name, accepted = QInputDialog.getText(self, 'Liste kopieren',
                                                'Name der neuen Liste (alle Einträge offen):',
                                                text=record['name'][:74] + ' Kopie')
            if accepted:
                self.change('duplicate', text=name)

    def reset(self):
        record = self.selected_list()
        if record and any(item['done'] for item in record['items']):
            if QMessageBox.question(self, 'Alle wieder öffnen',
                                    f"Alle erledigten Einträge in {record['name']} wieder öffnen?") == QMessageBox.StandardButton.Yes:
                self.change('reset')

    def add(self):
        if self.change('add', text=self.entry.text()):
            self.entry.clear()

    def toggle(self, item):
        if not self._rendering and item.column() == 0:
            self.change('toggle', item_id=item.data(Qt.ItemDataRole.UserRole), done=item.checkState() == Qt.CheckState.Checked)

    def rename(self):
        record = self.selected_list()
        if record:
            name, accepted = QInputDialog.getText(self, 'Liste umbenennen', 'Neuer Name:', text=record['name'])
            if accepted:
                self.change('rename', text=name)

    def remove_item(self):
        record, row = self.selected_list(), self.table.currentRow()
        if record and 0 <= row < len(record['items']):
            item = record['items'][row]
            if QMessageBox.question(self, 'Eintrag entfernen', item['text']) == QMessageBox.StandardButton.Yes:
                self.change('remove_item', item_id=item['id'])

    def remove_list(self):
        record = self.selected_list()
        if record and QMessageBox.question(self, 'Liste entfernen',
                                          f"Liste {record['name']} mit allen Einträgen entfernen?") == QMessageBox.StandardButton.Yes:
            self.change('remove_list')

    def export(self):
        record = self.selected_list()
        revision = self.snapshot['revision']
        if record is None:
            self.status.setText('Bitte zuerst eine Liste auswählen.')
            return
        if not self.can_save():
            self.status.setText('Der Dateiexport benötigt den Modus mit Speicherung.')
            return
        try:
            path, _ = QFileDialog.getSaveFileName(self, 'Liste exportieren', 'MICA-Liste.md', 'Markdown (*.md)')
            if not path:
                return
            if not self.can_save():
                self.status.setText('Der Dateiexport benötigt den Modus mit Speicherung.')
                return
            fresh = self.store.read()['revision'] == revision
            save_markdown(path, checklist_markdown(record, fresh=fresh))
        except (ValueError, OSError) as error:
            self.status.setText('Liste nicht exportiert: ' + str(error))
            return
        self.status.setText('Sichtbare Liste als Markdown exportiert.' if fresh else
                            'Ältere Ansicht exportiert; der Hinweis steht auch in der Datei.')
