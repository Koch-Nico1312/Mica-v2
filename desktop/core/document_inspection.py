"""Inspect explicitly selected, already extracted text without reading files."""
from __future__ import annotations

import math
import re

WORD = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*", re.UNICODE)


def _documents(documents):
    if not isinstance(documents, list) or len(documents) > 8:
        raise ValueError('Bitte höchstens acht Dokumente auswählen.')
    total = 0
    for doc in documents:
        if (not isinstance(doc, dict) or not isinstance(doc.get('title'), str)
                or not isinstance(doc.get('body'), str) or len(doc['body']) > 32000):
            raise ValueError('Die ausgewählte Textversion ist ungültig.')
        total += len(doc['body'])
    if total > 64000:
        raise ValueError('Die ausgewählten Texte sind zusammen zu groß.')
    return documents


def document_statistics(documents):
    rows = []
    for doc in _documents(documents):
        body = doc['body']
        rows.append({'title': doc['title'], 'words': len(WORD.findall(body)),
                     'characters': len(body), 'characters_without_spaces': sum(not c.isspace() for c in body),
                     'paragraphs': len([part for part in re.split(r'\n\s*\n', body.strip()) if part.strip()]),
                     'changed': bool(doc.get('changed')), 'truncated': bool(doc.get('truncated'))})
    return rows


def statistics_text(documents):
    rows = document_statistics(documents)
    if not rows:
        return 'Bitte zuerst unter Dateien ein Dokument auswählen.'
    lines = ['Dokumentinfos – ausgewählte Textversion', '']
    for row in rows:
        lines.extend([row['title'], f"{row['words']} Wörter · {row['characters']} Zeichen · {row['characters_without_spaces']} Zeichen ohne Leerraum · {row['paragraphs']} Absätze"])
        if row['changed']:
            lines.append('Datei wurde geändert oder ist nicht erreichbar; dies ist die zuvor eingelesene Version.')
        if row['truncated']:
            lines.append('Text wurde beim Einlesen gekürzt; diese Zahlen gelten nur für den eingelesenen Ausschnitt.')
        lines.append('')
    total = sum(row['words'] for row in rows)
    lines.append(f'Insgesamt: {total} Wörter. Geschätzte reine Lesedauer bei 200 Wörtern/Minute: {math.ceil(total / 200)} Minuten.')
    lines.append('Wortzählung: Buchstaben-/Zahlengruppen; verbundene Wörter wie E-Mail zählen als ein Wort. Formatierung und OCR können die Zählung beeinflussen.')
    return '\n'.join(lines)


def search_documents(documents, query, *, limit=20):
    documents = _documents(documents)
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 120:
        raise ValueError('Bitte einen Suchtext mit 1–120 Zeichen eingeben.')
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Ungültige Treffergrenze.')
    pattern = re.compile(re.escape(query.strip()), re.IGNORECASE)
    hits = []
    for doc in documents:
        for match in pattern.finditer(doc['body']):
            if len(hits) == limit:
                return {'hits': hits, 'more': True}
            start, end = max(0, match.start() - 90), min(len(doc['body']), match.end() + 150)
            hits.append({'title': doc['title'], 'line': doc['body'].count('\n', 0, match.start()) + 1,
                         'snippet': doc['body'][start:end], 'changed': bool(doc.get('changed')),
                         'truncated': bool(doc.get('truncated'))})
    return {'hits': hits, 'more': False}


def search_text(documents, query):
    result = search_documents(documents, query)
    if not result['hits']:
        return 'Keine Treffer in den ausgewählten Textversionen.'
    lines = []
    for hit in result['hits']:
        lines.extend([f"{hit['title']} · Textzeile {hit['line']}", hit['snippet']])
        if hit['changed'] or hit['truncated']:
            lines.append('Hinweis: Dieser Treffer stammt aus einer zuvor eingelesenen oder gekürzten Textversion.')
        lines.append('')
    if result['more']:
        lines.append('Weitere Treffer vorhanden. Bitte den Suchtext präzisieren.')
    return '\n'.join(lines)
