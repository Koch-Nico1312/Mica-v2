"""Controlled external test window; never reads a user's application window."""
import ctypes
from ctypes import wintypes as wt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
TEXT = 'MICA kontrollierte Textauswahl: Docker startet lokal.'


def target(path):
    from PyQt6.QtWidgets import QApplication, QPlainTextEdit
    from PyQt6.QtCore import QTimer
    app = QApplication([])
    edit = QPlainTextEdit(TEXT)
    edit.setWindowTitle('MICA controlled selection acceptance')
    edit.resize(500, 240)
    edit.show()
    edit.selectAll()
    edit.setFocus()
    Path(path).write_text(json.dumps({'hwnd': int(edit.winId()), 'pid': os.getpid()}))
    QTimer.singleShot(20000, app.quit)
    app.exec()


def check():
    from PyQt6.QtWidgets import QApplication, QWidget
    from PyQt6.QtCore import QMimeData
    from desktop.core.text_selection import SelectionCapture, SelectionShortcut
    from desktop.core.window_observation import WindowsObservation
    app = QApplication([])
    dispatcher_window = QWidget()
    dispatcher_window.winId()
    observer = WindowsObservation()
    previous = observer.user.GetForegroundWindow()
    observer.user.SetForegroundWindow.argtypes = [wt.HWND]
    shortcut, capture = SelectionShortcut(), SelectionCapture()
    replies, errors, triggers = [], [], []
    capture.selected.connect(replies.append)
    capture.failed.connect(errors.append)
    def triggered():
        triggers.append(True)
        capture.capture()
    shortcut.triggered.connect(triggered)
    active = shortcut.enable()
    clipboard = app.clipboard()
    previous_clipboard = QMimeData()
    original = clipboard.mimeData()
    for format_name in original.formats():
        previous_clipboard.setData(format_name, original.data(format_name))
    sentinel = 'MICA clipboard preservation sentinel'
    with tempfile.TemporaryDirectory(prefix='mica-selection-acceptance-') as directory:
        ready = Path(directory) / 'ready.json'
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--target', str(ready)],
                                   cwd=ROOT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.02)
            data = json.loads(ready.read_text())
            clipboard.setText(sentinel)
            observer.user.SetForegroundWindow(data['hwnd'])
            time.sleep(.15)
            if observer.foreground()['pid'] != data['pid']:
                current_thread = observer.kernel.GetCurrentThreadId()
                foreground_thread = observer.user.GetWindowThreadProcessId(observer.user.GetForegroundWindow(), None)
                observer.user.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
                attached = observer.user.AttachThreadInput(current_thread, foreground_thread, True)
                try:
                    observer.user.SetForegroundWindow(data['hwnd'])
                finally:
                    if attached:
                        observer.user.AttachThreadInput(current_thread, foreground_thread, False)
                time.sleep(.15)
            assert observer.foreground()['pid'] == data['pid'], 'controlled target did not gain focus'
            assert active, 'no selection shortcut available'
            user = observer.user
            user.keybd_event.argtypes = [wt.BYTE, wt.BYTE, wt.DWORD, ctypes.c_size_t]
            keys = [0x11, 0x12] + ([0x10] if 'Umschalt' in shortcut.label else []) + [ord('M')]
            for key in keys:
                user.keybd_event(key, 0, 0, 0)
                time.sleep(.03)
            for key in reversed(keys):
                user.keybd_event(key, 0, 2, 0)
                time.sleep(.03)
            deadline = time.monotonic() + 9
            while not replies and not errors and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
            result = {'shortcut': shortcut.label, 'registered': active, 'global_event_received': bool(triggers),
                      'selected_test_text_matches': replies == [TEXT], 'clipboard_preserved': clipboard.text() == sentinel,
                      'errors': errors, 'read_only_controlled_test_window': True}
            (Path(__file__).parent / 'windows-runtime.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(result, ensure_ascii=False))
            assert result['global_event_received'] and result['selected_test_text_matches'] and result['clipboard_preserved'], result
        finally:
            shortcut.enable(False)
            process.terminate()
            process.wait(timeout=5)
            clipboard.setMimeData(previous_clipboard)
            observer.user.SetForegroundWindow(previous)


if __name__ == '__main__':
    target(sys.argv[2]) if len(sys.argv) > 1 and sys.argv[1] == '--target' else check()
