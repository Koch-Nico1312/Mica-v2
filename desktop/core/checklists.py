"""Explicit local named checklists with atomic persistence and revision checks."""
from copy import deepcopy
import re
import uuid
from desktop.core.local_state import DATA_DIR, FileLease, read_json, write_json


class ChecklistStore:
    def __init__(self, path=None):
        self.path = path or DATA_DIR / 'checklists.json'

    def read(self):
        try:
            data = read_json(self.path, limit=2 * 1024 * 1024)
        except FileNotFoundError:
            return {'version': 1, 'revision': 0, 'lists': []}
        if (not isinstance(data, dict) or data.get('version') != 1 or type(data.get('revision')) is not int
                or data['revision'] < 0 or not isinstance(data.get('lists'), list) or len(data['lists']) > 20):
            raise ValueError('Der gespeicherte Listenstand ist ungültig.')
        ids, names = set(), set()
        for record in data['lists']:
            if (not isinstance(record, dict) or not isinstance(record.get('id'), str)
                    or not re.fullmatch(r'[a-f0-9]{32}', record['id']) or record['id'] in ids
                    or not isinstance(record.get('name'), str) or not 1 <= len(record['name']) <= 80
                    or record['name'].casefold() in names or not isinstance(record.get('items'), list)
                    or len(record['items']) > 200):
                raise ValueError('Eine gespeicherte Liste ist ungültig.')
            ids.add(record['id'])
            names.add(record['name'].casefold())
            for item in record['items']:
                if (not isinstance(item, dict) or not isinstance(item.get('id'), str)
                        or not re.fullmatch(r'[a-f0-9]{32}', item['id']) or item['id'] in ids
                        or not isinstance(item.get('text'), str) or not 1 <= len(item['text']) <= 240
                        or type(item.get('done')) is not bool):
                    raise ValueError('Ein gespeicherter Listeneintrag ist ungültig.')
                ids.add(item['id'])
        return data

    def change(self, operation, *, revision, list_id=None, item_id=None, text='', done=None):
        if operation not in {'create', 'rename', 'add', 'toggle', 'remove_item', 'remove_list'}:
            raise ValueError('Unbekannte Listenaktion.')
        if operation in {'create', 'rename', 'add'}:
            maximum = 240 if operation == 'add' else 80
            if not isinstance(text, str) or not 1 <= len(text.strip()) <= maximum or '\n' in text or '\r' in text:
                raise ValueError(f'Bitte 1–{maximum} Zeichen in einer Zeile eingeben.')
            text = text.strip()
        with FileLease(str(self.path) + '.lock', label='Die Checklisten'):
            data = self.read()
            if type(revision) is not int or revision != data['revision']:
                raise ValueError('Die Liste wurde inzwischen geändert. Bitte den aktuellen Stand prüfen.')
            data = deepcopy(data)
            record = next((entry for entry in data['lists'] if entry['id'] == list_id), None)
            if operation != 'create' and record is None:
                raise ValueError('Die ausgewählte Liste ist nicht mehr vorhanden.')
            if operation in {'create', 'rename'} and any(
                    entry['name'].casefold() == text.casefold() and (operation == 'create' or entry['id'] != list_id)
                    for entry in data['lists']):
                raise ValueError('Eine Liste mit diesem Namen ist bereits vorhanden.')
            if operation == 'create':
                if len(data['lists']) >= 20:
                    raise ValueError('Höchstens 20 Listen; bitte zuerst eine alte Liste entfernen.')
                record = {'id': uuid.uuid4().hex, 'name': text, 'items': []}
                data['lists'].append(record)
            elif operation == 'rename':
                record['name'] = text
            elif operation == 'add':
                if len(record['items']) >= 200:
                    raise ValueError('Höchstens 200 Einträge in einer Liste.')
                if any(item['text'].casefold() == text.casefold() for item in record['items']):
                    raise ValueError('Dieser Eintrag ist bereits in der Liste.')
                record['items'].append({'id': uuid.uuid4().hex, 'text': text, 'done': False})
            elif operation == 'remove_list':
                data['lists'].remove(record)
            else:
                item = next((entry for entry in record['items'] if entry['id'] == item_id), None)
                if item is None:
                    raise ValueError('Der ausgewählte Eintrag ist nicht mehr vorhanden.')
                if operation == 'toggle':
                    if type(done) is not bool:
                        raise ValueError('Ungültiger Erledigt-Zustand.')
                    item['done'] = done
                else:
                    record['items'].remove(item)
            data['revision'] += 1
            write_json(self.path, data)
            return data, record['id']
