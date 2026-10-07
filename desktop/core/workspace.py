"""An explicitly saved work checkpoint, without conversation transcripts."""
from datetime import datetime, UTC
import re
from pathlib import Path
from desktop.core.local_state import DATA_DIR, read_json, write_json, FileLease
from desktop.core.attachments import attachment_changed


class WorkspaceStore:
    def __init__(self, path=None):
        self.path = path or DATA_DIR / 'workspace.json'

    @staticmethod
    def validate(data):
        if not isinstance(data, dict) or data.get('version') != 1:
            raise ValueError('Arbeitsstand ist ungültig.')
        docs = data.get('documents')
        if not isinstance(docs, list) or len(docs) > 8:
            raise ValueError('Arbeitsstand enthält zu viele Dateien.')
        identifiers, total = set(), 0
        for doc in docs:
            if (not isinstance(doc, dict) or not isinstance(doc.get('id'), str)
                or not re.fullmatch(r'[a-f0-9]{32}', doc['id']) or doc['id'] in identifiers
                or any(not isinstance(doc.get(key), str) for key in ('title', 'body', 'source'))
                or not 1 <= len(doc['title']) <= 160 or len(doc['body']) > 32000
                or doc['source'] not in {'text', 'pdf', 'screenshot'}
                or any(key in doc and not isinstance(doc[key], str) for key in ('local_path', 'fingerprint'))):
                raise ValueError('Arbeitsstand enthält eine ungültige Datei.')
            if 'loaded_at' in doc and not isinstance(doc['loaded_at'], str):
                raise ValueError('Ungültiger Dokumentzeitpunkt.')
            if 'truncated' in doc and type(doc['truncated']) is not bool:
                raise ValueError('Ungültige Dokumentbegrenzung.')
            identifiers.add(doc['id'])
            total += len(doc['body'])
        if total > 64000 or not isinstance(data.get('next_step'), str) or len(data['next_step']) > 2000:
            raise ValueError('Arbeitsstand ist zu groß.')
        if data.get('task_id') is not None and (not isinstance(data['task_id'], str) or not re.fullmatch(r'[a-f0-9]{32}', data['task_id'])):
            raise ValueError('Ungültige Aufgabenkennung.')
        if not isinstance(data.get('task_title', ''), str) or len(data.get('task_title', '')) > 160:
            raise ValueError('Ungültiger Aufgabenname.')
        if type(data.get('remember_progress', False)) is not bool or not isinstance(data.get('last_step', ''), str) or len(data.get('last_step', '')) > 2000:
            raise ValueError('Ungültiger letzter Arbeitsschritt.')
        return data

    def save(self, documents, task_id, next_step, task_title=''):
        # Persist only selected content and provenance, never pending actions.
        docs = [{key: doc[key] for key in ('id', 'title', 'body', 'source', 'local_path', 'fingerprint') if key in doc}
                for doc in documents]
        data = self.validate({'version': 1, 'documents': docs, 'task_id': task_id,
                              'next_step': next_step, 'task_title': task_title, 'saved_at': datetime.now(UTC).isoformat()})
        write_json(self.path, data)
        return data

    def load(self):
        return self.validate(read_json(self.path, limit=524288))

    def warnings(self, data):
        return [doc['title'] for doc in data['documents'] if attachment_changed(doc)]

    def forget(self):
        from pathlib import Path
        Path(self.path).unlink(missing_ok=True)


class ProjectWorkspaceStore(WorkspaceStore):
    """Named checkpoints with three explicitly saved versions per project."""
    def __init__(self, path=None, legacy_path=None):
        super().__init__(path or DATA_DIR / 'project-workspaces.json')
        self.legacy_path = Path(legacy_path or DATA_DIR / 'workspace.json')

    @staticmethod
    def name(value):
        if not isinstance(value, str):
            raise ValueError('Bitte einen Projektnamen eingeben.')
        value = value.strip().casefold()
        if not re.fullmatch(r'[\w][\w .-]{0,49}', value):
            raise ValueError('Projektname: 1–50 Buchstaben, Zahlen, Leerzeichen, Punkte oder Bindestriche.')
        return value

    def all(self):
        try:
            data = read_json(self.path, limit=24 * 1024 * 1024)
        except FileNotFoundError:
            if self.legacy_path.exists():
                return {'standard': [WorkspaceStore(self.legacy_path).load()]}
            return {}
        if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('projects'), dict) or len(data['projects']) > 20:
            raise ValueError('Gespeicherte Projektstände sind ungültig.')
        for name, versions in data['projects'].items():
            if self.name(name) != name or not isinstance(versions, list) or not 1 <= len(versions) <= 3:
                raise ValueError('Gespeicherte Projektstände sind ungültig.')
            for version in versions:
                self.validate(version)
                try:
                    timestamp = datetime.fromisoformat(version['saved_at'])
                    if timestamp.tzinfo is None:
                        raise ValueError('Zeitpunkt ohne Zeitzone.')
                except (KeyError, TypeError, ValueError) as error:
                    raise ValueError('Ungültiger Zeitpunkt im Projektstand.') from error
        return data['projects']

    def names(self):
        return sorted(self.all())

    def save(self, documents, task_id, next_step, task_title='', name='standard', *, last_step='', remember_progress=False):
        with FileLease(str(self.path) + '.lock', label='Die Projektstände'):
            return self._save(documents, task_id, next_step, task_title, name, last_step, remember_progress)

    def _save(self, documents, task_id, next_step, task_title, name, last_step, remember_progress):
        name = self.name(name)
        projects = self.all()
        if name not in projects and len(projects) >= 20:
            raise ValueError('Höchstens 20 Projekte; zuerst einen Projektstand löschen.')
        docs = [{key: doc[key] for key in ('id', 'title', 'body', 'source', 'local_path', 'fingerprint', 'loaded_at', 'truncated') if key in doc} for doc in documents]
        data = self.validate({'version': 1, 'documents': docs, 'task_id': task_id,
            'next_step': next_step, 'task_title': task_title, 'saved_at': datetime.now(UTC).isoformat(),
            'last_step': last_step, 'remember_progress': remember_progress})
        projects[name] = [*projects.get(name, []), data][-3:]
        write_json(self.path, {'version': 1, 'projects': projects})
        return data

    def record_progress(self, name, request):
        """Update only the opted-in latest checkpoint, retaining older baselines."""
        if not isinstance(request, str) or not request.strip():
            return False
        with FileLease(str(self.path) + '.lock', label='Die Projektstände'):
            projects = self.all()
            latest = projects.get(self.name(name), [])
            if not latest or not latest[-1].get('remember_progress', False):
                return False
            latest[-1]['last_step'] = 'Zuletzt besprochen: ' + request.strip()[:1980]
            latest[-1]['progress_at'] = datetime.now(UTC).isoformat()
            self.validate(latest[-1])
            write_json(self.path, {'version': 1, 'projects': projects})
            return True

    def load(self, name='standard'):
        name = self.name(name)
        versions = self.all().get(name)
        if not versions:
            raise FileNotFoundError('Für dieses Projekt ist kein Arbeitsstand gespeichert.')
        return versions[-1]

    def forget(self, name='standard'):
        with FileLease(str(self.path) + '.lock', label='Die Projektstände'):
            projects = self.all()
            projects.pop(self.name(name), None)
            write_json(self.path, {'version': 1, 'projects': projects})
