"""Observe and snooze a real independent notification with disposable state."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from desktop.core.native_commands import LocalTimers
    from desktop.core.timer_delivery import WindowsTimerDelivery
    from desktop.core.window_observation import WindowsObservation
    from desktop.core.window_controls import read_window_controls
    with tempfile.TemporaryDirectory(prefix='mica-actionable-reminder-') as directory:
        path = Path(directory) / 'timers.json'
        delivery = WindowsTimerDelivery(path)
        timers = LocalTimers(lambda _: None, path=path, delivery=delivery)
        timers.start(5)
        original = next(iter(timers._items))
        timers.shutdown()
        observer, found, identifiers = WindowsObservation(), None, {original}
        try:
            deadline = time.monotonic() + 50
            while time.monotonic() < deadline and found is None:
                for window in observer.windows():
                    if window['title'] != 'MICA · Timer':
                        continue
                    try:
                        arguments = psutil.Process(window['pid']).cmdline()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                    if original in arguments and 'desktop.core.timer_delivery' in arguments:
                        found = window
                        break
                if found is None:
                    time.sleep(.2)
            assert found, 'Scheduled notification did not appear.'
            controls = read_window_controls(found)
            assert 'Erledigt' in controls['text'] and '10 Minuten später' in controls['text']
            powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-File',
                str(ROOT / 'scripts/invoke_assistance_test_button.ps1'), '-WindowHandle', str(found['hwnd']),
                '-ProcessId', str(found['pid']), '-TimerId', original], capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW)
            assert result.returncode == 0, result.stderr.decode(errors='replace')
            deadline = time.monotonic() + 15
            records = []
            while time.monotonic() < deadline:
                records = json.loads(path.read_text())['timers']
                if records:
                    break
                time.sleep(.1)
            assert len(records) == 1 and records[0]['seconds'] == 600
            assert 570 <= records[0]['deadline'] - time.time() <= 600
            identifiers.add(records[0]['id'])
            queried = subprocess.run(['schtasks.exe', '/Query', '/TN', delivery.task_name(records[0]['id'])], capture_output=True, timeout=8,
                creationflags=subprocess.CREATE_NO_WINDOW)
            assert queried.returncode == 0, 'Snoozed reminder has no scheduled task.'
            print(json.dumps({'closed_desktop_actions_visible': True, 'real_snooze_click': True,
                'durable_600_second_reminder': True, 'windows_task_registered': True, 'production_data_touched': False}))
        finally:
            if found:
                observer.user.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
                observer.user.PostMessageW(found['hwnd'], 0x0010, 0, 0)
            try:
                identifiers.update(item['id'] for item in json.loads(path.read_text())['timers'])
            except (OSError, ValueError):
                pass
            for identifier in identifiers:
                delivery.cancel(identifier)


if __name__ == '__main__':
    main()
