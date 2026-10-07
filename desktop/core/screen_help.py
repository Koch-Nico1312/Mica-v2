"""Track only foreground metadata; capture once after an explicit button click."""
from __future__ import annotations
import base64
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QImage
from desktop.core.window_observation import WindowsObservation


def capture_target(target):
    result = subprocess.run([sys.executable, "-m", "desktop.core.screen_capture", str(target["hwnd"]), str(target["pid"])],
                            cwd=Path(__file__).resolve().parents[2], capture_output=True, timeout=8,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode or len(result.stdout) > 64 * 1024 * 1024:
        raise ValueError("Fenster konnte nicht erfasst werden. Bitte das Fenster öffnen; geschützte Inhalte können nicht gelesen werden.")
    image = QImage.fromData(base64.b64decode(result.stdout, validate=True), "PNG")
    if image.isNull():
        raise ValueError("Fensteraufnahme ist leer.")
    return image


class ForegroundTracker(QObject):
    captured = pyqtSignal(dict, object)
    failed = pyqtSignal(str)

    def __init__(self, parent=None, *, observer=None, capture=capture_target, clock=time.monotonic):
        super().__init__(parent)
        try:
            self.observer = observer or WindowsObservation()
        except OSError:
            self.observer = None
        self.capture_function, self.clock = capture, clock
        self.target, self.busy = None, False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(250)

    def poll(self):
        if not self.observer:
            return
        info = self.observer.foreground()
        if info and info["pid"] != os.getpid() and info["title"] and not info["minimized"]:
            self.target = {**info, "seen": self.clock()}

    def capture_async(self):
        if self.busy:
            return
        target = dict(self.target) if self.target else None
        if not target or self.clock() - target["seen"] > 300:
            self.failed.emit("Bitte zuerst das gewünschte Fenster aktivieren und danach Fensterhilfe anklicken.")
            return
        self.busy = True
        def worker():
            try:
                self.captured.emit(target, self.capture_function(target))
            except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                self.failed.emit("Fensteraufnahme nicht möglich: " + str(error))
            finally:
                self.busy = False
        threading.Thread(target=worker, name="mica-window-capture", daemon=True).start()
