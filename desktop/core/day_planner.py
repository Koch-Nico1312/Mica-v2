"""Deterministic planning inside explicitly supplied free windows, with no actions."""
from datetime import datetime, timedelta, UTC
import hashlib
import json


def aware(value):
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('Zeitfenster und Fristen brauchen eine Zeitzone.')
    return result


def build_day_plan(tasks, windows, *, break_minutes=10, focus_minutes=45, allow_short_remainder=False):
    if type(break_minutes) is not int or not 0 <= break_minutes <= 60 or type(focus_minutes) is not int or not 5 <= focus_minutes <= 120:
        raise ValueError('Fokus: 5–120 Minuten; Pause: 0–60 Minuten.')
    if not 1 <= len(windows) <= 20 or len(tasks) > 200:
        raise ValueError('Bitte 1–20 freie Zeitfenster und höchstens 200 Aufgaben wählen.')
    display_zone = aware(windows[0][0]).tzinfo
    windows = sorted((aware(start).astimezone(UTC), aware(end).astimezone(UTC)) for start, end in windows)
    for index, (start, end) in enumerate(windows):
        if end <= start or end - start > timedelta(days=1) or (index and start < windows[index - 1][1]):
            raise ValueError('Freie Zeitfenster dürfen sich nicht überschneiden und höchstens einen Tag dauern.')
    if windows[-1][1] - windows[0][0] > timedelta(days=2):
        raise ValueError('Der Tagesplan darf höchstens zwei Kalendertage umfassen.')
    ids = set()
    remaining, complete, blocks, warnings = {}, {}, [], []
    ordered = []
    for task in tasks:
        identifier = task['id']
        if identifier in ids or not isinstance(identifier, str):
            raise ValueError('Doppelte oder ungültige Aufgabe.')
        ids.add(identifier)
        if task.get('status') in {'completed', 'cancelled'}:
            continue
        duration = task.get('minutes')
        if type(duration) is not int or not (1 if allow_short_remainder else 5) <= duration <= 1440:
            raise ValueError('Jede Aufgabe braucht eine Dauer von 5–1.440 Minuten.')
        dependencies = task.get('depends_on', [])
        if not isinstance(dependencies, list) or identifier in dependencies:
            raise ValueError('Ungültige Aufgabenabhängigkeit.')
        due = aware(task['due_at']).astimezone(UTC) if task.get('due_at') else None
        ordered.append({**task, 'deadline': due, 'depends_on': dependencies})
        remaining[identifier] = duration
    known = {task['id'] for task in tasks}
    complete.update({task['id']: windows[0][0] for task in tasks if task.get('status') == 'completed'})
    for task in ordered:
        if any(dep not in known for dep in task['depends_on']):
            warnings.append(task['title'] + ': eine Voraussetzung fehlt in der Auswahl.')
    ordered.sort(key=lambda task: (task['deadline'].timestamp() if task['deadline'] else float('inf'),
        {'high': 0, 'normal': 1, 'low': 2}.get(task.get('priority'), 1), task['id']))
    next_allowed = windows[0][0]
    for start, end in windows:
        cursor = max(start, next_allowed)
        if start < cursor < end:
            blocks.append({'kind': 'break', 'title': 'Pause', 'start': start.astimezone(display_zone).isoformat(),
                'end': cursor.astimezone(display_zone).isoformat(), 'minutes': int((cursor - start).total_seconds() // 60)})
        while cursor < end:
            eligible = [task for task in ordered if remaining[task['id']] and all(dep in complete for dep in task['depends_on'])
                and (not task['deadline'] or cursor < task['deadline'])]
            if not eligible:
                break
            task = eligible[0]
            boundary = min(end, task['deadline']) if task['deadline'] else end
            available = int((boundary - cursor).total_seconds() // 60)
            amount = min(focus_minutes, remaining[task['id']], available)
            if amount <= 0 or (amount < 5 and amount < remaining[task['id']]):
                # A later deadline may still fit the remaining part of this window.
                alternatives = [item for item in eligible[1:] if not item['deadline'] or item['deadline'] >= cursor + timedelta(minutes=5)]
                if not alternatives:
                    break
                task = alternatives[0]
                boundary = min(end, task['deadline']) if task['deadline'] else end
                amount = min(focus_minutes, remaining[task['id']], int((boundary - cursor).total_seconds() // 60))
                if amount <= 0 or (amount < 5 and amount < remaining[task['id']]):
                    break
            finish = cursor + timedelta(minutes=amount)
            blocks.append({'kind': 'task', 'task_id': task['id'], 'title': task['title'],
                'start': cursor.astimezone(display_zone).isoformat(), 'end': finish.astimezone(display_zone).isoformat(), 'minutes': amount})
            remaining[task['id']] -= amount
            cursor = finish
            next_allowed = cursor + timedelta(minutes=break_minutes)
            if not remaining[task['id']]:
                complete[task['id']] = finish
            work_left = any(remaining[item['id']] and all(dep in complete for dep in item['depends_on'])
                and (not item['deadline'] or cursor + timedelta(minutes=break_minutes + 5) <= item['deadline']) for item in ordered)
            if break_minutes and work_left and cursor + timedelta(minutes=break_minutes + 5) <= end:
                finish = cursor + timedelta(minutes=break_minutes)
                blocks.append({'kind': 'break', 'title': 'Pause', 'start': cursor.astimezone(display_zone).isoformat(),
                    'end': finish.astimezone(display_zone).isoformat(), 'minutes': break_minutes})
                cursor = finish
            elif break_minutes:
                # Do not squeeze another focus block into a window without its pause.
                break
    unplanned = [{'task_id': task['id'], 'title': task['title'], 'minutes': remaining[task['id']],
        'reason': 'Frist, fehlende Voraussetzung oder zu wenig freie Zeit.'} for task in ordered if remaining[task['id']]]
    result = {'version': 1, 'blocks': blocks, 'unplanned': unplanned, 'warnings': warnings,
        'inputs': {'tasks': tasks, 'windows': [(s.isoformat(), e.isoformat()) for s, e in windows],
            'break_minutes': break_minutes, 'focus_minutes': focus_minutes}}
    result['fingerprint'] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return result
