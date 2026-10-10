"""Literal Markdown exports with atomic publication to an explicitly chosen file."""
import os
from pathlib import Path
import re
import tempfile


def literal_markdown(value):
    return re.sub(r'([\\`*_{}\[\]()<>#!|+\-.])', r'\\\1', value)


def note_markdown(title, body, *, saved):
    if not title.strip() or not body.strip():
        raise ValueError('Bitte zuerst Titel und Notiztext eingeben.')
    lines = ['# ' + literal_markdown(title.strip()), '']
    if not saved:
        lines.extend(['Hinweis: Dieser Entwurf ist noch nicht in MICA gespeichert.', ''])
    lines.extend(literal_markdown(line) + '  ' for line in body.splitlines())
    return '\n'.join(lines).rstrip() + '\n'


def checklist_markdown(record, *, fresh):
    lines = ['# ' + literal_markdown(record['name']), '']
    if not fresh:
        lines.extend(['Hinweis: Dies ist eine ältere Ansicht; die gespeicherte Liste wurde inzwischen geändert.', ''])
    if not record['items']:
        lines.append('Diese Liste enthält keine Einträge.')
    for item in record['items']:
        lines.append(f"- [{'x' if item['done'] else ' '}] " + literal_markdown(item['text']))
    return '\n'.join(lines) + '\n'


def save_markdown(path, text):
    target = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=target.parent, prefix='.mica-markdown-',
                                         suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
