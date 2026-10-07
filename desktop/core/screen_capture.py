"""Isolated native PrintWindow capture; caller imposes a process timeout."""
from __future__ import annotations
import ctypes
from ctypes import wintypes as wt
from desktop.core.window_observation import WindowsObservation


class BitmapHeader(ctypes.Structure):
    _fields_ = [("size", wt.DWORD), ("width", wt.LONG), ("height", wt.LONG),
                ("planes", wt.WORD), ("bits", wt.WORD), ("compression", wt.DWORD),
                ("image_size", wt.DWORD), ("xppm", wt.LONG), ("yppm", wt.LONG),
                ("used", wt.DWORD), ("important", wt.DWORD)]


def capture_native(hwnd, pid):
    from PyQt6.QtGui import QImage
    observation = WindowsObservation()
    info = observation.info(hwnd)
    if not info or info["pid"] != pid or info["minimized"]:
        raise ValueError("Das ausgewählte Fenster ist geschlossen oder minimiert.")
    left, top, right, bottom = info["rect"]
    width, height = right - left, bottom - top
    if not 1 <= width <= 4096 or not 1 <= height <= 4096 or width * height > 12000000:
        raise ValueError("Das Fenster ist für die Texterkennung zu groß. Bitte verkleinern.")
    user, gdi = observation.user, ctypes.WinDLL("gdi32", use_last_error=True)
    signatures = [
        (user, "GetWindowDC", [wt.HWND], wt.HDC),
        (user, "ReleaseDC", [wt.HWND, wt.HDC], ctypes.c_int),
        (user, "PrintWindow", [wt.HWND, wt.HDC, wt.UINT], wt.BOOL),
        (gdi, "CreateCompatibleDC", [wt.HDC], wt.HDC),
        (gdi, "CreateCompatibleBitmap", [wt.HDC, ctypes.c_int, ctypes.c_int], wt.HBITMAP),
        (gdi, "SelectObject", [wt.HDC, wt.HANDLE], wt.HANDLE),
        (gdi, "DeleteObject", [wt.HANDLE], wt.BOOL),
        (gdi, "DeleteDC", [wt.HDC], wt.BOOL),
        (gdi, "GetDIBits", [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, wt.LPVOID, ctypes.POINTER(BitmapHeader), wt.UINT], ctypes.c_int),
    ]
    for library, name, args, result in signatures:
        function = getattr(library, name)
        function.argtypes, function.restype = args, result
    dc, memory, bitmap, previous = None, None, None, None
    try:
        dc = user.GetWindowDC(hwnd)
        if not dc:
            raise OSError("Fensteraufnahme nicht verfügbar.")
        memory = gdi.CreateCompatibleDC(dc)
        bitmap = gdi.CreateCompatibleBitmap(dc, width, height)
        if not memory or not bitmap:
            raise OSError("Fensteraufnahme konnte nicht vorbereitet werden.")
        previous = gdi.SelectObject(memory, bitmap)
        if not user.PrintWindow(hwnd, memory, 2):
            raise OSError("Dieses Fenster unterstützt die Aufnahme nicht.")
        gdi.SelectObject(memory, previous)
        previous = None
        header = BitmapHeader(ctypes.sizeof(BitmapHeader), width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0)
        buffer = ctypes.create_string_buffer(width * height * 4)
        if gdi.GetDIBits(dc, bitmap, 0, height, buffer, ctypes.byref(header), 0) != height:
            raise OSError("Fensterbild konnte nicht gelesen werden.")
        image = QImage(buffer.raw, width, height, width * 4, QImage.Format.Format_RGB32).copy()
        if image.isNull():
            raise OSError("Leere Fensteraufnahme.")
        return image
    finally:
        if previous and memory:
            gdi.SelectObject(memory, previous)
        if bitmap:
            gdi.DeleteObject(bitmap)
        if memory:
            gdi.DeleteDC(memory)
        if dc:
            user.ReleaseDC(hwnd, dc)


if __name__ == "__main__":
    import base64
    import sys
    from PyQt6.QtCore import QByteArray, QBuffer, QIODevice
    try:
        image = capture_native(int(sys.argv[1]), int(sys.argv[2]))
        data = QByteArray()
        stream = QBuffer(data)
        stream.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(stream, "PNG"):
            raise ValueError("Fensterbild konnte nicht kodiert werden.")
        sys.stdout.write(base64.b64encode(bytes(data)).decode("ascii"))
    except Exception:
        sys.stderr.write("Fensteraufnahme fehlgeschlagen. Das Fenster muss geöffnet sein und Aufnahmen unterstützen.")
        sys.exit(1)
