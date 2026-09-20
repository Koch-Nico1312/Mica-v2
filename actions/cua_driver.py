"""Cua Driver bridge: native Windows app control without stealing focus.

Cua (https://github.com/trycua/cua) ships a Windows driver that agents can use
to inspect and operate native applications with background delivery — the
agent works without moving the user's pointer or taking focus, where the app
and platform support it.

This module is a thin, fail-closed adapter for MICA:

- Enabled only when MICA_CUA_ENABLED=1 AND the driver executable is detected.
- All actual command dispatch happens through the locally installed ``cua``
  CLI; this wrapper never shells out to anything else.
- Irreversible/destructive commands (close, quit) run through MICA's existing
  on-screen confirmation gate (core.confirm) before the driver is invoked.
- When the driver is missing or fails, callers get a clear signal so they can
  fall back to the existing pyautogui/pywinauto path.

The Cua VM/Fleet/cloud parts are deliberately out of scope: MICA runs on the
user's own Windows machine and controls only the applications on it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Callable

CONFIRM_COMMANDS = {"close", "quit"}
_SAFE_COMMANDS = {
    "focus", "type", "press", "click", "double_click", "right_click",
    "scroll", "read", "screenshot", "list_apps",
}


def enabled() -> bool:
    return os.getenv("MICA_CUA_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def driver_available() -> str | None:
    """Return the driver executable name when installed, else None."""
    if shutil.which("cua"):
        return "cua"
    for candidate in ("cua-driver", "cuad"):
        if shutil.which(candidate):
            return candidate
    return None


def status() -> dict[str, Any]:
    driver = driver_available() if enabled() else None
    return {"enabled": enabled(), "driver": driver, "available": bool(driver)}


def _run_driver(driver: str, args: list[str], timeout: int) -> str:
    completed = subprocess.run(
        [driver, *args], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=max(5, int(timeout)), check=False,
        env={**os.environ, "CUA_NONINTERACTIVE": "1"},
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or "cua driver failed").strip()[-400:])
    return (completed.stdout or "ok").strip()[:2000] or "ok"


def native_app_control(
    parameters: dict[str, Any],
    response: Any = None,
    player: Any = None,
    confirm_request: Callable[[str, str, str, Callable[[], str]], str] | None = None,
) -> str:
    """MICA tool entry point for background native-app control.

    parameters:
        action:   focus | type | press | click | double_click | right_click |
                  scroll | read | screenshot | list_apps | close
        app:      target application name/window title (required for app commands)
        text:     text to type (type)
        key:      key or hotkey (press)
        amount:   scroll amount (scroll, may be negative)
        timeout:  seconds for the driver call (default 15)
    """
    action = str(parameters.get("action", "")).strip().lower()
    if not action:
        return "cua: no action given. Use one of: " + ", ".join(sorted(_SAFE_COMMANDS | CONFIRM_COMMANDS))
    if action not in _SAFE_COMMANDS and action not in CONFIRM_COMMANDS:
        return f"cua: unknown action '{action}'. Allowed: " + ", ".join(sorted(_SAFE_COMMANDS | CONFIRM_COMMANDS))

    if not enabled():
        return "cua: disabled. Set MICA_CUA_ENABLED=1 to enable background native-app control."
    driver = driver_available()
    if not driver:
        return (
            "cua: driver not installed. Install it once with PowerShell: "
            "irm https://cua.ai/driver/install.ps1 | iex — then try again."
        )

    app = str(parameters.get("app", "")).strip()
    timeout = int(parameters.get("timeout", 15) or 15)

    def _invoke() -> str:
        if action == "list_apps":
            return _run_driver(driver, ["apps", "list"], timeout)
        if not app:
            raise RuntimeError("the 'app' parameter is required for this action")
        if action == "focus":
            return _run_driver(driver, ["apps", "focus", app], timeout)
        if action == "read":
            return _run_driver(driver, ["apps", "read", app], timeout)
        if action == "screenshot":
            return _run_driver(driver, ["apps", "screenshot", app], timeout)
        if action == "type":
            return _run_driver(driver, ["apps", "type", app, str(parameters.get("text", ""))], timeout)
        if action == "press":
            return _run_driver(driver, ["apps", "press", app, str(parameters.get("key", ""))], timeout)
        if action in {"click", "double_click", "right_click"}:
            return _run_driver(driver, ["apps", action.replace("_", "-"), app], timeout)
        if action == "scroll":
            return _run_driver(driver, ["apps", "scroll", app, str(int(parameters.get("amount", 3) or 3))], timeout)
        if action == "close":
            return _run_driver(driver, ["apps", "close", app], timeout)
        raise RuntimeError(f"unhandled action {action}")

    try:
        if action in CONFIRM_COMMANDS:
            gate = confirm_request
            if gate is None:
                try:
                    from core import confirm as confirm_gate

                    gate = confirm_gate.request
                except Exception:
                    gate = None
            if gate is None:
                return f"cua: cannot confirm closing '{app}' because the confirmation gate is unavailable. Nothing was closed."
            return gate(
                f"cua-close:{app}",
                f"App schließen: {app}",
                f"MICA schließt die Anwendung '{app}' über den Cua Driver.",
                _invoke,
            )
        return _invoke()
    except Exception as error:
        return f"cua: {error}. Nothing was changed — use the regular desktop control instead."
