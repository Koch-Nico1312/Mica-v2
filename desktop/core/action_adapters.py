"""Explicit adapters from Phase-0 capability names to legacy action modules.

This module is imported only by the native Windows action runner.  It contains
no generic module/function input and therefore cannot be used as an import or
reflection gadget by model-supplied parameters.
"""
from __future__ import annotations

import importlib
import inspect
import hashlib
import os
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Callable

from backend.services.common.capabilities import capability_for

_DESKTOP_DIR = Path(__file__).resolve().parents[1]
if str(_DESKTOP_DIR) not in sys.path:
    sys.path.insert(0, str(_DESKTOP_DIR))


class ActionUnavailable(RuntimeError):
    pass


ENTRYPOINTS: dict[str, tuple[str, str]] = {
    "browser_control": ("actions.browser_control", "browser_control"),
    "code_helper": ("actions.code_helper", "code_helper"),
    "computer_control": ("actions.computer_control", "computer_control"),
    "computer_settings": ("actions.computer_settings", "computer_settings"),
    "desktop_control": ("actions.desktop", "desktop_control"),
    "dev_agent": ("actions.dev_agent", "dev_agent"),
    "file_controller": ("actions.file_controller", "file_controller"),
    "file_processor": ("actions.file_processor", "file_processor"),
    "flight_finder": ("actions.flight_finder", "flight_finder"),
    "game_updater": ("actions.game_updater", "game_updater"),
    "open_app": ("actions.open_app", "open_app"),
    "reminder": ("actions.reminder", "reminder"),
    "screen_process": ("actions.screen_processor", "screen_process"),
    "send_message": ("actions.send_message", "send_message"),
    "weather_report": ("actions.weather_report", "weather_action"),
    "web_search": ("actions.web_search", "web_search"),
    "youtube_video": ("actions.youtube_video", "youtube_video"),
}

# These legacy branches instantiate Gemini themselves.  They remain visible in
# the manifest, but the Windows production runner fails closed until a local
# replacement is used.  Safe direct operations in mixed modules stay usable.
_CLOUD_ONLY_MODULES: set[str] = set()
_CLOUD_ONLY_OPERATIONS = {
    "code_helper": {"", "auto", "write", "edit", "explain", "build", "optimize", "screen_debug"},
    "file_processor": {"", "auto", "summarize", "analyze", "transcribe", "extract"},
    "computer_control": {"screen_find", "screen_click"},
    "desktop": {"custom", "ask", "generate"},
    "computer_settings": {"suggest", "detect"},
    "youtube_video": {"summarize"},
    "dev_agent": {"", "auto", "create", "build", "fix", "repair", "write"},
    "screen_processor": {"", "analyze", "camera", "describe", "read"},
    "web_search": {"", "search", "compare", "news", "research", "price"},
}

_PATH_FIELDS = {"path", "file_path", "output_path", "project_path", "source", "destination"}


def _fixed_network_targets(action: str, params: dict[str, Any]) -> set[str]:
    operation = str(params.get("action", params.get("mode", ""))).strip().lower()
    if action == "manage_monitor" and operation == "check":
        return {"duckduckgo.com"}
    if action == "browser_control" and operation == "search":
        engines = {
            "google": "www.google.com", "bing": "www.bing.com",
            "duckduckgo": "duckduckgo.com", "yandex": "yandex.com",
        }
        return {engines.get(str(params.get("engine", "google")).strip().lower(), "www.google.com")}
    if action == "weather_report":
        return {"www.google.com"}
    if action == "flight_finder":
        return {"www.google.com"}
    if action == "game_updater" and operation in {"install", "update"}:
        return {"store.steampowered.com"}
    if action == "youtube_video":
        return {"www.youtube.com"}
    if action == "send_message":
        platform = str(params.get("platform", "whatsapp")).strip().lower()
        targets = {
            "whatsapp": "whatsapp.com", "wp": "whatsapp.com", "wapp": "whatsapp.com",
            "telegram": "telegram.org", "tg": "telegram.org", "signal": "signal.org",
            "discord": "discord.com", "instagram": "www.instagram.com",
            "ig": "www.instagram.com", "insta": "www.instagram.com",
            "messenger": "www.messenger.com", "facebook": "www.messenger.com", "fb": "www.messenger.com",
        }
        return {targets[platform]} if platform in targets else set()
    return set()


def _enabled_actions(environ: dict[str, str]) -> set[str]:
    return {item.strip() for item in environ.get("MICA_WINDOWS_ENABLED_ACTIONS", "").split(",") if item.strip()}


def execution_availability(action: str, params: dict[str, Any], environ: dict[str, str] | None = None) -> tuple[bool, str]:
    env = dict(os.environ if environ is None else environ)
    manifest = capability_for(action)
    if manifest is None:
        return False, "unknown_action"
    enabled = _enabled_actions(env)
    if action not in enabled and manifest.module not in enabled:
        return False, "action_not_enabled_on_windows_host"
    available, reason = manifest.availability_for(params, env)
    if not available:
        return False, reason
    operation = manifest.operation(params)
    if manifest.module in _CLOUD_ONLY_MODULES:
        return False, "legacy_cloud_model_dependency"
    if operation in _CLOUD_ONLY_OPERATIONS.get(manifest.module, set()):
        return False, "legacy_cloud_model_dependency"
    if action == "open_app":
        requested_app = str(params.get("app_name", "")).strip().casefold()
        allowed_apps = {
            item.strip().casefold()
            for item in env.get("MICA_WINDOWS_ALLOWED_APPS", "").split(",")
            if item.strip()
        }
        if not allowed_apps:
            return False, "app_allowlist_missing"
        if not requested_app or requested_app not in allowed_apps:
            return False, "app_not_allowlisted"
    supplied_paths = [str(value) for key, value in params.items() if key in _PATH_FIELDS and value]
    if supplied_paths:
        roots = [
            Path(item.strip()).expanduser().resolve(strict=False)
            for item in env.get("MICA_WINDOWS_ALLOWED_ROOTS", "").split(os.pathsep)
            if item.strip()
        ]
        if not roots:
            return False, "local_path_allowlist_missing"
        for raw_path in supplied_paths:
            resolved = Path(raw_path).expanduser().resolve(strict=False)
            if not any(resolved == root or resolved.is_relative_to(root) for root in roots):
                return False, "local_path_not_allowlisted"
    allowed_targets = set(manifest.network_targets(env))
    if not _fixed_network_targets(action, params).issubset(allowed_targets):
        return False, "network_target_not_allowlisted"
    for key in ("url", "endpoint", "webhook_url"):
        raw = params.get(key)
        if not raw:
            continue
        parsed = urlparse(str(raw))
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"https"} or not host or host not in allowed_targets:
            return False, "network_target_not_allowlisted"
    if manifest.requires_recipient_allowlist:
        recipient = str(params.get("receiver", params.get("recipient", params.get("to", "")))).strip()
        if not recipient or recipient not in set(manifest.recipients(env)):
            return False, "recipient_not_allowlisted"
    return True, "available"


def _call(entrypoint: Callable[..., Any], params: dict[str, Any]) -> Any:
    signature = inspect.signature(entrypoint)
    if not signature.parameters:
        return entrypoint()
    kwargs: dict[str, Any] = {}
    for name in ("response", "player", "session_memory", "speak"):
        if name in signature.parameters:
            kwargs[name] = None
    return entrypoint(parameters=params, **kwargs)


def _background_monitor(params: dict[str, Any]) -> Any:
    module = importlib.import_module("actions.background_monitor")
    operation = str(params.get("action", "list")).strip().lower()
    topic = str(params.get("topic", "")).strip()
    if operation == "add":
        return module.add_monitor(topic)
    if operation == "remove":
        return module.remove_monitor(topic)
    if operation == "list":
        return module.list_monitors()
    if operation == "check":
        return module.check_all()
    raise ActionUnavailable("Unsupported background-monitor operation")


def _proactive(params: dict[str, Any]) -> Any:
    module = importlib.import_module("actions.proactive")
    engine = module.ProactiveEngine(
        min_silence_secs=int(params.get("min_silence_secs", 900)),
        check_cooldown=int(params.get("check_cooldown", 1200)),
    )
    operation = str(params.get("action", "status")).strip().lower()
    if operation == "status":
        return {"min_silence_secs": engine.min_silence_secs, "check_cooldown": engine.check_cooldown}
    if operation == "preview":
        return engine.build_prompt(params.get("memory", {}), params.get("monitors", []), params.get("recent_turns", []))
    raise ActionUnavailable("Unsupported proactive operation")


def _flight_finder(params: dict[str, Any]) -> Any:
    """Build a bounded Google Flights target without invoking Gemini."""
    module = importlib.import_module("actions.flight_finder")
    origin = str(params.get("origin", "")).strip().upper()
    destination = str(params.get("destination", "")).strip().upper()
    departure = str(params.get("date", "")).strip()
    returning = str(params.get("return_date", "")).strip() or None
    if not (origin.isalnum() and destination.isalnum() and 2 <= len(origin) <= 8 and 2 <= len(destination) <= 8):
        raise ActionUnavailable("origin_and_destination_are_required")
    try:
        date.fromisoformat(departure)
        if returning:
            date.fromisoformat(returning)
    except ValueError as error:
        raise ActionUnavailable("dates_must_use_yyyy_mm_dd") from error
    passengers = max(1, min(int(params.get("passengers", 1)), 9))
    cabin = str(params.get("cabin", "economy")).strip().lower()
    if cabin not in module._CABIN_CODE:
        raise ActionUnavailable("unsupported_cabin")
    return {
        "url": module._build_google_flights_url(
            origin, destination, departure, returning, passengers, cabin,
        ),
        "opened": False,
        "note": "Local deterministic target only; no hosted model or automatic booking.",
    }


def _dev_agent(params: dict[str, Any]) -> Any:
    """Inspect a project without reading contents or invoking a hosted model."""
    project = Path(str(params.get("project_path", ""))).expanduser().resolve(strict=True)
    if not project.is_dir():
        raise ActionUnavailable("project_path_must_be_a_directory")
    files = [item for item in project.rglob("*") if item.is_file()]
    suffixes: dict[str, int] = {}
    for item in files[:10_000]:
        suffix = item.suffix.lower() or "[no_extension]"
        suffixes[suffix] = suffixes.get(suffix, 0) + 1
    test_markers = [name for name in ("tests", "test", "pyproject.toml", "package.json") if (project / name).exists()]
    return {
        "project": project.name,
        "file_count": len(files),
        "file_types": dict(sorted(suffixes.items(), key=lambda item: (-item[1], item[0]))[:20]),
        "test_markers": test_markers,
        "contents_read": False,
        "changed": False,
    }


def _screen_processor(params: dict[str, Any]) -> Any:
    """Capture no-persistence screen metadata for the local vision boundary."""
    try:
        import mss  # type: ignore[import-not-found]
    except ImportError as error:
        raise ActionUnavailable("missing_dependency:mss") from error
    monitor_index = int(params.get("monitor", 1))
    with mss.mss() as capture:
        if monitor_index < 0 or monitor_index >= len(capture.monitors):
            raise ActionUnavailable("invalid_monitor")
        shot = capture.grab(capture.monitors[monitor_index])
        pixels = bytes(shot.rgb)
        return {
            "monitor": monitor_index,
            "width": int(shot.width),
            "height": int(shot.height),
            "sha256": hashlib.sha256(pixels).hexdigest(),
            "bytes_inspected": len(pixels),
            "persisted": False,
            "analysis": "not_requested",
        }


def execute(action: str, params: dict[str, Any], environ: dict[str, str] | None = None) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    available, reason = execution_availability(action, params, env)
    if not available:
        raise ActionUnavailable(reason)
    manifest = capability_for(action)
    assert manifest is not None

    try:
        if action == "manage_monitor":
            result = _background_monitor(params)
        elif action == "proactive":
            result = _proactive(params)
        elif action == "system_status":
            result = importlib.import_module("actions.system_monitor").get_system_status()
        elif action == "flight_finder":
            result = _flight_finder(params)
        elif action == "dev_agent":
            result = _dev_agent(params)
        elif action == "screen_process":
            result = _screen_processor(params)
        else:
            target = ENTRYPOINTS.get(action)
            if not target:
                raise ActionUnavailable("No explicit Windows adapter exists")
            module = importlib.import_module(target[0])
            result = _call(getattr(module, target[1]), params)
    except ModuleNotFoundError as error:
        raise ActionUnavailable(f"missing_dependency:{error.name or manifest.module}") from error
    except ImportError as error:
        name = getattr(error, "name", None) or manifest.module
        raise ActionUnavailable(f"missing_dependency:{name}") from error

    return {
        "schema_version": 1,
        "action": action,
        "operation": manifest.operation(params),
        "risk": manifest.risk_for(params),
        "output": result,
    }
