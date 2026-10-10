"""Reveal, rate, and forget due cards without exposing answers early."""
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QPlainTextEdit
from desktop.core.flashcards import FlashcardStore


class FlashcardsDialog(QDialog):
    def __init__(self, parent=None, *, store=None, card_ids=None):
        super().__init__(parent)
        self.store = store or FlashcardStore()
        self.current = None
        self.card_ids = set(card_ids) if card_ids is not None else None
        self.reviewed_ids = set()
        self.setWindowTitle('Lernkarten wiederholen')
        self.resize(620, 500)
        layout = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.question = QLabel()
        self.question.setWordWrap(True)
        layout.addWidget(self.question)
        self.answer = QPlainTextEdit()
        self.answer.setReadOnly(True)
        layout.addWidget(self.answer)
        self.reveal = QPushButton('Antwort und Quelle anzeigen')
        self.reveal.clicked.connect(self.show_answer)
        layout.addWidget(self.reveal)
        self.ratings = []
        for label, rating in [('Noch einmal · 10 Minuten', 'again'), ('Schwer', 'hard'), ('Gut', 'good'), ('Leicht', 'easy')]:
            button = QPushButton(label)
            button.clicked.connect(lambda _, value=rating: self.rate(value))
            self.ratings.append(button)
            layout.addWidget(button)
        delete = QPushButton('Diese Karte vergessen')
        delete.clicked.connect(self.forget)
        layout.addWidget(delete)
        self.next_card()

    def next_card(self):
        try:
            due = self.store.due() if self.card_ids is None else [card for card in self.store.all()
                if card['id'] in self.card_ids and card['id'] not in self.reviewed_ids]
            self.current = due[0] if due else None
            self.question.setText(self.current['question'] if self.current else 'Für jetzt sind alle Karten wiederholt.')
            self.answer.clear()
            self.status.setText(f'{len(due)} Karten fällig. Schweres kommt früher wieder.')
            self.reveal.setEnabled(bool(self.current))
            for button in self.ratings:
                button.setEnabled(False)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.current = None
            self.reveal.setEnabled(False)
            for button in self.ratings:
                button.setEnabled(False)
            self.status.setText('Lernkarten nicht geladen: ' + str(error))

    def show_answer(self):
        if self.current:
            source = self.current['source']
            self.answer.setPlainText(self.current['answer'] + '\n\nQuelle: ' + source['title'] + ' · Zeile ' + str(source['line']))
            for button in self.ratings:
                button.setEnabled(True)

    def rate(self, value):
        if self.current:
            try:
                self.store.rate(self.current['id'], value)
                self.reviewed_ids.add(self.current['id'])
                self.next_card()
            except (OSError, ValueError) as error:
                self.status.setText(str(error))

    def forget(self):
        if self.current:
            from PyQt6.QtWidgets import QMessageBox
            if QMessageBox.question(self, 'Karte vergessen', 'Diese Lernkarte löschen?') != QMessageBox.StandardButton.Yes:
                return
            try:
                self.store.delete(self.current['id'])
                self.next_card()
            except (OSError, ValueError) as error:
                self.status.setText(str(error))
