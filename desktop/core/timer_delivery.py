"""Windows scheduled timer delivery; the durable timer record is authoritative."""
from __future__ import annotations
import argparse
import math
from datetime import datetime, UTC
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from xml.etree import ElementTree as ET
from desktop.core.local_state import FileLease, read_json, write_json


class WindowsTimerDelivery:
    def __init__(self, path, *, run=subprocess.run):
        self.path, self.run = Path(path).resolve(), run

    @staticmethod
    def task_name(identifier):
        if not re.fullmatch(r'[a-f0-9]{32}', identifier):
            raise ValueError('Ungültige Timerkennung.')
        return 'MICA-Timer-' + identifier

    def schedule(self, identifier, deadline):
        if os.name != 'nt':
            raise OSError('Timerzustellung bei geschlossener Oberfläche benötigt Windows.')
        namespace = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
        ET.register_namespace('', namespace)
        root = ET.Element('{' + namespace + '}Task', version='1.2')
        def add(parent, name, value=None):
            element = ET.SubElement(parent, '{' + namespace + '}' + name)
            if value is not None:
                element.text = str(value)
            return element
        info = add(root, 'RegistrationInfo')
        add(info, 'Description', 'Lokaler MICA-Timer; Zustellung nur für einen noch aktiven Timer.')
        triggers = add(root, 'Triggers')
        trigger = add(triggers, 'TimeTrigger')
        add(trigger, 'StartBoundary', datetime.fromtimestamp(math.ceil(deadline), UTC).isoformat(timespec='seconds'))
        add(trigger, 'Enabled', 'true')
        principals = add(root, 'Principals')
        principal = add(principals, 'Principal')
        add(principal, 'LogonType', 'InteractiveToken')
        add(principal, 'RunLevel', 'LeastPrivilege')
        settings = add(root, 'Settings')
        for name, value in [('MultipleInstancesPolicy', 'IgnoreNew'), ('DisallowStartIfOnBatteries', 'false'),
                ('StopIfGoingOnBatteries', 'false'), ('StartWhenAvailable', 'true'),
                ('ExecutionTimeLimit', 'PT2M'), ('Enabled', 'true')]:
            add(settings, name, value)
        actions = add(root, 'Actions')
        action = add(actions, 'Exec')
        python = Path(sys.executable)
        if python.with_name('pythonw.exe').exists():
            python = python.with_name('pythonw.exe')
        add(action, 'Command', str(python))
        args = ['-m', 'desktop.core.timer_delivery', '--path', str(self.path), '--id', identifier, '--deadline', str(deadline)]
        add(action, 'Arguments', subprocess.list2cmdline(args))
        add(action, 'WorkingDirectory', str(Path(__file__).resolve().parents[2]))
        with tempfile.TemporaryDirectory(prefix='mica-timer-task-') as directory:
            xml_path = Path(directory) / 'task.xml'
            xml_path.write_bytes(ET.tostring(root, encoding='utf-16', xml_declaration=True))
            output = self.run(['schtasks.exe', '/Create', '/TN', self.task_name(identifier), '/XML', str(xml_path), '/F'],
                capture_output=True, timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if output.returncode:
            raise OSError('Windows konnte die Timerzustellung nicht registrieren. Bitte Aufgabenplanung prüfen.')

    def cancel(self, identifier):
        try:
            self.run(['schtasks.exe', '/Delete', '/TN', self.task_name(identifier), '/F'],
                capture_output=True, timeout=8, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired):
            pass  # No valid timer record means an obsolete task cannot notify.

    def run_due(self, identifier):
        output = self.run(['schtasks.exe', '/Run', '/TN', self.task_name(identifier)],
            capture_output=True, timeout=8, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if output.returncode:
            raise OSError('Windows konnte den abgelaufenen Timer nicht starten.')


def claim_delivery(path, identifier, deadline, *, now=time.time, with_record=False):
    """Mutually exclusive with the desktop owner; stale/cancelled tasks are inert."""
    lease = FileLease(str(path) + '.lock')
    try:
        data = read_json(path, limit=262144)
        if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('timers'), list):
            raise ValueError('Ungültige Timerdatei.')
        if any(not isinstance(item, dict) for item in data['timers']) or len(data['timers']) > 72:
            raise ValueError('Ungültige Timerdatei.')
        record = next((item for item in data['timers'] if item.get('id') == identifier and item.get('deadline') == deadline), None)
        if record is None or deadline > now():
            return False
        task_id = record.get('task_id')
        if task_id is not None and (not isinstance(task_id, str) or not re.fullmatch(r'[a-f0-9]{32}', task_id)):
            raise ValueError('Ungültige Aufgabenkennung.')
        if not isinstance(record.get('label', ''), str) or len(record.get('label', '')) > 500:
            raise ValueError('Ungültiger Erinnerungstext.')
        if type(record.get('followup_seconds', 0)) is not int or not 0 <= record.get('followup_seconds', 0) <= 86400:
            raise ValueError('Ungültige Pausendauer.')
        data['timers'].remove(record)
        write_json(path, data)
        return record if with_record else True
    finally:
        lease.close()


def notify_timer():
    """A native visible notification, independent of Qt and model availability."""
    if os.name != 'nt':
        return False
    import ctypes
    import winsound
    try:
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except RuntimeError:
        pass
    # Native foreground message box is reliable without optional toast packages.
    return bool(ctypes.windll.user32.MessageBoxW(None, 'Dein MICA-Timer ist abgelaufen.', 'MICA · Timer', 0x40 | 0x1000))


def notify_record(path, record):
    from desktop.reminder_notification import show_standalone
    return show_standalone(record, path=path)


def deliver(path, identifier, deadline, *, notify=None, wait=time.sleep, now=time.time):
    # UI normally clears the record itself. Retry across its shutdown race.
    for _ in range(30):
        if deadline > now():
            wait(min(1, deadline - now()))
            continue
        try:
            record = claim_delivery(path, identifier, deadline, now=now, with_record=True)
            if record:
                followup = record.get('followup_seconds', 0)
                if type(followup) is not int or not 0 <= followup <= 86400:
                    raise ValueError('Ungültige Pausendauer.')
                if followup:
                    from desktop.core.native_commands import LocalTimers
                    timers = LocalTimers(lambda _: None, path=path, delivery=WindowsTimerDelivery(path))
                    try:
                        timers.start(followup, label='Pause beendet.')
                    finally:
                        timers.shutdown()
                return notify() if notify else notify_record(path, record)
            return False
        except FileNotFoundError:
            return False
        except ValueError as error:
            if 'anderen Mica' not in str(error):
                raise
            wait(1)
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--path', required=True)
    parser.add_argument('--id', required=True)
    parser.add_argument('--deadline', required=True, type=float)
    args = parser.parse_args()
    WindowsTimerDelivery.task_name(args.id)
    try:
        deliver(Path(args.path), args.id, args.deadline)
    finally:
        WindowsTimerDelivery(args.path).cancel(args.id)


if __name__ == '__main__':
    main()
