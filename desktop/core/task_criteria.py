"""Explicit per-task file criteria and bounded evidence; checks never complete a task."""
from datetime import datetime, UTC
from pathlib import Path
import json
import re
from desktop.core.local_state import DATA_DIR, FileLease, read_json, write_json
from desktop.core.outcome_verification import file_snapshot, verify_file


class TaskCriteriaStore:
    def __init__(self, path=None):
        self.path = path or DATA_DIR / 'task-criteria.json'

    def read(self):
        try:
            data = read_json(self.path, limit=2 * 1024 * 1024)
        except FileNotFoundError:
            return {}
        if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('criteria'), dict) or len(data['criteria']) > 500:
            raise ValueError('Ungültige Aufgabenprüfungen.')
        for identifier, entry in data['criteria'].items():
            self.validate(identifier, entry)
        return data['criteria']

    def write(self, data):
        payload = {'version': 1, 'criteria': data}
        if len(json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')) > 2 * 1024 * 1024:
            raise ValueError('Aufgabenprüfungen sind zu groß. Bitte alte Kriterien entfernen.')
        write_json(self.path, payload)

    @staticmethod
    def validate(identifier, entry):
        if not re.fullmatch(r'[a-f0-9]{32}', identifier) or not isinstance(entry, dict):
            raise ValueError('Ungültige Aufgabenprüfung.')
        if (not isinstance(entry.get('path'), str) or not 1 <= len(entry['path']) <= 4096
                or not isinstance(entry.get('expected_text'), str) or len(entry['expected_text']) > 2000
                or type(entry.get('require_changed')) is not bool):
            raise ValueError('Datei und erwarteter Text sind ungültig.')
        if entry['require_changed'] and (not isinstance(entry.get('baseline'), dict) or entry['baseline'].get('path') != entry['path']):
            raise ValueError('Für den Änderungsnachweis fehlt die Ausgangsfassung.')
        return entry

    def set(self, identifier, path, expected_text='', require_changed=False):
        if not isinstance(path, str) or not path.strip():
            raise ValueError('Bitte eine Prüfdatei angeben.')
        entry = {'path': str(Path(path).expanduser().resolve()), 'expected_text': expected_text,
            'require_changed': require_changed, 'saved_at': datetime.now(UTC).isoformat()}
        if require_changed:
            entry['baseline'] = file_snapshot(entry['path'])
        self.validate(identifier, entry)
        with FileLease(str(self.path) + '.lock', label='Die Aufgabenprüfungen'):
            data = self.read()
            if identifier not in data and len(data) >= 500:
                raise ValueError('Höchstens 500 Aufgabenprüfungen.')
            data[identifier] = entry
            self.write(data)
        return entry

    def remove(self, identifier):
        with FileLease(str(self.path) + '.lock', label='Die Aufgabenprüfungen'):
            data = self.read()
            data.pop(identifier, None)
            self.write(data)

    def check(self, identifier):
        with FileLease(str(self.path) + '.lock', label='Die Aufgabenprüfungen'):
            data = self.read()
            entry = data.get(identifier)
            if not entry:
                raise ValueError('Für diese Aufgabe ist keine Prüfung gespeichert.')
            result = verify_file(entry['path'], baseline=entry.get('baseline'), expected_text=entry['expected_text'], require_changed=entry['require_changed'])
            entry['last_result'] = result
            self.write(data)
            return result

    def complete(self, identifier, task_store):
        # Recheck at explicit completion, rather than trusting an earlier green label.
        task = next((t for t in task_store.view() if t['id'] == identifier), None)
        if not task or task.get('status') not in {'open', 'in_progress'}:
            raise ValueError('Die Aufgabe ist nicht mehr offen.')
        result = self.check(identifier)
        if result['status'] != 'confirmed':
            raise ValueError('Aufgabe bleibt offen: ' + result['detail'])
        task_store.stage({**task, 'status': 'completed'}, minutes=task.get('minutes', 30), depends_on=task.get('depends_on', []), expected_view=task)
        return result
