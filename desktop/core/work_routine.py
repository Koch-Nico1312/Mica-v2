"""A user-configured local routine; each app still crosses the action broker."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from pathlib import Path
import threading
import time
from mica_shared.quick_commands import APP_NAMES, parse_quick_command
from desktop.core.local_state import read_json, write_json
import re


@dataclass
class WorkRoutine:
    enabled: bool = False
    apps: list[str] = field(default_factory=list)
    focus_minutes: int = 25
    quiet_minutes: int = 25
    documents: list[str] = field(default_factory=list)
    pause_minutes: int = 0

    def validate(self):
        if type(self.pause_minutes) is not int or not 0 <= self.pause_minutes <= 1440:
            raise ValueError('Die anschließende Pause muss zwischen 0 und 1440 Minuten liegen.')
        if type(self.enabled) is not bool or not isinstance(self.apps, list) or len(self.apps) > 8:
            raise ValueError("Ungültiger Arbeitsmodus.")
        if any(not isinstance(app, str) or app not in APP_NAMES for app in self.apps) or len(set(self.apps)) != len(self.apps):
            raise ValueError("Bitte eindeutige Programme aus der Auswahl verwenden.")
        identities = ["vscode" if APP_NAMES[app] == "visual studio code" else APP_NAMES[app] for app in self.apps]
        if len(set(identities)) != len(identities):
            raise ValueError("Dasselbe Programm darf nur einmal im Ablauf stehen.")
        for minutes in (self.focus_minutes, self.quiet_minutes):
            if type(minutes) is not int or not 1 <= minutes <= 1440:
                raise ValueError("Die Dauer muss zwischen 1 und 1440 Minuten liegen.")
        if (not isinstance(self.documents, list) or len(self.documents) > 8
            or any(not isinstance(path, str) or not path.strip() or len(path) > 1024 or not Path(path).is_absolute() for path in self.documents)
            or len(set(self.documents)) != len(self.documents)):
            raise ValueError('Bitte höchstens acht unterschiedliche lokale Dateien auswählen.')
        return self


class WorkRoutineStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(__file__).resolve().parents[2] / ".mica-data" / "work-routine.json"

    @staticmethod
    def valid_name(name):
        if not isinstance(name, str) or not re.fullmatch(r'[\wäöüÄÖÜß][\wäöüÄÖÜß -]{0,49}', name.strip()):
            raise ValueError('Bitte einen Namen mit höchstens 50 Buchstaben, Ziffern, Leerzeichen oder Bindestrichen verwenden.')
        return name.strip().casefold()

    def all(self):
        try:
            data = read_json(self.path, limit=262144)
        except FileNotFoundError:
            return {}
        if not isinstance(data, dict):
            raise ValueError('Ungültige Ablaufkonfiguration.')
        if 'version' not in data:
            return {'work': WorkRoutine(**data).validate()}
        if data['version'] != 2 or not isinstance(data.get('routines'), dict) or len(data['routines']) > 20:
            raise ValueError('Ungültige Ablaufkonfiguration.')
        result = {}
        for name, value in data['routines'].items():
            key = self.valid_name(name)
            if key in result:
                raise ValueError('Doppelter Ablaufname.')
            result[key] = WorkRoutine(**value).validate()
        return result

    def load(self, name='work'):
        try:
            return self.all().get(self.valid_name(name), WorkRoutine())
        except (OSError, ValueError, TypeError):
            return WorkRoutine()

    def save(self, routine, name='work'):
        routine.validate()
        records = self.all()
        name = self.valid_name(name)
        if name not in records and len(records) >= 20:
            raise ValueError('Höchstens 20 Abläufe speichern.')
        records[name] = routine
        write_json(self.path, {'version': 2, 'routines': {key: asdict(value) for key, value in records.items()}})

    def delete(self, name):
        records = self.all()
        records.pop(self.valid_name(name), None)
        write_json(self.path, {'version': 2, 'routines': {key: asdict(value) for key, value in records.items()}})


class QuietPeriod:
    """Mica-local pause of wake listening and unsolicited timer popups."""
    def __init__(self, *, clock=time.monotonic):
        self.clock, self.until = clock, 0
        self._lock = threading.Lock()

    @property
    def active(self):
        with self._lock:
            return self.clock() < self.until

    def begin(self, minutes):
        if type(minutes) is not int or not 1 <= minutes <= 1440:
            raise ValueError("Ungültige Ruhezeit.")
        with self._lock:
            self.until = self.clock() + minutes * 60

    def end(self):
        with self._lock:
            self.until = 0


class RoutineRunner:
    def __init__(self, store, commands, quiet, on_quiet_change=lambda: None, *, prepare_documents=None, apply_documents=None):
        self.store, self.commands, self.quiet = store, commands, quiet
        self.on_quiet_change = on_quiet_change
        self.prepare_documents, self.apply_documents = prepare_documents, apply_documents
        self._lock = threading.Lock()

    def run(self, *, name='work', cancelled=None):
        if not self._lock.acquire(blocking=False):
            return "Der Arbeitsmodus wird bereits gestartet."
        try:
            routine = self.store.load(name)
            if not routine.enabled:
                return "Bitte Arbeitsmodus zuerst über den Knopf Abläufe festlegen und speichern."
            documents = None
            if routine.documents and not self.prepare_documents:
                return 'Ablauf angehalten: Dokumentauswahl ist in dieser Oberfläche nicht verfügbar.'
            if self.prepare_documents:
                try:
                    documents = self.prepare_documents(routine.documents)
                except (OSError, ValueError) as error:
                    return 'Ablauf angehalten: Eine konfigurierte Datei konnte nicht gelesen werden. ' + str(error)
            results = []
            for app in routine.apps:
                if cancelled is not None and cancelled.is_set():
                    return "Arbeitsmodus abgebrochen. Bereits geöffnete Programme bleiben geöffnet."
                message = f"Öffne {app}"
                command = parse_quick_command(message)
                reply = self.commands.execute(command, message, cancelled=cancelled)
                results.append(reply)
                if reply != f"{command['label']} geöffnet.":
                    return "Arbeitsmodus angehalten: " + " ".join(results) + " Fokus-Timer und Ruhezeit wurden nicht gestartet."
            if cancelled is not None and cancelled.is_set():
                return "Arbeitsmodus abgebrochen."
            if documents is not None:
                if not self.apply_documents:
                    return 'Ablauf angehalten: Dokumentauswahl konnte nicht übernommen werden.'
                self.apply_documents(documents)
            timer = self.commands.timers.start(routine.focus_minutes * 60, followup_seconds=routine.pause_minutes * 60) if routine.pause_minutes else self.commands.timers.start(routine.focus_minutes * 60)
            if "gestartet" not in timer:
                return "Arbeitsmodus angehalten: " + timer
            self.quiet.begin(routine.quiet_minutes)
            self.on_quiet_change()
            return "Arbeitsmodus gestartet. " + " ".join(results) + f" {timer} Mica-Ruhezeit für {routine.quiet_minutes} Minuten aktiv." + (f' Danach beginnt eine Pause von {routine.pause_minutes} Minuten.' if routine.pause_minutes else '')
        finally:
            self._lock.release()
