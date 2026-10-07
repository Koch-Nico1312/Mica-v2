"""Exercise real UI Automation and scheduled delivery using disposable local data."""
from __future__ import annotations
import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import psutil
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    if os.name != 'nt':
        raise RuntimeError('Diese Laufzeitprüfung benötigt Windows.')
    from PyQt6.QtWidgets import QApplication, QDialog, QVBoxLayout, QPushButton, QLineEdit
    from desktop.core.window_controls import read_window_controls
    from desktop.core.timer_delivery import WindowsTimerDelivery
    from desktop.core.native_commands import LocalTimers
    from desktop.core.window_observation import WindowsObservation
    app = QApplication.instance() or QApplication([])
    window = QDialog()
    window.setWindowTitle('MICA · Fensterhilfe-Prüfung')
    layout = QVBoxLayout(window)
    layout.addWidget(QPushButton('MICA Prüfknopf Speichern'))
    password = QLineEdit('MICA_PASSWORD_MUST_NOT_APPEAR')
    password.setEchoMode(QLineEdit.EchoMode.Password)
    layout.addWidget(password)
    window.show()
    app.processEvents()
    try:
        target = {'hwnd': int(window.winId()), 'pid': os.getpid()}
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(read_window_controls, target)
            while not future.done():
                app.processEvents()
                time.sleep(.01)
            controls = future.result()
        assert controls['status'] == 'read', controls
        assert 'MICA Prüfknopf Speichern' in controls['text'], controls
        assert 'MICA_PASSWORD_MUST_NOT_APPEAR' not in controls['text'], controls
    finally:
        window.close()
        app.processEvents()
    with tempfile.TemporaryDirectory(prefix='mica-closed-timer-') as directory:
        path = Path(directory) / 'timers.json'
        delivery = WindowsTimerDelivery(path)
        callbacks = []
        timer = LocalTimers(callbacks.append, path=path, delivery=delivery)
        timer.start(5)
        identifier = next(iter(timer._items))
        timer.shutdown()  # No Qt timer and no desktop owner remains.
        observer = WindowsObservation()
        found = None
        try:
            limit = time.monotonic() + 50
            while time.monotonic() < limit:
                for item in observer.windows():
                    if item['title'] != 'MICA · Timer':
                        continue
                    try:
                        arguments = psutil.Process(item['pid']).cmdline()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                    if identifier in arguments and 'desktop.core.timer_delivery' in arguments:
                        found = item
                        break
                if found:
                    break
                time.sleep(.2)
            assert found, 'Die unabhängige Windows-Timerbenachrichtigung erschien nicht.'
            assert json.loads(path.read_text())['timers'] == [], 'Timer wurde nicht verbraucht.'
            assert callbacks == [], 'Der geschlossene Desktop darf keinen Callback auslösen.'
        finally:
            if found:
                observer.user.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
                observer.user.PostMessageW(found['hwnd'], 0x0010, 0, 0)  # Close this test's message box.
            delivery.cancel(identifier)
    print(json.dumps({'uia_visible_button': True, 'uia_password_excluded': True,
        'timer_after_desktop_shutdown': True, 'native_notification_observed': True,
        'timer_consumed_once': True, 'production_data_touched': False}))


if __name__ == '__main__':
    main()
