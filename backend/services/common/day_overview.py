"""Read-only day overview based on local task and reminder records."""
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import HTTPException

VIENNA = ZoneInfo('Europe/Vienna')


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(VIENNA) if parsed.tzinfo else parsed.replace(tzinfo=VIENNA)
    except (ValueError, TypeError, AttributeError):
        return None


def day_overview(runtime, *, now=None):
    now = now or datetime.now(VIENNA)
    now = now.astimezone(VIENNA)
    unavailable = False
    try:
        tasks = [item for item in runtime.list_task_items()['tasks'] if item['status'] in {'open', 'in_progress'}]
    except HTTPException as error:
        if error.status_code != 409:
            raise
        tasks, unavailable = [], True
    def rank(task):
        due = timestamp(task.get('due_at'))
        bucket = 0 if due and due < now else 1 if due and due.date() == now.date() else 2 if not due else 3
        return (bucket, {'high': 0, 'normal': 1, 'low': 2}.get(task.get('priority'), 1), due or datetime.max.replace(tzinfo=VIENNA), task['title'].casefold())
    tasks.sort(key=rank)
    lines = ['Heute, ' + now.strftime('%d.%m.%Y') + ' (Europe/Vienna)']
    due_today, other = [], []
    for task in tasks:
        due = timestamp(task.get('due_at'))
        label = task['title'] + (' · in Bearbeitung' if task['status'] == 'in_progress' else '')
        if due and due.date() <= now.date():
            due_today.append(label + (' · überfällig' if due < now else ' · ' + due.strftime('%H:%M')))
        else:
            other.append(label + (' · fällig ' + due.strftime('%d.%m. %H:%M') if due else ' · ohne Termin'))
    lines.append('Aufgaben heute / überfällig:\n' + ('\n'.join('- ' + item for item in due_today[:12]) or 'Keine.'))
    lines.append('Weitere unerledigte Aufgaben:\n' + ('\n'.join('- ' + item for item in other[:12]) or 'Keine.'))
    if unavailable:
        lines.append('Aufgabenverwaltung ist deaktiviert; diese Übersicht enthält keine Aufgaben daraus.')
    reminders = []
    for item in runtime.list_schedules()['schedules']:
        due = timestamp(item.get('run_at'))
        if (item.get('action') in {'reminder.create', 'reminder.dispatch'} and item.get('status') in {'pending', 'awaiting_approval'}
            and due and due.date() <= now.date()):
            reminders.append((due, item['name'], item['status']))
    reminders.sort()
    lines.append('Erinnerungen:\n' + ('\n'.join('- ' + title + ' · ' + due.strftime('%d.%m. %H:%M') +
        (' · wartet auf Freigabe' if status == 'awaiting_approval' else ' · überfällig' if due < now else '')
        for due, title, status in reminders[:12]) or 'Keine anstehenden Erinnerungen.'))
    if len(tasks) > 24 or len(due_today) > 12 or len(other) > 12 or len(reminders) > 12:
        lines.append('Die Übersicht ist gekürzt; alle Einträge findest du unter Aufgaben und Zeitpläne.')
    if tasks:
        suggestion = 'Vorschlag zum Anfangen: „' + tasks[0]['title'] + '“.'
    elif reminders:
        suggestion = 'Vorschlag zum Anfangen: Prüfe die nächste anstehende Erinnerung „' + reminders[0][1] + '“.'
    else:
        suggestion = 'Vorschlag zum Anfangen: Lege deine wichtigste Aufgabe für heute fest.'
    lines.insert(1, suggestion)
    return '\n\n'.join(lines)
