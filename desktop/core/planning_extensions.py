"""Read-only calendar availability and explicit, reproducible plan changes."""
from copy import deepcopy
from datetime import datetime, date, time, timedelta, UTC
import hashlib
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo
from desktop.core.day_planner import aware, build_day_plan

ZONE = ZoneInfo('Europe/Vienna')


def block_id(block):
    return hashlib.sha256(json.dumps({k: block.get(k) for k in ('task_id', 'start', 'end')}, sort_keys=True).encode()).hexdigest()[:32]


def fingerprint_plan(plan):
    return hashlib.sha256(json.dumps({k: v for k, v in plan.items() if k not in {'fingerprint', 'accepted_at'}}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def calendar_busy(path, day):
    """Expand one selected local ICS snapshot; never connect to or write a calendar."""
    from icalendar import Calendar
    import recurring_ical_events
    path = Path(path).resolve()
    with path.open('rb') as handle:
        body = handle.read(2 * 1024 * 1024 + 1)
    if len(body) > 2 * 1024 * 1024:
        raise ValueError('Kalenderdatei: höchstens 2 MB.')
    try:
        calendar = Calendar.from_ical(body)
        if calendar.name != 'VCALENDAR':
            raise ValueError('Keine ICS-Kalenderdatei.')
        events = calendar.walk('VEVENT')
        if len(events) > 2000:
            raise ValueError('Kalender enthält mehr als 2.000 Termine.')
        for event in events:
            if event.errors or 'DTSTART' not in event:
                raise ValueError('Ein Kalendertermin ist nicht lesbar.')
            rule = event.get('RRULE', {})
            if any(str(freq).upper() in {'SECONDLY', 'MINUTELY', 'HOURLY'} for freq in rule.get('FREQ', [])):
                raise ValueError('Zu häufige Kalenderwiederholung; bitte einen Tagesexport verwenden.')
            for key in ('DTSTART', 'DTEND', 'RECURRENCE-ID'):
                value = event.get(key)
                if value and value.params.get('TZID') and isinstance(value.dt, datetime) and value.dt.tzinfo is None:
                    raise ValueError('Unbekannte Zeitzone im Kalender.')
        start = datetime.combine(day, time.min, ZONE)
        stop = datetime.combine(day + timedelta(days=1), time.min, ZONE)
        expanded = recurring_ical_events.of(calendar).between(start, stop)
        if len(expanded) > 2000:
            raise ValueError('Zu viele Termine an diesem Tag.')
        busy = []
        def moment(value):
            if isinstance(value, datetime):
                if value.tzinfo is None:
                    value = value.replace(tzinfo=ZONE)
                    if value.replace(fold=0).utcoffset() != value.replace(fold=1).utcoffset() or value.astimezone(UTC).astimezone(ZONE).replace(tzinfo=None) != value.replace(tzinfo=None):
                        raise ValueError('Kalenderzeit ohne Zeitzone ist wegen Zeitumstellung nicht eindeutig.')
                return value
            if isinstance(value, date):
                return datetime.combine(value, time.min, ZONE)
            raise ValueError('Ungültiger Kalenderzeitpunkt.')
        for event in expanded:
            if str(event.get('STATUS', '')).upper() == 'CANCELLED' or str(event.get('TRANSP', '')).upper() == 'TRANSPARENT':
                continue
            begin = moment(event.decoded('DTSTART'))
            raw_end = event.decoded('DTEND') if 'DTEND' in event else None
            end = moment(raw_end) if raw_end is not None else begin + (event.decoded('DURATION') if 'DURATION' in event else timedelta(days=1) if not isinstance(event.decoded('DTSTART'), datetime) else timedelta())
            if end < begin:
                raise ValueError('Kalendertermin endet vor seinem Beginn.')
            if begin < stop and end > start:
                busy.append({'start': max(begin.astimezone(UTC), start.astimezone(UTC)).isoformat(),
                    'end': min(end.astimezone(UTC), stop.astimezone(UTC)).isoformat(),
                    'title': str(event.get('SUMMARY', 'Belegt'))[:160]})
        return {'path': str(path), 'sha256': hashlib.sha256(body).hexdigest(), 'day': day.isoformat(), 'busy': busy}
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise ValueError('Kalender nicht vollständig lesbar: ' + str(error)) from error


def subtract_busy(windows, busy):
    """Subtract the union of busy intervals, preserving the requested display zone."""
    result = []
    for begin, end in windows:
        zone = aware(begin).tzinfo
        pieces = [(aware(begin).astimezone(UTC), aware(end).astimezone(UTC))]
        for event in busy:
            left, right = aware(event['start']).astimezone(UTC), aware(event['end']).astimezone(UTC)
            if right <= left:
                raise ValueError('Ungültige belegte Kalenderzeit.')
            remaining = []
            for start, stop in pieces:
                if right <= start or left >= stop:
                    remaining.append((start, stop))
                else:
                    if start < left:
                        remaining.append((start, left))
                    if right < stop:
                        remaining.append((right, stop))
            pieces = remaining
        result.extend((s.astimezone(zone), e.astimezone(zone)) for s, e in pieces if e - s >= timedelta(minutes=1))
    if len(result) > 20:
        raise ValueError('Kalender teilt den Tag in mehr als 20 Fenster. Bitte enger planen.')
    return result


def parse_adjustment(text):
    text = text.strip().rstrip('.!?')
    late = re.fullmatch(r'(?:ich habe |ich kann )?erst ab (\d{1,2})(?::(\d{2}))?\s*(?:uhr)?(?: zeit)?', text, re.I)
    if late:
        hour, minute = int(late[1]), int(late[2] or 0)
        if hour > 23 or minute > 59:
            raise ValueError('Bitte eine gültige Uhrzeit angeben.')
        return {'kind': 'available_from', 'time': f'{hour:02}:{minute:02}'}
    longer = re.fullmatch(r'(?:die )?aufgabe(?: (.+?))? dauert (?:länger|(?:jetzt )?(\d{1,4}) minuten)', text, re.I)
    if longer:
        minutes = int(longer[2]) if longer[2] else None
        if minutes is not None and not 5 <= minutes <= 1440:
            raise ValueError('Dauer: 5–1.440 Minuten.')
        return {'kind': 'duration', 'title': longer[1] or '', 'minutes': minutes}
    raise ValueError('Zum Beispiel: Ich habe erst ab 15 Uhr Zeit; oder: Aufgabe Bericht dauert 60 Minuten.')


def study_tasks(cards, day, *, minutes_per_card=2, block_minutes=15):
    boundary = datetime.combine(day + timedelta(days=1), time.min, ZONE)
    candidates = [card for card in cards if aware(card['due_at']) < boundary or card.get('last_rating') in {'again', 'hard'}]
    candidates.sort(key=lambda card: (0 if card.get('last_rating') in {'again', 'hard'} else 1, aware(card['due_at']).astimezone(UTC), card['id']))
    groups = {}
    for card in candidates:
        groups.setdefault(card['source']['document_id'], []).append(card)
    tasks = []
    for doc_id, group in groups.items():
        size = max(1, block_minutes // minutes_per_card)
        for offset in range(0, len(group), size):
            batch = group[offset:offset + size]
            identifier = hashlib.sha256(('study:' + day.isoformat() + ':' + ':'.join(c['id'] for c in batch)).encode()).hexdigest()[:32]
            tasks.append({'id': identifier, 'title': 'Lernen: ' + batch[0]['source']['title'], 'status': 'open',
                'minutes': max(5, len(batch) * minutes_per_card), 'priority': 'high' if any(c.get('last_rating') in {'again', 'hard'} for c in batch) else 'normal',
                'depends_on': [], 'due_at': None, 'card_ids': [c['id'] for c in batch], 'document_id': doc_id})
    if len(tasks) > 200:
        raise ValueError('Zu viele Lernblöcke; bitte weniger Lernkarten auswählen.')
    return tasks


def extended_plan(tasks, windows, *, busy=None, calendar=None, previous=None, change=None,
                  now=None, break_minutes=10, focus_minutes=45):
    """Keep elapsed blocks fixed; only explicitly revised future work is rescheduled."""
    tasks = deepcopy(tasks)
    overrides = deepcopy(previous.get('duration_overrides', {})) if previous else {}
    for task in tasks:
        if task['id'] in overrides:
            task['minutes'] = overrides[task['id']]
    # Validate original windows before subtraction, so overlaps cannot be hidden.
    base = build_day_plan(tasks, windows, break_minutes=break_minutes, focus_minutes=focus_minutes)
    base['inputs'] = deepcopy(base['inputs'])
    original_windows = windows
    fixed = []
    if previous is not None:
        now = aware(now or datetime.now(UTC))
        completed_ids = set(previous.get('completed_blocks', []))
        fixed = [deepcopy(block) for block in previous['blocks'] if block_id(block) in completed_ids
            or aware(block['start']) < now < aware(block['end'])]
        for task in tasks:
            consumed = sum(block['minutes'] for block in fixed if block.get('task_id') == task['id'])
            task['minutes'] = max(0, task['minutes'] - consumed)
        tasks = [task for task in tasks if task['minutes'] or task.get('status') == 'completed']
        cutoff = max([now, *[aware(b['end']) + timedelta(minutes=break_minutes if b['kind'] == 'task' else 0) for b in fixed]])
        if change and change['kind'] == 'available_from':
            day = aware(original_windows[0][0]).astimezone(ZONE).date()
            requested = datetime.combine(day, time.fromisoformat(change['time']), ZONE)
            if requested.replace(fold=0).utcoffset() != requested.replace(fold=1).utcoffset() or requested.astimezone(UTC).astimezone(ZONE).replace(tzinfo=None) != requested.replace(tzinfo=None):
                raise ValueError('Uhrzeit wegen Zeitumstellung nicht eindeutig.')
            cutoff = max(cutoff, requested)
        if change and change['kind'] == 'duration':
            matches = [task for task in tasks if task['id'] == change['task_id']]
            if len(matches) != 1:
                raise ValueError('Die gewählte Aufgabe hat keine offene Restarbeit.')
            task = matches[0]
            task['minutes'] = change['minutes']
            consumed = sum(b['minutes'] for b in fixed if b.get('task_id') == task['id'])
            overrides[task['id']] = consumed + change['minutes']
            if overrides[task['id']] > 1440:
                raise ValueError('Gesamtdauer mit bereits geplanter Arbeit: höchstens 1.440 Minuten.')
            for original in base['inputs']['tasks']:
                if original['id'] == task['id']:
                    original['minutes'] = overrides[task['id']]
        windows = [(max(aware(start), cutoff), aware(end)) for start, end in windows if aware(end) > cutoff]
        completed = {block['task_id'] for block in fixed if block.get('task_id')} - {task['id'] for task in tasks}
        for task in tasks:
            task['depends_on'] = [dep for dep in task.get('depends_on', []) if dep not in completed]
    windows = subtract_busy(windows, busy or [])
    if windows:
        plan = build_day_plan(tasks, windows, break_minutes=break_minutes, focus_minutes=focus_minutes, allow_short_remainder=True)
    else:
        plan = {'version': 1, 'blocks': [], 'unplanned': [{'task_id': t['id'], 'title': t['title'], 'minutes': t['minutes'],
            'reason': 'Keine freie Zeit nach Kalender und Anpassung.'} for t in tasks if t.get('status') not in {'completed', 'cancelled'}], 'warnings': []}
    plan['blocks'] = fixed + plan['blocks']
    plan['request'] = base['inputs']
    plan['calendar'] = calendar
    plan['adjustment'] = change
    plan['fixed_blocks'] = len(fixed)
    plan['previous_fingerprint'] = previous.get('fingerprint') if previous else None
    plan['duration_overrides'] = overrides
    plan['completed_blocks'] = [identifier for identifier in (previous or {}).get('completed_blocks', [])
        if identifier in {block_id(b) for b in fixed}]
    if previous:
        plan['changes'] = [{'task_id': task['id'], 'title': task['title'],
            'before': [b for b in previous['blocks'] if b not in fixed and b.get('task_id') == task['id']],
            'after': [b for b in plan['blocks'][len(fixed):] if b.get('task_id') == task['id']]} for task in tasks]
    plan['fingerprint'] = fingerprint_plan(plan)
    return plan
