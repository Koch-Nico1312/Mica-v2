"""An explicitly saved work checkpoint, without conversation transcripts."""
from datetime import datetime, UTC
import re
from desktop.core.local_state import DATA_DIR, read_json, write_json
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
            identifiers.add(doc['id'])
            total += len(doc['body'])
        if total > 64000 or not isinstance(data.get('next_step'), str) or len(data['next_step']) > 2000:
            raise ValueError('Arbeitsstand ist zu groß.')
        if data.get('task_id') is not None and (not isinstance(data['task_id'], str) or not re.fullmatch(r'[a-f0-9]{32}', data['task_id'])):
            raise ValueError('Ungültige Aufgabenkennung.')
        if not isinstance(data.get('task_title', ''), str) or len(data.get('task_title', '')) > 160:
            raise ValueError('Ungültiger Aufgabenname.')
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
