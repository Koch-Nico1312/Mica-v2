"""Explicit local named checklists with atomic persistence and revision checks."""
from copy import deepcopy
import re
import uuid
from desktop.core.local_state import DATA_DIR, FileLease, read_json, write_json

CHECKLIST_TEMPLATES = {
    'Einkauf': ('Obst und Gemüse', 'Brot', 'Milch oder Alternative', 'Vorräte prüfen'),
    'Reise': ('Ausweis oder Reisepass', 'Tickets und Buchungen', 'Ladegerät',
              'Kleidung', 'Hygieneartikel', 'Schlüssel'),
    'Arbeitsbeginn': ('Tagesplan ansehen', 'Wichtigste Aufgabe wählen',
                      'Benötigte Unterlagen öffnen', 'Ablenkungen reduzieren'),
}


def parse_checklist_lines(text):
    """Accept pasted plain/bulleted/task-list text, without reading the clipboard."""
    if not isinstance(text, str) or len(text) > 64_000:
        raise ValueError('Bitte höchstens 64.000 Zeichen einfügen.')
    items = []
    seen = set()
    for number, line in enumerate(text.splitlines(), 1):
        value = line.strip()
        if not value:
            continue
        value = re.sub(r'^(?:[-*•]\s+|\d+[.)]\s+)', '', value)
        checked = re.match(r'^\[([ xX])\]\s+', value)
        done = bool(checked and checked[1].lower() == 'x')
        if checked:
            value = value[checked.end():].strip()
        if not 1 <= len(value) <= 240:
            raise ValueError(f'Zeile {number}: Bitte 1–240 Zeichen pro Eintrag verwenden.')
        if value.casefold() in seen:
            raise ValueError(f'Zeile {number}: Eintrag ist im eingefügten Text doppelt vorhanden.')
        seen.add(value.casefold())
        items.append({'text': value, 'done': done})
        if len(items) > 200:
            raise ValueError('Höchstens 200 Einträge in einer Liste.')
    if not items:
        raise ValueError('Bitte mindestens einen Eintrag eingeben.')
    return items


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

    def change(self, operation, *, revision, list_id=None, item_id=None, text='', done=None, template=None, items=None, lines=None):
        if operation not in {'create', 'rename', 'add', 'toggle', 'remove_item', 'remove_list',
                             'from_template', 'duplicate', 'reset', 'add_many', 'edit', 'from_text'}:
            raise ValueError('Unbekannte Listenaktion.')
        if operation == 'from_template' and (not isinstance(template, str) or template not in CHECKLIST_TEMPLATES):
            raise ValueError('Bitte eine vorhandene Listenvorlage wählen.')
        parsed_items = parse_checklist_lines(lines) if operation == 'from_text' else None
        if operation in {'create', 'rename', 'add', 'from_template', 'duplicate', 'edit', 'from_text'}:
            maximum = 240 if operation in {'add', 'edit'} else 80
            if not isinstance(text, str) or not 1 <= len(text.strip()) <= maximum or '\n' in text or '\r' in text:
                raise ValueError(f'Bitte 1–{maximum} Zeichen in einer Zeile eingeben.')
            text = text.strip()
        with FileLease(str(self.path) + '.lock', label='Die Checklisten'):
            data = self.read()
            if type(revision) is not int or revision != data['revision']:
                raise ValueError('Die Liste wurde inzwischen geändert. Bitte den aktuellen Stand prüfen.')
            data = deepcopy(data)
            record = next((entry for entry in data['lists'] if entry['id'] == list_id), None)
            creates_list = operation in {'create', 'from_template', 'duplicate', 'from_text'}
            if operation not in {'create', 'from_template', 'from_text'} and record is None:
                raise ValueError('Die ausgewählte Liste ist nicht mehr vorhanden.')
            if (creates_list or operation == 'rename') and any(
                    entry['name'].casefold() == text.casefold() and (creates_list or entry['id'] != list_id)
                    for entry in data['lists']):
                raise ValueError('Eine Liste mit diesem Namen ist bereits vorhanden.')
            if creates_list:
                if len(data['lists']) >= 20:
                    raise ValueError('Höchstens 20 Listen; bitte zuerst eine alte Liste entfernen.')
                texts = (CHECKLIST_TEMPLATES[template] if operation == 'from_template' else
                         [item['text'] for item in record['items']] if operation == 'duplicate' else [])
                record = {'id': uuid.uuid4().hex, 'name': text,
                          'items': [{'id': uuid.uuid4().hex, 'text': value, 'done': False} for value in texts]}
                if parsed_items is not None:
                    record['items'] = [{'id': uuid.uuid4().hex, **item} for item in parsed_items]
                data['lists'].append(record)
            elif operation == 'rename':
                record['name'] = text
            elif operation == 'add':
                if len(record['items']) >= 200:
                    raise ValueError('Höchstens 200 Einträge in einer Liste.')
                if any(item['text'].casefold() == text.casefold() for item in record['items']):
                    raise ValueError('Dieser Eintrag ist bereits in der Liste.')
                record['items'].append({'id': uuid.uuid4().hex, 'text': text, 'done': False})
            elif operation == 'add_many':
                if not isinstance(items, list) or not 1 <= len(items) <= 200:
                    raise ValueError('Bitte 1–200 Einträge übergeben.')
                if len(record['items']) + len(items) > 200:
                    raise ValueError('Zusammen höchstens 200 Einträge in einer Liste.')
                seen = {item['text'].casefold() for item in record['items']}
                for item in items:
                    if (not isinstance(item, dict) or not isinstance(item.get('text'), str)
                            or not 1 <= len(item['text'].strip()) <= 240
                            or '\n' in item['text'] or '\r' in item['text'] or type(item.get('done')) is not bool):
                        raise ValueError('Ein eingefügter Eintrag ist ungültig.')
                    value = item['text'].strip()
                    if value.casefold() in seen:
                        raise ValueError('Ein eingefügter Eintrag ist bereits vorhanden. Bitte doppelte Einträge entfernen.')
                    seen.add(value.casefold())
                    record['items'].append({'id': uuid.uuid4().hex, 'text': value, 'done': item['done']})
            elif operation == 'remove_list':
                data['lists'].remove(record)
            elif operation == 'reset':
                for item in record['items']:
                    item['done'] = False
            else:
                item = next((entry for entry in record['items'] if entry['id'] == item_id), None)
                if item is None:
                    raise ValueError('Der ausgewählte Eintrag ist nicht mehr vorhanden.')
                if operation == 'toggle':
                    if type(done) is not bool:
                        raise ValueError('Ungültiger Erledigt-Zustand.')
                    item['done'] = done
                elif operation == 'edit':
                    if any(other['id'] != item_id and other['text'].casefold() == text.casefold()
                           for other in record['items']):
                        raise ValueError('Dieser Eintrag ist bereits in der Liste.')
                    item['text'] = text
                else:
                    record['items'].remove(item)
            data['revision'] += 1
            write_json(self.path, data)
            return data, record['id']
