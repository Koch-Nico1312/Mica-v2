"""Validate editable, ordered task suggestions; proposals never create actions."""
import json


def parse_steps(raw):
    text = raw.strip()
    if text.startswith('```') and text.endswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0]
    try:
        items = json.loads(text)['steps']
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError('Das Modell hat keine lesbare Schrittfolge geliefert.') from error
    if not isinstance(items, list) or not 2 <= len(items) <= 12:
        raise ValueError('Eine Schrittfolge braucht 2–12 Schritte.')
    result = []
    for index, item in enumerate(items):
        if (not isinstance(item, dict) or not isinstance(item.get('title'), str)
            or not 1 <= len(item['title'].strip()) <= 160
            or not isinstance(item.get('description', ''), str) or len(item.get('description', '')) > 2000
            or type(item.get('minutes')) is not int or not 5 <= item['minutes'] <= 240):
            raise ValueError('Ungültiger Schritt oder ungültige Dauerschätzung.')
        result.append({'title': item['title'].strip(), 'description': item.get('description', '').strip(),
            'minutes': item['minutes'], 'after': index - 1 if index else None})
    return result
