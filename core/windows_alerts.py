"""Best-effort local Windows notification for critical MICA failures."""
from __future__ import annotations

import os
import threading


def notify_critical(error_class: str) -> bool:
    """Show only a non-sensitive error class; never include action parameters."""
    if os.name != "nt":
        return False
    safe_class = "".join(character for character in error_class if character.isalnum() or character in "_.-")[:80]
    if not safe_class:
        safe_class = "critical_error"
    try:
        from win10toast import ToastNotifier  # type: ignore[import-not-found]

        def show() -> None:
            ToastNotifier().show_toast(
                "MICA - kritischer Fehler",
                f"Fehlerklasse: {safe_class}. Details stehen im lokalen, redigierten Audit.",
                duration=10,
                threaded=False,
            )

        threading.Thread(target=show, name="mica-critical-alert", daemon=True).start()
        return True
    except Exception:
        return False
