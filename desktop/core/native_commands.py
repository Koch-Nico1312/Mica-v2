"""Model-free user commands; Windows changes still cross the Core policy gate."""
from __future__ import annotations
import math
import threading
import time
import uuid
from pathlib import Path
from desktop.core.local_state import read_json, write_json, FileLease
from mica_shared.quick_commands import parse_quick_command
from desktop.core.local_core_client import LocalCoreError
from desktop.core.window_observation import wait_for_app_window


class LocalTimers:
    """Timers with optional durable UTC deadlines, independent of inference."""
    def __init__(self, notify, *, clock=time.monotonic, wall_clock=time.time, path=None):
        self.notify, self.clock = notify, clock
        self.wall_clock, self.path = wall_clock, Path(path) if path else None
        self._items, self._lock = {}, threading.RLock()
        self._restored = False
        self._lease = None
        self._closed = False

    def _persist(self):
        if self.path:
            write_json(self.path, {'version': 1, 'timers': [
                {'id': key, 'deadline': item['deadline'], 'seconds': item['seconds']}
                for key, item in self._items.items()]})

    def _schedule(self, identifier, seconds, deadline):
        remaining = max(0, deadline - self.wall_clock())
        def elapsed():
            with self._lock:
                if self._closed or identifier not in self._items:
                    return
                item = self._items.pop(identifier)
                try:
                    self._persist()
                except OSError:
                    self._items[identifier] = item
                    self.notify('Timer abgelaufen, aber der gespeicherte Zustand konnte nicht aktualisiert werden. Bitte Speicherung prüfen.')
                    return
            self.notify('Timer abgelaufen.')
        timer = threading.Timer(remaining, elapsed)
        timer.daemon = True
        self._items[identifier] = {'timer': timer, 'until': self.clock() + remaining,
                                   'deadline': deadline, 'seconds': seconds}
        return timer

    def restore(self):
        with self._lock:
            if self._restored or not self.path:
                return
            if self._closed:
                raise ValueError('Timerverwaltung wurde beendet.')
            if self._lease is None:
                self._lease = FileLease(str(self.path) + '.lock')
            try:
                data = read_json(self.path, limit=8192)
            except FileNotFoundError:
                self._restored = True
                return
            if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('timers'), list) or len(data['timers']) > 8:
                raise ValueError('Gespeicherte Timer sind ungültig.')
            records = data['timers']
            ids = set()
            for item in records:
                if (not isinstance(item, dict) or not isinstance(item.get('id'), str) or len(item['id']) != 32
                    or item['id'] in ids or type(item.get('seconds')) is not int or not 1 <= item['seconds'] <= 86400
                    or type(item.get('deadline')) not in (int, float) or not math.isfinite(item['deadline'])
                    or item['deadline'] > self.wall_clock() + 86400):
                    raise ValueError('Gespeicherte Timer sind ungültig.')
                ids.add(item['id'])
            self._restored = True
            for item in records:
                self._schedule(item['id'], item['seconds'], item['deadline'])
            for item in list(self._items.values()):
                item['timer'].start()

    def shutdown(self):
        """Stop this process's callbacks; retain deadlines for the next start."""
        with self._lock:
            self._closed = True
            for item in self._items.values():
                item['timer'].cancel()
            if self._lease:
                self._lease.close()
                self._lease = None

    def start(self, seconds: int):
        if type(seconds) is not int or not 1 <= seconds <= 86400:
            raise ValueError("Timerdauer muss zwischen einer Sekunde und 24 Stunden liegen.")
        with self._lock:
            if self._closed:
                raise ValueError('Timerverwaltung wurde beendet.')
            if self.path and not self._restored:
                self.restore()
            if len(self._items) >= 8:
                return "Es laufen bereits acht Timer. Stoppe zuerst einen Timer."
            identifier = uuid.uuid4().hex
            timer = self._schedule(identifier, seconds, self.wall_clock() + seconds)
            try:
                self._persist()
            except OSError:
                del self._items[identifier]
                raise
            timer.start()
        amount = seconds // 60 if seconds % 60 == 0 else seconds
        unit_name = ("Minute" if amount == 1 else "Minuten") if seconds % 60 == 0 else ("Sekunde" if amount == 1 else "Sekunden")
        unit = f"{amount} {unit_name}"
        return f"Timer für {unit} gestartet."

    def correct_latest(self, seconds, previous_seconds):
        # The explicit old duration prevents correcting an unrelated timer.
        with self._lock:
            if not self._items:
                return "Es läuft kein Timer, den ich ändern kann."
            identifier = next(reversed(self._items))
            if self._items[identifier]["seconds"] != previous_seconds:
                return "Die genannte alte Dauer passt nicht zum zuletzt gestarteten Timer. Bitte die Dauer prüfen."
            if type(seconds) is not int or not 1 <= seconds <= 86400:
                return "Die neue Dauer muss zwischen einer Sekunde und 24 Stunden liegen."
            old = self._items.pop(identifier)
            try:
                result = self.start(seconds).replace("gestartet", "ab jetzt neu gestartet")
            except OSError:
                self._items[identifier] = old
                raise
            old['timer'].cancel()
            return result

    def cancel_latest(self):
        with self._lock:
            if not self._items:
                return "Es läuft kein Timer."
            identifier = next(reversed(self._items))
            old = self._items.pop(identifier)
            try:
                self._persist()
            except OSError:
                self._items[identifier] = old
                raise
            old['timer'].cancel()
            return "Letzten Timer gestoppt."

    def status(self):
        with self._lock:
            seconds = [max(0, math.ceil(item["until"] - self.clock())) for item in self._items.values()]
        return "Es läuft kein Timer." if not seconds else "Verbleibende Sekunden: " + ", ".join(map(str, seconds)) + "."

    def cancel_all(self):
        with self._lock:
            old = self._items
            self._items = {}
            try:
                self._persist()
            except OSError:
                self._items = old
                raise
            for item in old.values():
                item["timer"].cancel()


class NativeCommands:
    def __init__(self, client, timers, *, verify_window=wait_for_app_window, routine_handler=None, quiet_end=None, workspace_handler=None, preference_handler=None):
        self.client, self.timers = client, timers
        self.verify_window = verify_window
        self.routine_handler, self.quiet_end = routine_handler, quiet_end
        self.workspace_handler = workspace_handler
        self.preference_handler = preference_handler

    def execute(self, command: dict, original: str, *, cancelled=None) -> str:
        # The server's/model's parameter object cannot extend the exact grammar.
        if command != parse_quick_command(original):
            return "Der Befehl passt nicht zur gesprochenen Anfrage und wurde nicht ausgeführt."
        if cancelled is not None and cancelled.is_set():
            return "Befehl abgebrochen."
        kind = command["kind"]
        if kind == 'day_overview':
            from desktop.core.day_overview import desktop_day_overview
            return desktop_day_overview(self.client)
        if kind == 'preference_offer':
            return self.preference_handler(command) if self.preference_handler else 'Diese Vorliebe kannst du unter Weiterentwicklung bestätigen.'
        if kind in {'workspace_save', 'workspace_resume'}:
            return self.workspace_handler(kind) if self.workspace_handler else 'Arbeitsstände sind in dieser Oberfläche nicht eingerichtet.'
        if kind == "routine":
            return self.routine_handler(name=command['name'], cancelled=cancelled) if self.routine_handler else "Arbeitsmodus ist in dieser Oberfläche nicht eingerichtet."
        if kind == "quiet_end":
            if self.quiet_end:
                self.quiet_end()
                return "Mica-Ruhezeit beendet. Bereits geöffnete Programme und Timer laufen weiter."
            return "Es ist keine Mica-Ruhezeit eingerichtet."
        if kind == "timer":
            return self.timers.start(command["seconds"])
        if kind == "timer_cancel":
            return self.timers.cancel_latest()
        if kind == "timer_status":
            return self.timers.status()
        if kind == "timer_correct":
            return self.timers.correct_latest(command["seconds"], command["previous_seconds"])
        if kind == "volume":
            action, params = "computer_settings", {key: value for key, value in command.items() if key != "kind"}
            success = (f"Lautstärke auf {command['value']} Prozent gesetzt." if "value" in command
                       else {"volume_up": "Lautstärke erhöht.", "volume_down": "Lautstärke reduziert.", "mute": "Ton umgeschaltet."}[command["action"]])
        elif kind == "app":
            action, params, success = "open_app", {"app_name": command["app_name"]}, f"{command['label']} geöffnet."
        elif kind == "reminder":
            action, params = "reminder", {key: value for key, value in command.items() if key != "kind"}
            success = f"Erinnerung für {command['date']} um {command['time']} gespeichert."
        else:
            return "Dieser lokale Befehl wird nicht unterstützt."
        try:
            plan = self.client.plan(original, action, params, dry_run=False)["plan"]
            if cancelled is not None and cancelled.is_set():
                return "Befehl abgebrochen."
            result = self.client.execute(plan["task_id"], action, params,
                                         approval_id=plan.get("permission", {}).get("approval_id"),
                                         idempotency_key="quick:" + plan["task_id"])
        except LocalCoreError as error:
            if error.status_code == 403:
                return "Der Befehl wartet auf deine Freigabe unter Betrieb. Danach die Ausführung fortsetzen."
            return "Der lokale Befehl konnte nicht abgeschlossen werden. Bitte die Diagnose unter Betrieb prüfen."
        output = result.get("output")
        # Legacy adapter error strings must never become a success confirmation.
        if result.get("status") not in {"succeeded", "completed"} or (isinstance(output, str) and output.startswith(
            ("Could not", "Failed", "I couldn't", "Something went wrong", "pyautogui", "No application", "Unsupported"))):
            return "Der lokale Befehl wurde nicht erfolgreich abgeschlossen. Bitte Betrieb prüfen."
        if kind == "app" and not self.verify_window(command["app_name"], cancelled=cancelled):
            return f"Start angefordert; ein Fenster von {command['label']} konnte ich nicht bestätigen."
        return success
