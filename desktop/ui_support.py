"""Local UI configuration, presence and context helpers."""
from __future__ import annotations
import json
import sys
from datetime import datetime
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR   = _base_dir()

CONFIG_DIR = BASE_DIR / "config"

API_FILE   = CONFIG_DIR / "api_keys.json"

PRESENCE_STATES = frozenset({
    "offline", "idle", "listening", "thinking", "approval_required", "executing", "speaking", "error",
})

def canonical_presence_state(state: str | None, *, speaking: bool = False, muted: bool = False) -> str:
    """Map legacy desktop voice labels onto the Phase-4 shared state machine."""
    value = (state or "idle").strip().lower()
    if speaking or value == "speaking":
        return "speaking"
    if value in {"offline", "sleeping", "disconnected"}:
        return "offline"
    if value in {"initialising", "connecting", "idle", "muted", "cancelled"} or muted:
        return "idle"
    if value in {"listening"}:
        return "listening"
    if value in {"thinking", "processing", "planning", "transcribing"}:
        return "thinking"
    if value in {"approval_required"}:
        return "approval_required"
    if value in {"executing"}:
        return "executing"
    if value in {"error", "failed"}:
        return "error"
    return "idle"

def day_presence_state(moment: datetime | None = None) -> str:
    hour = (moment or datetime.now().astimezone()).hour
    return "morning" if 5 <= hour < 11 else "day" if 11 <= hour < 18 else "evening" if 18 <= hour < 23 else "night"

def time_greeting(moment: datetime | None = None) -> str:
    """Reference-aligned German greeting for the calm ready state."""
    return {
        "morning": "Guten Morgen",
        "day": "Guten Tag",
        "evening": "Guten Abend",
        "night": "Guten Abend",
    }[day_presence_state(moment)]

def _read_full_config() -> dict:
    """Read api_keys.json config dict. Returns {} on any error."""
    try:
        return json.loads(API_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def latest_project_context(memory_data: dict | None = None) -> tuple[str, str] | None:
    """Return the newest real project saved in long-term memory.

    The HUD deliberately has no demonstration project: if memory has not yet
    recorded a project, callers receive ``None`` and render a clear empty
    state instead.
    """
    try:
        if memory_data is None:
            from desktop.memory.memory_manager import load_memory
            memory_data = load_memory()
        projects = (memory_data or {}).get("projects", {})
        if not isinstance(projects, dict):
            return None
        entries: list[tuple[str, int, str, str]] = []
        for position, (key, entry) in enumerate(projects.items()):
            if isinstance(entry, dict):
                value = str(entry.get("value", "") or "").strip()
                updated = str(entry.get("updated_at") or entry.get("updated", "") or "")
            else:
                value, updated = str(entry or "").strip(), ""
            if value:
                entries.append((updated, position, str(key), value))
        if not entries:
            return None
        _updated, _position, key, value = max(entries, key=lambda item: (item[0], item[1]))
        return key.replace("_", " ").strip().title(), value
    except Exception:
        return None

def next_reminder_context() -> tuple[str, str] | None:
    """Read the local reminder index without inventing a calendar entry."""
    try:
        from desktop.actions.reminder import list_upcoming_reminders
        reminders = list_upcoming_reminders(limit=1)
        if not reminders:
            return None
        reminder = reminders[0]
        return str(reminder["when"]), str(reminder["message"])
    except Exception:
        return None
