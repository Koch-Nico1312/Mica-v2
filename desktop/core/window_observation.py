"""Read-only native window observations; window titles never authorize actions."""
from __future__ import annotations
import ctypes
from ctypes import wintypes as wt
import os
import re
from pathlib import PureWindowsPath
import time

PROCESS_NAMES = {
    "notepad": {"notepad.exe"}, "calculator": {"calculatorapp.exe", "calculator.exe", "calc.exe"},
    "explorer": {"explorer.exe"}, "edge": {"msedge.exe"}, "chrome": {"chrome.exe"},
    "firefox": {"firefox.exe"}, "obsidian": {"obsidian.exe"}, "notion": {"notion.exe"},
    "spotify": {"spotify.exe"}, "discord": {"discord.exe"},
    "vscode": {"code.exe"}, "visual studio code": {"code.exe"},
    "ms-settings:": {"systemsettings.exe"},
}


class WindowsObservation:
    def __init__(self):
        if os.name != "nt":
            raise OSError("Fensterprüfung benötigt Windows.")
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.callback = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        signatures = [
            (self.user, "GetForegroundWindow", [], wt.HWND),
            (self.user, "GetWindowThreadProcessId", [wt.HWND, ctypes.POINTER(wt.DWORD)], wt.DWORD),
            (self.user, "IsWindowVisible", [wt.HWND], wt.BOOL),
            (self.user, "IsIconic", [wt.HWND], wt.BOOL),
            (self.user, "GetWindowTextW", [wt.HWND, wt.LPWSTR, ctypes.c_int], ctypes.c_int),
            (self.user, "GetWindowRect", [wt.HWND, ctypes.POINTER(wt.RECT)], wt.BOOL),
            (self.user, "EnumWindows", [self.callback, wt.LPARAM], wt.BOOL),
            (self.user, "EnumChildWindows", [wt.HWND, self.callback, wt.LPARAM], wt.BOOL),
            (self.kernel, "OpenProcess", [wt.DWORD, wt.BOOL, wt.DWORD], wt.HANDLE),
            (self.kernel, "QueryFullProcessImageNameW", [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)], wt.BOOL),
            (self.kernel, "CloseHandle", [wt.HANDLE], wt.BOOL),
        ]
        for library, name, args, result in signatures:
            function = getattr(library, name)
            function.argtypes, function.restype = args, result

    def info(self, hwnd):
        if not hwnd or not self.user.IsWindowVisible(hwnd):
            return None
        pid = wt.DWORD()
        if not self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
            return None
        handle = self.kernel.OpenProcess(0x1000, False, pid.value)
        executable = ""
        if handle:
            try:
                buffer, size = ctypes.create_unicode_buffer(32768), wt.DWORD(32768)
                if self.kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                    executable = PureWindowsPath(buffer.value).name.casefold()
            finally:
                self.kernel.CloseHandle(handle)
        title, rect = ctypes.create_unicode_buffer(1024), wt.RECT()
        self.user.GetWindowTextW(hwnd, title, len(title))
        if not self.user.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        return {"hwnd": int(hwnd), "pid": pid.value, "exe": executable, "title": title.value,
                "rect": (rect.left, rect.top, rect.right, rect.bottom), "minimized": bool(self.user.IsIconic(hwnd))}

    def foreground(self):
        return self.info(self.user.GetForegroundWindow())

    def windows(self):
        result = []
        def visit(hwnd, unused):
            info = self.info(hwnd)
            if info and info["title"]:
                result.append(info)
            return True
        callback = self.callback(visit)
        self.user.EnumWindows(callback, 0)
        return result

    def matches(self, app):
        expected = PROCESS_NAMES.get(app.casefold().removesuffix(".exe"), set())
        if not expected and re.fullmatch(r"[\w-]{1,80}(?:\.exe)?", app):
            expected = {app.casefold().removesuffix(".exe") + ".exe"}
        if not expected:
            return False
        for window in self.windows():
            if window.get("minimized"):
                continue
            if window["exe"] in expected:
                # Explorer also owns the shell/taskbar; only folder windows count.
                if app.casefold() == "explorer":
                    class_name = ctypes.create_unicode_buffer(256)
                    self.user.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
                    self.user.GetClassNameW.restype = ctypes.c_int
                    self.user.GetClassNameW(window["hwnd"], class_name, 256)
                    if class_name.value not in {"CabinetWClass", "ExploreWClass"}:
                        continue
                return True
            # Some packaged applications expose their window through a host.
            if window["exe"] == "applicationframehost.exe":
                found = []
                def child(hwnd, unused):
                    info = self.info(hwnd)
                    if info and info["exe"] in expected:
                        found.append(True)
                    return True
                callback = self.callback(child)
                self.user.EnumChildWindows(window["hwnd"], callback, 0)
                if found:
                    return True
        return False


def wait_for_app_window(app, *, timeout=12, cancelled=None, observer=None):
    try:
        observer = observer or WindowsObservation()
        deadline = time.monotonic() + timeout
        while True:
            if cancelled is not None and cancelled.is_set():
                return False
            if observer.matches(app):
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            if cancelled is not None:
                cancelled.wait(min(0.2, remaining))
            else:
                time.sleep(min(0.2, remaining))
    except OSError:
        return False
