"""Exact user-command grammar; never execute model prose or shell strings."""
from __future__ import annotations
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

APP_NAMES = {"editor": "notepad", "texteditor": "notepad", "notizblock": "notepad", "notepad": "notepad", "rechner": "calculator",
             "taschenrechner": "calculator", "explorer": "explorer", "edge": "edge",
             "chrome": "chrome", "firefox": "firefox", "obsidian": "obsidian",
             "notion": "notion", "spotify": "spotify", "discord": "discord",
             "visual studio code": "visual studio code", "vscode": "vscode"}
NUMBER_WORDS = {"eine": 1, "einen": 1, "eins": 1, "zwei": 2, "drei": 3,
                "vier": 4, "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8,
                "neun": 9, "zehn": 10, "elf": 11, "zwölf": 12, "dreizehn": 13,
                "vierzehn": 14, "fünfzehn": 15, "sechzehn": 16, "siebzehn": 17,
                "achtzehn": 18, "neunzehn": 19, "zwanzig": 20,
                "einundzwanzig": 21, "zweiundzwanzig": 22, "dreiundzwanzig": 23,
                "dreißig": 30, "vierzig": 40, "fünfzig": 50, "sechzig": 60,
                "siebzig": 70, "achtzig": 80, "neunzig": 90, "hundert": 100, "null": 0}


def parse_quick_command(message: str) -> dict | None:
    text = re.sub(r"^(?:(?:hallo|hey)\s+)?mica[,\s]+", "", message.strip(), flags=re.I)
    original = re.sub(r"^bitte\s+", "", text, flags=re.I).rstrip(".!?")
    text = original.casefold()
    if text in {'was steht heute an', 'tagesübersicht', 'zeige meine tagesübersicht', 'was muss ich heute machen'}:
        return {'kind': 'day_overview'}
    if text in {"arbeitsmodus starten", "starte arbeitsmodus", "starte den arbeitsmodus"}:
        return {"kind": "routine", "name": "work"}
    # Explicit named routine grammar never grants arbitrary program execution.
    named = re.fullmatch(r'(?:starte (?:den )?ablauf\s*(.+)|ablauf (.+) starten)', text)
    if named:
        name = named[1] or named[2]
        if re.fullmatch(r'[\wäöüß][\wäöüß -]{0,49}', name):
            return {'kind': 'routine', 'name': name}
    if text in {'schulmodus starten', 'programmieren starten', 'feierabend starten'}:
        return {'kind': 'routine', 'name': text.removesuffix(' starten')}
    if text in {'arbeitsstand speichern', 'speichere meinen arbeitsstand'}:
        return {'kind': 'workspace_save'}
    if text in {'arbeitsstand laden', 'mach dort weiter, wo wir aufgehört haben', 'mach dort weiter wo wir aufgehört haben', 'weiterarbeiten'}:
        return {'kind': 'workspace_resume'}
    preference = re.fullmatch(r'antworte(?: bei (technischen|persönlichen) fragen)? (kürzer|ausführlicher|in stichpunkten|auf deutsch)', text)
    if preference:
        scope = {None: 'global', 'technischen': 'technical', 'persönlichen': 'personal'}[preference[1]]
        key = 'Antwortlänge' if preference[2] in {'kürzer', 'ausführlicher'} else 'Antwortformat' if preference[2] == 'in stichpunkten' else 'Antwortsprache'
        return {'kind': 'preference_offer', 'key': key, 'value': preference[2], 'scope': scope}
    if text in {"ruhemodus beenden", "ruhezeiten beenden", "arbeitsmodus beenden"}:
        return {"kind": "quiet_end"}
    correction = re.fullmatch(r"(?:nein[, ]+)?(\d+|[\wäöüß]+) (sekunden?|minuten?|stunden?) statt (\d+|[\wäöüß]+)(?: (sekunden?|minuten?|stunden?))?", text)
    if correction:
        amount = int(correction[1]) if correction[1].isdigit() else NUMBER_WORDS.get(correction[1], 0)
        old = int(correction[3]) if correction[3].isdigit() else NUMBER_WORDS.get(correction[3], 0)
        factor = lambda unit: 3600 if unit.startswith("stund") else 60 if unit.startswith("minut") else 1
        seconds = amount * factor(correction[2])
        old_seconds = old * factor(correction[4] or correction[2])
        if 1 <= seconds <= 86400 and 1 <= old_seconds <= 86400:
            return {"kind": "timer_correct", "seconds": seconds, "previous_seconds": old_seconds}
    if text in {"lauter", "lautstärke erhöhen", "mach lauter"}:
        return {"kind": "volume", "action": "volume_up"}
    if text in {"leiser", "lautstärke reduzieren", "mach leiser"}:
        return {"kind": "volume", "action": "volume_down"}
    if text in {"ton stummschalten", "lautsprecher stummschalten"}:
        return {"kind": "volume", "action": "mute"}
    match = re.fullmatch(r"(?:(?:setze|stell|stelle) (?:die )?)?lautstärke (?:auf )?(\d{1,3}|\w+)\s*(?:%|prozent)?", text)
    value = (int(match[1]) if match[1].isdigit() else NUMBER_WORDS.get(match[1], -1)) if match else -1
    if match and 0 <= value <= 100:
        return {"kind": "volume", "action": "volume_set", "value": value}
    match = re.fullmatch(r"(?:öffne|starte) (.+)", text)
    if match and match[1] in APP_NAMES:
        return {"kind": "app", "app_name": APP_NAMES[match[1]], "label": match[1].capitalize()}
    match = re.fullmatch(r"(?:(?:setze|starte|stell|stelle) (?:einen )?)?timer (?:auf |für )?(\d+|[\wäöüß]+) (sekunden?|minuten?|stunden?)", text)
    if match:
        amount = int(match[1]) if match[1].isdigit() else NUMBER_WORDS.get(match[1], 0)
        factor = 3600 if match[2].startswith("stund") else 60 if match[2].startswith("minut") else 1
        seconds = amount * factor
        if 1 <= seconds <= 86400:
            return {"kind": "timer", "seconds": seconds}
    if text in {"timer stoppen", "timer abbrechen", "stoppe den timer", "brich den timer ab"}:
        return {"kind": "timer_cancel"}
    if text in {"timer anzeigen", "wie lange läuft der timer noch", "wie lange läuft mein timer noch"}:
        return {"kind": "timer_status"}
    match = re.fullmatch(r"(?:erinnere mich|erinner mich) (heute|morgen|übermorgen) um (\d{1,2}):(\d{2})(?: uhr)? (?:an|daran,?) (.+)", original, re.I)
    if match and int(match[2]) <= 23 and int(match[3]) <= 59:
        now = datetime.now(ZoneInfo("Europe/Vienna"))
        target = (now + timedelta(days={"heute": 0, "morgen": 1, "übermorgen": 2}[match[1].casefold()])).replace(
            hour=int(match[2]), minute=int(match[3]), second=0, microsecond=0)
        if target > now:
            return {"kind": "reminder", "date": target.date().isoformat(), "time": target.strftime("%H:%M"),
                    "message": match[4][:500]}
    return None
