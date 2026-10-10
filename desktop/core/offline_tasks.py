"""Local task snapshots and a review-only outbox. Reconnection never writes by itself."""
from copy import deepcopy
from datetime import datetime, UTC
import re
import uuid
from desktop.core.local_state import DATA_DIR, FileLease, read_json, write_json
from desktop.core.local_core_client import LocalCoreError

FIELDS = ('title', 'description', 'status', 'priority', 'due_at')


def canonical_fields(task):
    due = task.get('due_at')
    return {'title': task.get('title', '').strip(), 'description': task.get('description', '').strip(),
        'status': task.get('status', 'open'), 'priority': task.get('priority', 'normal'),
        'due_at': datetime.fromisoformat(due).astimezone(UTC).isoformat() if due else None}


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

    @staticmethod
    def remote_task(client, identifier):
        try:
            return client._request('GET', '/v1/task-items/' + identifier)
        except LocalCoreError as error:
            if error.status_code == 404:
                return None
            raise

    @staticmethod
    def clean_metadata(data):
        alive = {task['id'] for task in data['tasks']} | {item['desired']['id'] for item in data['pending']}
        data['metadata'] = {identifier: meta for identifier, meta in data['metadata'].items() if identifier in alive}
        parents = {meta.get('parent_id') for meta in data['metadata'].values()}
        for identifier, meta in data['metadata'].items():
            if meta.get('container') and identifier not in parents:
                meta.pop('container', None)

    @staticmethod
    def cache_task(data, task):
        """Keep a bounded, readable remote snapshot without evicting pending/referenced tasks."""
        data['tasks'] = [entry for entry in data['tasks'] if entry['id'] != task['id']] + [task]
        protected = {task['id']} | {item['desired']['id'] for item in data['pending']}
        alive = {entry['id'] for entry in data['tasks']} | protected
        for identifier, meta in data['metadata'].items():
            if identifier in alive:
                if meta.get('parent_id') or meta.get('container') or 'step' in meta:
                    protected.add(identifier)
                protected.update(meta.get('depends_on', []))
                if meta.get('parent_id'):
                    protected.add(meta['parent_id'])
        while len(data['tasks']) > 500:
            candidates = [entry for entry in data['tasks'] if entry['id'] not in protected]
            if not candidates:
                raise ValueError('Lokaler Aufgabenstand ist voll und alle Aufgaben sind vorgemerkt oder Voraussetzungen. Erst Änderungen abgleichen oder verwerfen; ausstehende Änderungen bleiben erhalten.')
            victim = min(candidates, key=lambda entry: (entry.get('status') not in {'completed', 'cancelled'}, entry.get('updated_at', ''), entry['id']))
            data['tasks'] = [entry for entry in data['tasks'] if entry['id'] != victim['id']]
        OfflineTasks.clean_metadata(data)

    def refresh(self, client):
        original = self.read()
        tasks = client.task_items()['tasks']
        for task in tasks:
            validate_task(task)
        if len(tasks) > 500:
            raise ValueError('Zu viele Aufgaben für den lokalen Stand.')
        merged = {task['id']: task for task in tasks}
        local_creates = {item['desired']['id'] for item in original['pending'] if item['kind'] == 'create'}
        needed = {task['id'] for task in original['tasks']} | {item['desired']['id'] for item in original['pending'] if item['kind'] == 'update'}
        for meta in original['metadata'].values():
            needed.update(meta.get('depends_on', []))
            if meta.get('parent_id'):
                needed.add(meta['parent_id'])
        for identifier in sorted(needed - merged.keys() - local_creates):
            task = self.remote_task(client, identifier)
            if task is not None:
                validate_task(task)
                merged[identifier] = task
        with FileLease(str(self.path) + '.lock', label='Die Offline-Aufgaben'):
            data = self.read()
            if data != original:
                raise ValueError('Lokaler Aufgabenstand änderte sich während des Ladens. Bitte erneut laden; deine Änderungen bleiben erhalten.')
            data['tasks'], data['fetched_at'] = list(merged.values()), datetime.now(UTC).isoformat()
            if merged:
                self.cache_task(data, next(iter(merged.values())))
            self.clean_metadata(data)
            write_json(self.path, data)
        return data

    def view(self):
        data = self.read()
        tasks = {task['id']: deepcopy(task) for task in data['tasks']}
        for item in data['pending']:
            tasks[item['desired']['id']] = {**item['desired'], 'pending': True}
        return [{**task, **data['metadata'].get(identifier, {})} for identifier, task in tasks.items()]

    def stage(self, task, *, minutes=30, depends_on=None, expected_view=None, create_only=False):
        task = {'description': '', 'status': 'open', 'priority': 'normal', 'due_at': None, **task}
        validate_task(task)
        task = {**task, **canonical_fields(task)}
        if type(minutes) is not int or not 5 <= minutes <= 1440:
            raise ValueError('Dauer: 5–1.440 Minuten.')
        depends_on = list(depends_on or [])
        if task['id'] in depends_on or len(depends_on) > 20 or any(not re.fullmatch(r'[a-f0-9]{32}', dep) for dep in depends_on):
            raise ValueError('Ungültige Voraussetzungen.')
        with FileLease(str(self.path) + '.lock', label='Die Offline-Aufgaben'):
            data = self.read()
            if create_only and (any(entry['id'] == task['id'] for entry in data['tasks'])
                                or any(entry['desired']['id'] == task['id'] for entry in data['pending'])):
                raise ValueError('Dieser Vorgang wurde bereits als lokale Aufgabe übernommen. Bestehende Änderungen bleiben erhalten.')
            if expected_view is not None:
                current = next((entry for entry in self.view() if entry['id'] == task['id']), None)
                if current != expected_view:
                    raise ValueError('Aufgabe änderte sich während der Prüfung. Bitte erneut prüfen.')
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
            data['metadata'][task['id']] = {**data['metadata'].get(task['id'], {}), 'minutes': minutes, 'depends_on': depends_on}
            write_json(self.path, data)

    def preview(self, client):
        data = self.read()
        rows = []
        for item in data['pending']:
            remote = self.remote_task(client, item['desired']['id']) if item['kind'] == 'update' else None
            applied = item['kind'] == 'update' and remote and canonical_fields(remote) == canonical_fields(item['desired'])
            conflict = item['kind'] == 'update' and not applied and (not remote or canonical_fields(remote) != canonical_fields(item['base']))
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
                task = {**task, **canonical_fields(task)}
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
            if item and item['kind'] == 'create':
                identifier = item['desired']['id']
                if any(identifier in meta.get('depends_on', []) for owner, meta in data['metadata'].items() if owner != identifier):
                    raise ValueError('Andere Schritte benötigen diese Aufgabe. Zuerst die nachfolgenden Schritte verwerfen oder ihre Voraussetzung ändern.')
                data['metadata'].pop(identifier, None)
            data['pending'] = [item for item in data['pending'] if item['key'] != key]
            self.clean_metadata(data)
            write_json(self.path, data)

    def accept_remote(self, client, reviewed):
        if reviewed['kind'] != 'update':
            raise ValueError('Neue Aufgaben können erst nach geklärtem Speicherausgang verworfen werden.')
        remote = self.remote_task(client, reviewed['desired']['id'])
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
                self.cache_task(data, remote)
            self.clean_metadata(data)
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
                # Check cache capacity before a remote write; pending and dependency metadata stay protected.
                self.cache_task(deepcopy(data), item['desired'])
                item['attempted'] = True
                write_json(self.path, data)
            try:
                if reviewed['applied']:
                    result = client._request('GET', '/v1/task-items/' + item['desired']['id'])
                    if canonical_fields(result) != canonical_fields(item['desired']):
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
                data['tasks'] = [task for task in data['tasks'] if task['id'] != old_id]
                if old_id != new_id:
                    data['metadata'][new_id] = data['metadata'].pop(old_id, {})
                    for meta in data['metadata'].values():
                        meta['depends_on'] = [new_id if dep == old_id else dep for dep in meta.get('depends_on', [])]
                        if meta.get('parent_id') == old_id:
                            meta['parent_id'] = new_id
                self.cache_task(data, result)
                write_json(self.path, data)
            saved.append(new_id)
        return saved
