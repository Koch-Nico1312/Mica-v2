"""Turn one verified Jira issue response into a reviewable local task."""
import json
import re
import uuid


def _description(value):
    if isinstance(value, str):
        return value[:3000]
    if value is None:
        return ''
    if not isinstance(value, dict):
        raise ValueError('Die Jira-Beschreibung hat ein unbekanntes Format.')
    parts, visited = [], [0]
    def walk(node, depth=0):
        visited[0] += 1
        if visited[0] > 1000 or depth > 12:
            raise ValueError('Die Jira-Beschreibung ist zu komplex für den lokalen Import.')
        if not isinstance(node, dict):
            return
        if isinstance(node.get('text'), str):
            parts.append(node['text'])
        for child in node.get('content', []) if isinstance(node.get('content'), list) else []:
            walk(child, depth + 1)
        if node.get('type') in {'paragraph', 'heading', 'listItem', 'hardBreak'}:
            parts.append('\n')
    walk(value)
    return ''.join(parts).strip()[:3000]


def issue_task_draft(result, cloud_id, expected_key):
    if not isinstance(cloud_id, str) or not cloud_id or len(cloud_id) > 200:
        raise ValueError('Die Atlassian-Website fehlt.')
    key = expected_key.strip().upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9_]*-\d+', key):
        raise ValueError('Die angefragte Jira-Vorgangsnummer ist ungültig.')
    candidates = [result.get('structuredContent')]
    for item in result.get('content', []):
        if isinstance(item, dict) and item.get('type') == 'text' and isinstance(item.get('text'), str):
            try:
                candidates.append(json.loads(item['text']))
            except ValueError:
                pass
    issue = next((item for item in candidates if isinstance(item, dict) and item.get('key') == key), None)
    if issue is None:
        raise ValueError('Die Antwort enthält keinen eindeutig passenden Jira-Vorgang.')
    fields = issue.get('fields', {})
    summary = fields.get('summary') if isinstance(fields, dict) else None
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError('Der Jira-Vorgang hat keinen lesbaren Titel.')
    description = _description(fields.get('description'))
    identity = uuid.uuid5(uuid.NAMESPACE_URL, f'mica:jira:{cloud_id}:{key}').hex
    return {'id': identity, 'title': f'{key}: {summary.strip()}'[:160],
            'description': f'Quelle: Jira {key}\nAtlassian-Website: {cloud_id}\n\n{description}'[:4000],
            'status': 'open', 'priority': 'normal', 'due_at': None}
