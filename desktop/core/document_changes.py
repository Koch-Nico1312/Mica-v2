"""Compare an explicitly selected historical text with the current local file."""
from difflib import unified_diff
from desktop.core.attachments import extract_attachment


def compare_document(document, *, baseline_at=None, reader=extract_attachment):
    if not document.get('local_path'):
        raise ValueError('Diese Aufnahme hat keine Originaldatei zum Vergleichen.')
    current = reader(document['local_path'])
    before, after = document['body'], current['body']
    timestamp = baseline_at or document.get('loaded_at') or 'Zeitpunkt unbekannt'
    # Diff records need their own newline even for files with no terminal LF.
    diff = '\n'.join(unified_diff(before.splitlines(), after.splitlines(),
        fromfile=f"{document['title']} · gespeicherte Fassung ({timestamp})",
        tofile=f"{current['title']} · aktuell ({current['loaded_at']})", n=3, lineterm=''))
    # A missing terminal newline must not merge adjacent diff records.
    if before != after and not diff:
        diff = 'Die Zeilenenden oder der abschließende Zeilenumbruch wurden geändert; der Zeilentext ist gleich.'
    return {'title': document['title'], 'baseline_at': timestamp, 'current_at': current['loaded_at'],
        'changed': before != after, 'diff': diff[:12000], 'diff_truncated': len(diff) > 12000,
        'extraction_truncated': bool(document.get('truncated') or current.get('truncated'))}
