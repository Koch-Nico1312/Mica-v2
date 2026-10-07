"""Bounded German routine requests create editable drafts, never actions."""
import re


def routine_draft(text):
    match = re.fullmatch(r'erstelle (?:einen |eine |den |die )?(?:ablauf )?([\w][\w -]{0,49}):\s*(.{1,1000})', text, re.I)
    if not match:
        return None
    body = match[2].casefold().strip()
    focus = re.search(r'(\d{1,4}) minuten? fokus', body)
    pause = re.search(r'(\d{1,4}) minuten? pause', body)
    if not focus or not 1 <= int(focus[1]) <= 1440:
        return None
    if pause and not 1 <= int(pause[1]) <= 1440:
        return None
    # Unknown clauses stay visible in the editor instead of becoming commands.
    return {'kind': 'routine_draft', 'name': match[1].strip(), 'request': match[2],
        'focus_minutes': int(focus[1]), 'pause_minutes': int(pause[1]) if pause else 5 if 'pause' in body else 0,
        'selected_documents': bool(re.search(r'(?:unterlagen|dokumente|dateien) öffnen', body))}
