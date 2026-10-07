"""Local, explicitly saved source cards and durable spaced repetition."""
from datetime import datetime, UTC, timedelta
import uuid
import re
from desktop.core.local_state import DATA_DIR, FileLease, read_json, write_json


class FlashcardStore:
    def __init__(self, path=None):
        self.path = path or DATA_DIR / 'flashcards.json'

    @staticmethod
    def validate(card):
        if not isinstance(card, dict) or not isinstance(card.get('question'), str) or not 1 <= len(card['question'].strip()) <= 500:
            raise ValueError('Ungültige Lernkarte.')
        source, answer = card.get('source'), card.get('answer')
        if not isinstance(source, dict) or not isinstance(answer, str) or not 5 <= len(answer) <= 1200 or source.get('quote') != answer:
            raise ValueError('Ungültiger Lernkartenbeleg.')
        if (not isinstance(source.get('document_id'), str) or not re.fullmatch(r'[a-f0-9]{32}', source['document_id'])
            or not isinstance(source.get('title'), str) or not 1 <= len(source['title']) <= 160
            or type(source.get('start')) is not int or source['start'] < 0
            or type(source.get('end')) is not int or source['end'] != source['start'] + len(answer)
            or type(source.get('line')) is not int or source['line'] < 1):
            raise ValueError('Ungültige Lernkartenquelle.')
        if not isinstance(card.get('id'), str) or not re.fullmatch(r'[a-f0-9]{32}', card['id']):
            raise ValueError('Ungültige Lernkartenkennung.')
        if type(card.get('interval')) is not int or not 0 <= card['interval'] <= 365 or type(card.get('reviews')) is not int or card['reviews'] < 0:
            raise ValueError('Ungültige Wiederholungsdaten.')
        try:
            if not isinstance(card['due_at'], str) or len(card['due_at']) > 64 or datetime.fromisoformat(card['due_at']).tzinfo is None:
                raise ValueError('Zeitpunkt ohne Zeitzone.')
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError('Ungültiger Wiederholungstermin.') from error
        return card

    def all(self):
        try:
            data = read_json(self.path, limit=8 * 1024 * 1024)
        except FileNotFoundError:
            return []
        if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('cards'), list) or len(data['cards']) > 1000:
            raise ValueError('Ungültige Lernkartendatei.')
        for card in data['cards']:
            self.validate(card)
        if len({card['id'] for card in data['cards']}) != len(data['cards']):
            raise ValueError('Doppelte Lernkartenkennung.')
        return data['cards']

    def add(self, items, *, now=None):
        now = now or datetime.now(UTC)
        with FileLease(str(self.path) + '.lock', label='Die Lernkarten'):
            cards = self.all()
            if len(cards) + len(items) > 1000:
                raise ValueError('Höchstens 1000 Lernkarten speichern.')
            for item in items:
                candidate = self.validate({key: item[key] for key in ('question', 'answer', 'source')} | {
                    'id': uuid.uuid4().hex, 'due_at': now.isoformat(), 'interval': 0, 'reviews': 0})
                identity = (item['question'], item['source']['document_id'], item['source']['start'])
                if any((c['question'], c['source']['document_id'], c['source']['start']) == identity for c in cards):
                    continue
                cards.append(candidate)
            write_json(self.path, {'version': 1, 'cards': cards})

    def due(self, *, now=None):
        now = now or datetime.now(UTC)
        return sorted([card for card in self.all() if datetime.fromisoformat(card['due_at']) <= now], key=lambda card: card['due_at'])

    def rate(self, identifier, rating, *, now=None):
        if rating not in {'again', 'hard', 'good', 'easy'}:
            raise ValueError('Ungültige Bewertung.')
        now = now or datetime.now(UTC)
        with FileLease(str(self.path) + '.lock', label='Die Lernkarten'):
            cards = self.all()
            card = next((card for card in cards if card['id'] == identifier), None)
            if not card:
                raise ValueError('Lernkarte nicht mehr vorhanden.')
            interval = {'again': 0, 'hard': max(1, card['interval']), 'good': max(1, card['interval'] * 2),
                'easy': max(4, card['interval'] * 3)}[rating]
            card['interval'] = min(365, interval)
            card['due_at'] = (now + (timedelta(minutes=10) if rating == 'again' else timedelta(days=card['interval']))).isoformat()
            card['reviews'] += 1
            write_json(self.path, {'version': 1, 'cards': cards})
            return card

    def delete(self, identifier):
        with FileLease(str(self.path) + '.lock', label='Die Lernkarten'):
            write_json(self.path, {'version': 1, 'cards': [card for card in self.all() if card['id'] != identifier]})
