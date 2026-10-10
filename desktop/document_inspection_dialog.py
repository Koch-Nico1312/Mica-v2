"""Local statistics and literal search for selected documents."""
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit, QVBoxLayout
from desktop.core.document_inspection import search_text, statistics_text


class DocumentInspectionDialog(QDialog):
    def __init__(self, parent=None, documents=None):
        super().__init__(parent)
        self.documents = [dict(doc) for doc in (documents or [])]
        self.setWindowTitle('Dokumentinfos und Suche')
        self.resize(700, 520)
        layout = QVBoxLayout(self)
        note = QLabel('Nur ausgewählte, bereits eingelesene Texte. Keine Backend- oder Cloud-Anfrage.')
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setMaxLength(120)
        self.query.setPlaceholderText('Text in allen ausgewählten Dokumenten suchen')
        self.query.returnPressed.connect(self.search)
        search = QPushButton('Suchen')
        search.clicked.connect(self.search)
        row.addWidget(self.query, 1)
        row.addWidget(search)
        layout.addLayout(row)
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        layout.addWidget(self.report, 1)
        row = QHBoxLayout()
        self.stats_button = QPushButton('Wörter und Zeichen zählen')
        self.stats_button.clicked.connect(self.statistics)
        close = QPushButton('Schließen')
        close.clicked.connect(self.accept)
        row.addWidget(self.stats_button)
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)
        self.statistics()

    def statistics(self):
        try:
            self.report.setPlainText(statistics_text(self.documents))
        except ValueError as error:
            self.report.setPlainText(str(error))

    def search(self):
        try:
            self.report.setPlainText(search_text(self.documents, self.query.text()))
        except ValueError as error:
            self.report.setPlainText(str(error))
