"""Portable Markdown from the selected saved project and explicit task/card snapshots."""
from datetime import datetime, UTC
import html
from pathlib import Path
import re
import os
import tempfile


def plain(value):
    # Escape literal markup, including Obsidian transclusion and remote images.
    value = html.escape(str(value), quote=False)
    return re.sub(r'([\\`*_{}\[\]()#+.!|>~-])', r'\\\1', value)


def project_markdown(name, checkpoint, tasks, *, cards=(), fetched_at=None):
    from desktop.core.workspace import WorkspaceStore
    WorkspaceStore.validate(checkpoint)
    lines = ['# ' + plain(name), '', 'Exportiert: ' + datetime.now(UTC).isoformat(),
        'Projektstand: ' + plain(checkpoint.get('saved_at', 'unbekannt')),
        'Aufgabenstand: ' + plain(fetched_at or 'lokal / nicht abgeglichen'), '', '## Hier warst du', '',
        plain(checkpoint.get('last_step') or 'Noch kein Schritt festgehalten.'), '', '## Nächster Schritt', '',
        plain(checkpoint['next_step'] or 'Noch nicht festgelegt.'), '', '## Aufgaben', '']
    for task in tasks:
        marker = 'x' if task.get('status') == 'completed' else ' '
        lines += [f'- [{marker}] ' + plain(task['title']) + (' · nur lokal vorgemerkt' if task.get('pending') else ''),
            '  Status: ' + plain(task.get('status', 'open')) + ' · Frist: ' + plain(task.get('due_at') or 'keine')]
        if task.get('description'):
            lines += [''] + ['  ' + plain(line) for line in task['description'].splitlines()]
    lines += ['', '## Quellen und ausgewählte Dokumentinhalte', '']
    document_ids = set()
    for doc in checkpoint['documents']:
        document_ids.add(doc['id'])
        lines += ['### ' + plain(doc['title']), '', 'Herkunft: ' + plain(doc['source']) +
            ' · Dokumentkennung: ' + plain(doc['id']), '']
        # Quotes remain literal text; never emit executable HTML, embeds or local file links.
        lines += ['> ' + plain(line) for line in doc['body'].splitlines()] + ['']
    selected_cards = [card for card in cards if card['source']['document_id'] in document_ids]
    if selected_cards:
        lines += ['## Lernkarten und Quellenzitate', '']
        for card in selected_cards:
            lines += ['### ' + plain(card['question']), '', '> ' + plain(card['answer']).replace('\n', '\n> '), '',
                'Quelle: ' + plain(card['source']['title']) + ' · Zeile ' + str(card['source']['line']), '']
    return '\n'.join(lines).rstrip() + '\n'


def write_export(path, markdown):
    path = Path(path).resolve()
    if path.suffix.casefold() != '.md':
        raise ValueError('Bitte eine Datei mit der Endung .md wählen.')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(markdown)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
