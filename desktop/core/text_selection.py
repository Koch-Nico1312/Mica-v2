"""Explicit global shortcut; bounded selection capture with clipboard recovery."""
import ctypes
from ctypes import wintypes as wt
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from PyQt6.QtCore import QObject, QAbstractNativeEventFilter, QCoreApplication, QMimeData, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication
from desktop.core.window_observation import WindowsObservation


class _ShortcutFilter(QAbstractNativeEventFilter):
    def __init__(self, shortcut):
        super().__init__()
        self.shortcut = shortcut

    def nativeEventFilter(self, event_type, message):
        packet = wt.MSG.from_address(int(message))
        if packet.message == 0x0312 and packet.wParam == self.shortcut.identifier:
            self.shortcut.triggered.emit()
            return True, 0
        return False, 0


class SelectionShortcut(QObject):
    triggered = pyqtSignal()
    identifier = 0x4D49

    def __init__(self, parent=None):
        super().__init__(parent)
        self.filter = _ShortcutFilter(self)
        self.active = False
        self.label = 'Strg+Alt+M'
        self.user = ctypes.WinDLL('user32', use_last_error=True) if os.name == 'nt' else None

    def enable(self, enabled=True):
        if not self.user or QApplication.platformName() == 'offscreen':
            return False
        self.user.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
        self.user.RegisterHotKey.restype = wt.BOOL
        self.user.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
        if self.active:
            self.user.UnregisterHotKey(None, self.identifier)
            QCoreApplication.instance().removeNativeEventFilter(self.filter)
            self.active = False
        if enabled:
            self.active = bool(self.user.RegisterHotKey(None, self.identifier, 0x4003, ord('M')))
            self.label = 'Strg+Alt+M'
            if not self.active:
                self.active = bool(self.user.RegisterHotKey(None, self.identifier, 0x4007, ord('M')))
                self.label = 'Strg+Alt+Umschalt+M'
            if self.active:
                QCoreApplication.instance().installNativeEventFilter(self.filter)
        return self.active

class SelectionCapture(QObject):
    selected = pyqtSignal(str)
    failed = pyqtSignal(str)
    _read = pyqtSignal(dict, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False
        self._read.connect(self._after_read)
        self.poll = QTimer(self)
        self.poll.setInterval(30)
        self.poll.timeout.connect(self._copy_tick)

    def capture(self):
        if self.busy:
            return
        try:
            self.observer = WindowsObservation()
            target = self.observer.foreground()
            if not target or target['pid'] == os.getpid():
                raise ValueError('Bitte Text in der gewünschten Anwendung markieren und dort Strg+Alt+M drücken.')
        except (OSError, ValueError) as error:
            self.failed.emit(str(error))
            return
        self.busy = True
        def worker():
            try:
                powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
                output = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-File',
                    str(Path(__file__).with_name('selection_reader.ps1')), '-WindowHandle', str(target['hwnd']),
                    '-ProcessId', str(target['pid'])], capture_output=True, timeout=5, encoding='utf-8',
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                result = json.loads(output.stdout) if output.returncode == 0 else {'status': 'unsupported'}
            except (OSError, ValueError, subprocess.TimeoutExpired):
                result = {'status': 'unsupported'}
            self._read.emit(target, result)
        threading.Thread(target=worker, name='mica-selected-text', daemon=True).start()

    def _after_read(self, target, result):
        current = self.observer.foreground()
        if not current or (current['hwnd'], current['pid']) != (target['hwnd'], target['pid']):
            self._finish(error='Das aktive Fenster hat gewechselt. Bitte das Tastenkürzel erneut im gewünschten Fenster drücken.')
            return
        status = result.get('status')
        if status == 'selected':
            self._finish(text=result.get('text', ''))
        elif status == 'unsupported':
            # Generic copy fallback only in the unchanged foreground window.
            self.target = target
            self.copy_until = time.monotonic() + 2
            self.copy_sent = False
            self.original_mime = None
            self.poll.start()
        else:
            self._finish(error={'password': 'Passwortfelder werden nicht gelesen.', 'too_large': 'Bitte höchstens 16.000 Zeichen markieren.'}.get(status, 'Kein markierter Text erkannt.'))

    def _copy_tick(self):
        user = self.observer.user
        user.GetClipboardSequenceNumber.restype = wt.DWORD
        user.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user.GetAsyncKeyState.restype = ctypes.c_short
        current = self.observer.foreground()
        if not current or (current['hwnd'], current['pid']) != (self.target['hwnd'], self.target['pid']):
            self._finish(error='Das aktive Fenster hat gewechselt; Auswahl nicht übernommen.')
            return
        if time.monotonic() >= self.copy_until:
            self._finish(error='Die Anwendung hat keinen kopierbaren markierten Text bereitgestellt.')
            return
        clipboard = QApplication.clipboard()
        if not self.copy_sent:
            if any(user.GetAsyncKeyState(key) & 0x8000 for key in (0x10, 0x11, 0x12, ord('M'))):
                return
            self.original_mime = QMimeData()
            mime = clipboard.mimeData()
            for fmt in mime.formats():
                self.original_mime.setData(fmt, mime.data(fmt))
            self.sequence = user.GetClipboardSequenceNumber()
            user.keybd_event.argtypes = [wt.BYTE, wt.BYTE, wt.DWORD, ctypes.c_size_t]
            for key, flag in ((0x11, 0), (ord('C'), 0), (ord('C'), 2), (0x11, 2)):
                user.keybd_event(key, 0, flag, 0)
            self.copy_sent = True
        elif user.GetClipboardSequenceNumber() != self.sequence:
            text = clipboard.text()
            # Clipboard and UI are on this thread; no event loop interleaving here.
            clipboard.setMimeData(self.original_mime)
            self.original_mime = None
            self._finish(text=text)

    def _finish(self, text='', error=''):
        self.poll.stop()
        self.busy = False
        if error or not text.strip() or len(text) > 16000:
            self.failed.emit(error or ('Bitte höchstens 16.000 Zeichen markieren.' if len(text) > 16000 else 'Kein markierter Text erkannt.'))
        else:
            self.selected.emit(text)
