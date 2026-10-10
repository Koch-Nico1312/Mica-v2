"""Explicit local notes with bounded storage and optimistic concurrency."""
from copy import deepcopy
from datetime import datetime, timezone
import re
import uuid

from desktop.core.local_state import DATA_DIR, FileLease, read_json, write_json

MAX_NOTES = 100
MAX_BODY = 20_000
MAX_STORAGE = 16 * 1024 * 1024


class QuickNotesStore:
    def __init__(self, path=None):
        self.path = path or DATA_DIR / 'quick-notes.json'

    def read(self):
        try:
            data = read_json(self.path, limit=MAX_STORAGE)
        except FileNotFoundError:
            return {'version': 1, 'revision': 0, 'notes': []}
        if (not isinstance(data, dict) or type(data.get('version')) is not int or data.get('version') != 1
                or type(data.get('revision')) is not int or data['revision'] < 0
                or not isinstance(data.get('notes'), list) or len(data['notes']) > MAX_NOTES):
            raise ValueError('Der gespeicherte Notizstand ist ungültig.')
        identifiers = set()
        for note in data['notes']:
            if (not isinstance(note, dict) or not isinstance(note.get('id'), str)
                    or not re.fullmatch(r'[a-f0-9]{32}', note['id']) or note['id'] in identifiers
                    or not isinstance(note.get('title'), str) or not 1 <= len(note['title'].strip()) <= 80
                    or '\n' in note['title'] or '\r' in note['title']
                    or not isinstance(note.get('body'), str) or not 1 <= len(note['body'].strip()) <= MAX_BODY
                    or len(note['body']) > MAX_BODY
                    or type(note.get('pinned', False)) is not bool
                    or type(note.get('trashed', False)) is not bool
                    or not isinstance(note.get('updated_at'), str)):
                raise ValueError('Eine gespeicherte Notiz ist ungültig.')
            try:
                timestamp = datetime.fromisoformat(note['updated_at'])
                if timestamp.tzinfo is None:
                    raise ValueError('Zeitzone fehlt.')
            except ValueError as error:
                raise ValueError('Der Notizzeitpunkt ist ungültig.') from error
            identifiers.add(note['id'])
        return data

    def change(self, operation, *, revision, note_id=None, title='', body='', pinned=None):
        if operation not in {'save', 'remove', 'pin', 'restore', 'purge'}:
            raise ValueError('Unbekannte Notizaktion.')
        if operation == 'pin' and type(pinned) is not bool:
            raise ValueError('Ungültiger Anheften-Zustand.')
        if operation == 'save':
            if (not isinstance(title, str) or not 1 <= len(title.strip()) <= 80
                    or '\n' in title or '\r' in title or not isinstance(body, str)
                    or not body.strip() or len(body) > MAX_BODY):
                raise ValueError('Bitte einen Titel mit 1–80 Zeichen und einen Text mit 1–20.000 Zeichen eingeben.')
            title = title.strip()
        with FileLease(str(self.path) + '.lock', label='Die Notizen'):
            data = deepcopy(self.read())
            if type(revision) is not int or revision != data['revision']:
                raise ValueError('Der Notizstand wurde inzwischen geändert. Entwurf behalten und aktuellen Stand neu laden.')
            note = next((record for record in data['notes'] if record['id'] == note_id), None)
            if note_id is not None and note is None:
                raise ValueError('Die ausgewählte Notiz ist nicht mehr vorhanden.')
            trashed = note is not None and note.get('trashed', False)
            if operation in {'restore', 'purge'} and not trashed:
                raise ValueError('Bitte eine Notiz aus dem Papierkorb auswählen.')
            if operation in {'save', 'remove', 'pin'} and trashed:
                raise ValueError('Bitte die Notiz zuerst aus dem Papierkorb wiederherstellen.')
            if operation == 'remove':
                if note is None:
                    raise ValueError('Bitte eine gespeicherte Notiz auswählen.')
                note['trashed'] = True
            elif operation == 'purge':
                data['notes'].remove(note)
            elif operation == 'restore':
                note['trashed'] = False
            elif operation == 'pin':
                if note is None:
                    raise ValueError('Bitte zuerst eine gespeicherte Notiz auswählen.')
                note['pinned'] = pinned
            else:
                if note is None:
                    if len(data['notes']) >= MAX_NOTES:
                        raise ValueError('Höchstens 100 Notizen einschließlich Papierkorb; bitte zuerst eine alte Notiz endgültig entfernen.')
                    note = {'id': uuid.uuid4().hex}
                    data['notes'].append(note)
                note.update(title=title, body=body, updated_at=datetime.now(timezone.utc).isoformat())
                note_id = note['id']
            data['revision'] += 1
            write_json(self.path, data)
            return data, note_id


def search_notes(notes, query, *, trash_only=False):
    """Literal case-insensitive filtering; no expression evaluation or network."""
    query = query.strip().casefold()
    matches = [note for note in notes if note.get('trashed', False) == trash_only
               and (not query or query in note['title'].casefold() or query in note['body'].casefold())]
    return sorted(matches, key=lambda note: (not note.get('pinned', False), note['title'].casefold(), note['id']))


def note_excerpt(note, query='', *, limit=140):
    """Bounded plain text around a literal body hit, including Unicode casefold."""
    lines = [line.strip() for line in note['body'].splitlines() if line.strip()]
    query = query.strip().casefold()
    line = next((line for line in lines if query and query in line.casefold()), lines[0] if lines else '')
    position = line.casefold().find(query) if query else 0
    character = 0
    folded_position = 0
    if position > 0:
        for index, value in enumerate(line):
            if folded_position + len(value.casefold()) > position:
                character = index
                break
            folded_position += len(value.casefold())
    start = max(0, character - 40)
    end = min(len(line), start + limit)
    return ('…' if start else '') + line[start:end] + ('…' if end < len(line) else '')
