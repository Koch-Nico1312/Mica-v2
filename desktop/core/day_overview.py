"""Join the Core overview with the same Windows reminder index used by the HUD."""
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from desktop.core.local_state import read_json


def bounded_overview(reply):
    if len(reply) <= 1950:
        return reply
    suffix = '\n\nÜbersicht gekürzt. Alle Einträge findest du unter Aufgaben und Zeitpläne; Windows-Erinnerungen stehen im lokalen Register.'
    return reply[:1950 - len(suffix)].rsplit('\n', 1)[0] + suffix


def desktop_day_overview(client, *, path=None, now=None):
    reply = client.day_overview()['reply']
    now = now or datetime.now(ZoneInfo('Europe/Vienna'))
    path = path or Path.home() / '.jarvis' / 'reminders' / 'reminders.json'
    try:
        records = read_json(path, limit=524288)
        if not isinstance(records, list):
            raise ValueError('Ungültiges Erinnerungsregister.')
    except FileNotFoundError:
        return bounded_overview(reply)
    except (OSError, ValueError):
        return bounded_overview(reply + '\n\nDas lokale Windows-Erinnerungsregister konnte nicht gelesen werden.')
    reminders = []
    for item in records:
        try:
            when = datetime.strptime(item['when'], '%Y-%m-%d %H:%M').replace(tzinfo=ZoneInfo('Europe/Vienna'))
            message = str(item['message'])[:500]
        except (KeyError, TypeError, ValueError):
            continue
        if when.date() == now.date():
            reminders.append((when, message))
    reminders.sort()
    if reminders:
        reply += '\n\nWindows-Erinnerungen heute (lokales Register):\n' + '\n'.join(
            '- ' + when.strftime('%H:%M') + ' · ' + message + (' · Zeitpunkt bereits erreicht' if when <= now else '')
            for when, message in reminders[:12]) + '\nDer tatsächliche Zustellstatus dieser Windows-Erinnerungen wurde hier nicht geprüft.'
        if len(reminders) > 12:
            reply += '\nDie Liste wurde auf zwölf Einträge gekürzt.'
    return bounded_overview(reply)
