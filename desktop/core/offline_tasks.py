"""Local task snapshots and a review-only outbox. Reconnection never writes by itself."""
from copy import deepcopy
from datetime import datetime, UTC
import re
import uuid
from desktop.core.local_state import DATA_DIR, FileLease, read_json, write_json
from desktop.core.local_core_client import LocalCoreError

FIELDS = ('title', 'description', 'status', 'priority', 'due_at')


def validate_task(task):
    if not isinstance(task, dict) or not isinstance(task.get('id'), str) or not re.fullmatch(r'[a-f0-9]{32}', task['id']):
        raise ValueError('Ungültige Aufgabenkennung.')
    if not isinstance(task.get('title'), str) or not 1 <= len(task['title'].strip()) <= 160:
        raise ValueError('Aufgabentitel: 1–160 Zeichen.')
    if not isinstance(task.get('description', ''), str) or len(task.get('description', '')) > 4000:
        raise ValueError('Aufgabenbeschreibung: höchstens 4.000 Zeichen.')
    if task.get('status', 'open') not in {'open', 'in_progress', 'completed', 'cancelled'} or task.get('priority', 'normal') not in {'low', 'normal', 'high'}:
        raise ValueError('Ungültiger Aufgabenstatus oder Priorität.')
    if task.get('due_at'):
        if not isinstance(task['due_at'], str) or len(task['due_at']) > 64 or datetime.fromisoformat(task['due_at']).tzinfo is None:
            raise ValueError('Frist braucht eine Zeitzone.')
    return task


class OfflineTasks:
    def __init__(self, path=None):
        self.path = path or DATA_DIR / 'offline-tasks.json'

    def read(self):
        try:
            data = read_json(self.path, limit=8 * 1024 * 1024)
        except FileNotFoundError:
            return {'version': 1, 'tasks': [], 'pending': [], 'metadata': {}, 'fetched_at': None}
        if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('tasks'), list) or not isinstance(data.get('pending'), list) or not isinstance(data.get('metadata'), dict) or len(data['tasks']) > 500 or len(data['pending']) > 200:
            raise ValueError('Ungültiger Offline-Aufgabenstand.')
        for task in data['tasks']:
            validate_task(task)
        for item in data['pending']:
            if not isinstance(item, dict) or not isinstance(item.get('desired'), dict):
                raise ValueError('Ungültige vorgemerkte Änderung.')
            validate_task(item['desired'])
            if item.get('kind') not in {'create', 'update'} or not isinstance(item.get('key'), str) or not re.fullmatch(r'[a-f0-9]{32}', item['key']):
                raise ValueError('Ungültige vorgemerkte Änderung.')
            if item['kind'] == 'update':
                validate_task(item.get('base'))
        if len({task['id'] for task in data['tasks']}) != len(data['tasks']) or len({item['key'] for item in data['pending']}) != len(data['pending']):
            raise ValueError('Doppelte Aufgaben im Offline-Stand.')
        for identifier, meta in data['metadata'].items():
            if (not re.fullmatch(r'[a-f0-9]{32}', identifier) or not isinstance(meta, dict)
                or set(meta) - {'minutes', 'depends_on', 'parent_id', 'step', 'container'}
                or ('minutes' in meta and (type(meta['minutes']) is not int or not 5 <= meta['minutes'] <= 1440))
                or not isinstance(meta.get('depends_on', []), list)
                or any(not isinstance(dep, str) or not re.fullmatch(r'[a-f0-9]{32}', dep) for dep in meta.get('depends_on', []))):
                raise ValueError('Ungültige lokale Planungseinstellungen.')
        return data

    def refresh(self, client):
        tasks = client.task_items()['tasks']
        for task in tasks:
            validate_task(task)
        if len(tasks) > 500:
            raise ValueError('Zu viele Aufgaben für den lokalen Stand.')
        with FileLease(str(self.path) + '.lock', label='Die Offline-Aufgaben'):
            data = self.read()
            data['tasks'], data['fetched_at'] = tasks, datetime.now(UTC).isoformat()
            write_json(self.path, data)
        return data

    def view(self):
        data = self.read()
        tasks = {task['id']: deepcopy(task) for task in data['tasks']}
        for item in data['pending']:
            tasks[item['desired']['id']] = {**item['desired'], 'pending': True}
        return [{**task, **data['metadata'].get(identifier, {})} for identifier, task in tasks.items()]

    def stage(self, task, *, minutes=30, depends_on=None):
        task = {'description': '', 'status': 'open', 'priority': 'normal', 'due_at': None, **task}
        validate_task(task)
        if type(minutes) is not int or not 5 <= minutes <= 1440:
            raise ValueError('Dauer: 5–1.440 Minuten.')
        depends_on = list(depends_on or [])
        if task['id'] in depends_on or len(depends_on) > 20 or any(not re.fullmatch(r'[a-f0-9]{32}', dep) for dep in depends_on):
            raise ValueError('Ungültige Voraussetzungen.')
        with FileLease(str(self.path) + '.lock', label='Die Offline-Aufgaben'):
            data = self.read()
            existing = next((item for item in data['pending'] if item['desired']['id'] == task['id']), None)
            if existing and existing.get('attempted'):
                raise ValueError('Diese Änderung wurde bereits gesendet. Erst den Ausgang abgleichen, dann weiter bearbeiten.')
            original = next((item for item in data['tasks'] if item['id'] == task['id']), None)
            if not original and task.get('status', 'open') != 'open':
                raise ValueError('Neue lokale Aufgaben zuerst als offen abgleichen; danach den Status ändern.')
            desired = {key: task.get(key) for key in ('id', *FIELDS)}
            if not existing and len(data['pending']) >= 200:
                raise ValueError('Höchstens 200 vorgemerkte Änderungen.')
            if existing:
                existing['desired'] = desired
            else:
                data['pending'].append({'key': uuid.uuid4().hex, 'kind': 'update' if original else 'create',
                    'base': deepcopy(original), 'desired': desired})
            data['metadata'][task['id']] = {'minutes': minutes, 'depends_on': depends_on}
            write_json(self.path, data)

    def preview(self, client):
        data = self.read()
        current = {task['id']: task for task in client.task_items()['tasks']}
        rows = []
        for item in data['pending']:
            remote = current.get(item['desired']['id'])
            applied = item['kind'] == 'update' and remote and all(remote.get(key) == item['desired'].get(key) for key in FIELDS)
            conflict = item['kind'] == 'update' and not applied and (not remote or any(remote.get(key) != item['base'].get(key) for key in FIELDS))
            rows.append({**deepcopy(item), 'remote': remote, 'conflict': bool(conflict), 'applied': bool(applied)})
        return rows

    def stage_steps(self, steps, parent):
        if not 2 <= len(steps) <= 12:
            raise ValueError('Eine Schrittfolge braucht 2–12 Schritte.')
        with FileLease(str(self.path) + '.lock', label='Die Offline-Aufgaben'):
            data = self.read()
            if len(data['pending']) + len(steps) > 200:
                raise ValueError('Zu viele vorgemerkte Änderungen.')
            previous, added = None, []
            for index, step in enumerate(steps):
                identifier = uuid.uuid4().hex
                task = validate_task({'id': identifier, 'title': step['title'],
                    'description': ('Teil von: ' + parent['title'] + '\nSchritt ' + str(index + 1) + '\n' + step.get('description', ''))[:4000],
                    'status': 'open', 'priority': 'normal', 'due_at': parent.get('due_at')})
                if type(step['minutes']) is not int or not 5 <= step['minutes'] <= 240:
                    raise ValueError('Schritte brauchen 5–240 Minuten.')
                data['pending'].append({'key': uuid.uuid4().hex, 'kind': 'create', 'base': None, 'desired': task})
                data['metadata'][identifier] = {'minutes': step['minutes'], 'depends_on': [previous] if previous else [],
                    'parent_id': parent.get('id'), 'step': index + 1}
                previous = identifier
                added.append(identifier)
            if parent.get('id'):
                data['metadata'].setdefault(parent['id'], {})['container'] = True
            write_json(self.path, data)
        return added

    def discard(self, key):
        with FileLease(str(self.path) + '.lock', label='Die Offline-Aufgaben'):
            data = self.read()
            item = next((item for item in data['pending'] if item['key'] == key), None)
            if item and item.get('attempted'):
                raise ValueError('Ausgang einer gesendeten Änderung zuerst abgleichen; sonst kann sie bereits gespeichert sein.')
            data['pending'] = [item for item in data['pending'] if item['key'] != key]
            write_json(self.path, data)

    def accept_remote(self, client, reviewed):
        if reviewed['kind'] != 'update':
            raise ValueError('Neue Aufgaben können erst nach geklärtem Speicherausgang verworfen werden.')
        remote = client._request('GET', '/v1/task-items/' + reviewed['desired']['id']) if reviewed['remote'] else None
        if remote != reviewed['remote']:
            raise ValueError('Serverstand änderte sich seit der Vorschau. Bitte erneut abgleichen.')
        with FileLease(str(self.path) + '.lock', label='Die Offline-Aufgaben'):
            data = self.read()
            item = next((item for item in data['pending'] if item['key'] == reviewed['key']), None)
            if not item or item['desired'] != reviewed['desired']:
                raise ValueError('Lokaler Stand änderte sich seit der Vorschau.')
            data['pending'] = [entry for entry in data['pending'] if entry['key'] != reviewed['key']]
            data['tasks'] = [task for task in data['tasks'] if task['id'] != item['desired']['id']]
            if remote:
                data['tasks'].append(remote)
            write_json(self.path, data)

    def apply(self, client, preview):
        """Apply precisely the reviewed rows; changed remote values abort rather than overwrite."""
        saved = []
        for reviewed in preview:
            if reviewed['conflict']:
                continue
            with FileLease(str(self.path) + '.lock', label='Die Offline-Aufgaben'):
                data = self.read()
                item = next((item for item in data['pending'] if item['key'] == reviewed['key']), None)
                if not item or item['desired'] != reviewed['desired']:
                    raise ValueError('Lokale Änderung passt nicht mehr zur Vorschau. Bitte erneut abgleichen.')
                item['attempted'] = True
                write_json(self.path, data)
            try:
                if reviewed['applied']:
                    result = client._request('GET', '/v1/task-items/' + item['desired']['id'])
                    if any(result.get(key) != item['desired'].get(key) for key in FIELDS):
                        raise ValueError('Bereits gespeicherte Änderung wurde erneut verändert. Bitte erneut abgleichen.')
                elif item['kind'] == 'create':
                    result = client._request('POST', '/v1/task-items', json={key: item['desired'].get(key) for key in FIELDS if key != 'status'} | {'idempotency_key': item['key']})
                    if item['desired'].get('status') != 'open':
                        result = client._request('PATCH', '/v1/task-items/' + result['id'], json={'status': item['desired']['status'], 'expected_updated_at': result['updated_at']})
                else:
                    result = client._request('PATCH', '/v1/task-items/' + item['desired']['id'], json={key: item['desired'].get(key) for key in FIELDS} | {'expected_updated_at': reviewed['remote']['updated_at']})
            except LocalCoreError as error:
                if error.status_code is not None and error.status_code < 500:
                    with FileLease(str(self.path) + '.lock', label='Die Offline-Aufgaben'):
                        data = self.read()
                        for pending in data['pending']:
                            if pending['key'] == item['key']:
                                pending.pop('attempted', None)
                        write_json(self.path, data)
                raise
            validate_task(result)
            with FileLease(str(self.path) + '.lock', label='Die Offline-Aufgaben'):
                data = self.read()
                old_id, new_id = item['desired']['id'], result['id']
                data['pending'] = [entry for entry in data['pending'] if entry['key'] != item['key']]
                data['tasks'] = [task for task in data['tasks'] if task['id'] not in {old_id, new_id}] + [result]
                if old_id != new_id:
                    data['metadata'][new_id] = data['metadata'].pop(old_id, {})
                    for meta in data['metadata'].values():
                        meta['depends_on'] = [new_id if dep == old_id else dep for dep in meta.get('depends_on', [])]
                        if meta.get('parent_id') == old_id:
                            meta['parent_id'] = new_id
                write_json(self.path, data)
            saved.append(new_id)
        return saved
