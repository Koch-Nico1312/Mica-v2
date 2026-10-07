"""Convert model drafts into bounded suggestions with exact source evidence."""
import json
from datetime import datetime


def parse_document_drafts(raw, documents, operation):
    text = raw.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    data = json.loads(text)
    items = data.get('items') if isinstance(data, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= 20:
        raise ValueError('Das Modell hat keine gültige Vorschlagsliste geliefert.')
    sources = {doc['id']: doc for doc in documents}
    result = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('Ungültiger Vorschlag.')
        source = sources.get(item.get('document_id'))
        quote = item.get('quote')
        if not source or not isinstance(quote, str) or not 5 <= len(quote) <= 1200:
            raise ValueError('Ein Vorschlag enthält keinen prüfbaren Quellenbeleg.')
        start = source['body'].find(quote)
        if start < 0 or source['body'].find(quote, start + 1) >= 0:
            raise ValueError('Die vorgeschlagene Textstelle ist nicht eindeutig im Dokument enthalten.')
        field = 'title' if operation == 'tasks' else 'question'
        title = item.get(field)
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= (160 if operation == 'tasks' else 500):
            raise ValueError('Ein Vorschlag enthält keinen gültigen Titel.')
        entry = {field: title.strip(), 'source': {'document_id': source['id'], 'title': source['title'], 'quote': quote,
            'start': start, 'end': start + len(quote), 'line': source['body'][:start].count('\n') + 1}}
        if operation == 'tasks':
            due = item.get('due_at')
            if due is not None:
                if not isinstance(due, str) or len(due) > 64 or datetime.fromisoformat(due).tzinfo is None:
                    raise ValueError('Ein Termin enthält keine gültige Zeit mit Zeitzone.')
            entry['due_at'] = due
        else:
            # The answer is the verified passage, not unsupported model prose.
            entry['answer'] = quote
        result.append(entry)
    return result
