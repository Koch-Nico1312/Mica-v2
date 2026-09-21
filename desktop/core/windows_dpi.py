"""Windows/Qt DPI startup coordination.

Qt 6 normally selects Per-Monitor-V2 itself.  Some launchers and imported
Windows components set the process DPI context earlier, in which case Qt's
second SetProcessDpiAwarenessContext call is rejected with ERROR_ACCESS_DENIED.
When an awareness context already exists, tell the Qt Windows plugin not to
set it again; the existing Windows context remains in force.
"""

from __future__ import annotations

import ctypes
import os
import platform


def process_already_dpi_aware() -> bool:
    """Return True when Windows reports a non-unaware context for this thread."""
    if platform.system() != "Windows":
        return False
    try:
        user32 = ctypes.windll.user32
        context = user32.GetThreadDpiAwarenessContext()
        awareness = user32.GetAwarenessFromDpiAwarenessContext(context)
        return int(awareness) > 0
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def configure_qt_dpi_startup() -> bool:
    """Avoid Qt's duplicate DPI setter while preserving an existing context.

    Returns True only when this function changed ``QT_QPA_PLATFORM``.  An
    explicit user/platform choice is never overwritten.
    """
    if not process_already_dpi_aware() or os.environ.get("QT_QPA_PLATFORM"):
        return False
    os.environ["QT_QPA_PLATFORM"] = "windows:dpiawareness=0"
    return True
