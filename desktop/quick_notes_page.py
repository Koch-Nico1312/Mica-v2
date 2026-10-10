"""Local scratchpad with explicit save and protected drafts."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                            QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from desktop.core.quick_notes import MAX_BODY, QuickNotesStore, search_notes


class QuickNotesPage(QWidget):
    def __init__(self, parent=None, store=None, can_save=lambda: True):
        super().__init__(parent)
        self.store = store or QuickNotesStore()
        self.can_save = can_save
        self.snapshot = {'revision': 0, 'notes': []}
        self.note_id = None
        self.saved_fields = ('', '')
        layout = QVBoxLayout(self)
        note = QLabel('Kurze Ideen und Arbeitsnotizen lokal sammeln. Erst Speichern schreibt die Notiz auf dieses Gerät.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.search = QLineEdit()
        self.search.setPlaceholderText('In Titel und Notiztext suchen')
        self.search.setMaxLength(200)
        self.search.textChanged.connect(self.render_list)
        layout.addWidget(self.search)
        self.notes = QListWidget()
        self.notes.currentItemChanged.connect(self.select_note)
        layout.addWidget(self.notes, 1)
        self.title = QLineEdit()
        self.title.setMaxLength(80)
        self.title.setPlaceholderText('Titel')
        layout.addWidget(self.title)
        self.body = QPlainTextEdit()
        self.body.setPlaceholderText('Notiztext (bis 20.000 Zeichen)')
        layout.addWidget(self.body, 2)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.title.textChanged.connect(self.show_draft_status)
        self.body.textChanged.connect(self.show_draft_status)
        row = QHBoxLayout()
        self.new_button = QPushButton('Neue Notiz')
        self.new_button.clicked.connect(self.new_note)
        self.save_button = QPushButton('Speichern')
        self.save_button.clicked.connect(self.save)
        self.remove_button = QPushButton('Notiz entfernen')
        self.remove_button.clicked.connect(self.remove)
        self.refresh_button = QPushButton('Neu laden')
        self.refresh_button.clicked.connect(self.reload)
        for button in (self.new_button, self.save_button, self.remove_button, self.refresh_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.reload()

    def dirty(self):
        return (self.title.text(), self.body.toPlainText()) != self.saved_fields

    def allow_discard(self):
        return not self.dirty() or QMessageBox.question(
            self, 'Ungespeicherter Entwurf', 'Ungespeicherte Änderungen verwerfen?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def show_draft_status(self, *_):
        count = len(self.body.toPlainText())
        suffix = ' · Noch nicht gespeichert' if self.dirty() else ' · Unverändert'
        self.status.setText(f'{count} / {MAX_BODY} Zeichen' + suffix)
        self.save_button.setEnabled(count <= MAX_BODY)

    def render_list(self, *_):
        self.notes.blockSignals(True)
        try:
            self.notes.clear()
            for note in search_notes(self.snapshot['notes'], self.search.text()):
                item = QListWidgetItem(note['title'])
                item.setData(Qt.ItemDataRole.UserRole, note['id'])
                self.notes.addItem(item)
                if note['id'] == self.note_id:
                    self.notes.setCurrentItem(item)
        finally:
            self.notes.blockSignals(False)

    def load_editor(self, note):
        self.note_id = note['id'] if note else None
        self.saved_fields = (note['title'], note['body']) if note else ('', '')
        self.title.setText(self.saved_fields[0])
        self.body.setPlainText(self.saved_fields[1])
        self.show_draft_status()

    def select_note(self, current, previous):
        if current is None:
            return
        identifier = current.data(Qt.ItemDataRole.UserRole)
        if identifier == self.note_id:
            return
        if not self.allow_discard():
            self.notes.blockSignals(True)
            self.notes.setCurrentItem(previous)
            self.notes.blockSignals(False)
            return
        note = next((note for note in self.snapshot['notes'] if note['id'] == identifier), None)
        self.load_editor(note)

    def new_note(self):
        if self.allow_discard():
            self.load_editor(None)
            self.render_list()
            self.title.setFocus()

    def reload(self):
        if not self.allow_discard():
            return
        try:
            data = self.store.read()
        except (ValueError, OSError) as error:
            self.status.setText('Notizen konnten nicht geladen werden: ' + str(error))
            return
        self.snapshot = data
        note = next((note for note in data['notes'] if note['id'] == self.note_id), None)
        self.load_editor(note)
        self.render_list()

    def change(self, operation, **kwargs):
        if not self.can_save():
            self.status.setText('Notizänderungen benötigen den Modus mit Speicherung. Der Entwurf bleibt erhalten.')
            return False
        try:
            data, identifier = self.store.change(operation, revision=self.snapshot['revision'],
                                                 note_id=self.note_id, **kwargs)
        except (ValueError, OSError) as error:
            self.status.setText('Nicht gespeichert; Entwurf bleibt erhalten: ' + str(error))
            return False
        self.snapshot = data
        note = next((note for note in data['notes'] if note['id'] == identifier), None)
        self.load_editor(note)
        self.render_list()
        self.status.setText('Notiz gespeichert.' if operation == 'save' else 'Notiz entfernt.')
        return True

    def save(self):
        self.change('save', title=self.title.text(), body=self.body.toPlainText())

    def remove(self):
        if self.note_id is not None and QMessageBox.question(
                self, 'Notiz entfernen', 'Diese gespeicherte Notiz und den aktuellen Entwurf entfernen?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.change('remove')
