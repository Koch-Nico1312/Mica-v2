"""Versioned capability contracts for the Phase-0 Windows action boundary.

The model may propose an action, but this registry is the authority for whether
that action exists, which network/secret gates apply, and how it is classified.
No function in this module imports or executes the legacy ``actions`` package.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
from typing import Any


RISK_READ = "read"
RISK_SENSITIVE_READ = "sensitive_read"
RISK_REVERSIBLE = "reversible"
RISK_DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    requires_idempotency_key: bool = False
    retry_after_unknown_outcome: bool = False


@dataclass(frozen=True)
class CapabilityManifest:
    module: str
    action: str
    description: str
    default_risk: str
    operation_field: str = "action"
    risk_by_operation: dict[str, str] = field(default_factory=dict)
    network_required: bool = False
    required_secrets: tuple[str, ...] = ()
    timeout_seconds: int = 45
    platform: tuple[str, ...] = ("windows",)
    input_schema: dict[str, Any] = field(default_factory=lambda: {
        "type": "object", "maxProperties": 64, "properties": {}, "additionalProperties": True,
    })
    output_schema: dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "required": ["schema_version", "action", "operation", "risk", "output"],
        "properties": {"schema_version": {"const": 1}},
    })
    error_classes: tuple[str, ...] = (
        "unavailable", "invalid_input", "approval_required", "timeout",
        "execution_failed", "uncertain_outcome",
    )
    local_adapter_status: str = "ready"
    blocked_operations: tuple[str, ...] = ()
    allowed_operations: tuple[str, ...] = ()
    requires_target_allowlist: bool = False
    requires_recipient_allowlist: bool = False

    def operation(self, params: dict[str, Any]) -> str:
        return str(params.get(self.operation_field, "")).strip().lower()

    def risk_for(self, params: dict[str, Any]) -> str:
        if self.action == "files.create" and bool(params.get("overwrite")):
            return RISK_DESTRUCTIVE
        operation = self.operation(params)
        return self.risk_by_operation.get(operation, self.default_risk)

    def retry_for(self, params: dict[str, Any]) -> RetryPolicy:
        risk = self.risk_for(params)
        if risk in {RISK_READ, RISK_SENSITIVE_READ}:
            return RetryPolicy(max_attempts=3)
        if risk == RISK_REVERSIBLE:
            return RetryPolicy(max_attempts=2, requires_idempotency_key=True)
        return RetryPolicy(max_attempts=1, requires_idempotency_key=True)

    def network_enabled(self, environ: dict[str, str] | None = None) -> bool:
        if not self.network_required:
            return True
        env = os.environ if environ is None else environ
        key = f"MICA_CAPABILITY_{self.module.upper()}_NETWORK"
        return env.get(key, "").strip().lower() in {"1", "true", "yes", "on"}

    def network_targets(self, environ: dict[str, str] | None = None) -> tuple[str, ...]:
        env = os.environ if environ is None else environ
        key = f"MICA_CAPABILITY_{self.module.upper()}_TARGETS"
        return tuple(sorted({item.strip().lower() for item in env.get(key, "").split(",") if item.strip()}))

    def recipients(self, environ: dict[str, str] | None = None) -> tuple[str, ...]:
        env = os.environ if environ is None else environ
        key = f"MICA_CAPABILITY_{self.module.upper()}_RECIPIENTS"
        return tuple(sorted({item.strip() for item in env.get(key, "").split(",") if item.strip()}))

    def availability(self, environ: dict[str, str] | None = None) -> tuple[bool, str]:
        env = os.environ if environ is None else environ
        if self.local_adapter_status == "blocked":
            return False, "local_adapter_not_ready"
        if not self.network_enabled(env):
            return False, "network_disabled"
        if self.requires_target_allowlist and not self.network_targets(env):
            return False, "network_target_allowlist_missing"
        if self.requires_recipient_allowlist and not self.recipients(env):
            return False, "recipient_allowlist_missing"
        missing = [name for name in self.required_secrets if not env.get(name, "").strip()]
        if missing:
            return False, "missing_secret:" + ",".join(missing)
        return True, "available"

    def availability_for(self, params: dict[str, Any], environ: dict[str, str] | None = None) -> tuple[bool, str]:
        available, reason = self.availability(environ)
        if not available:
            return available, reason
        if self.operation(params) in self.blocked_operations:
            return False, "operation_requires_local_replacement"
        if self.allowed_operations and self.operation(params) not in self.allowed_operations:
            return False, "unsupported_operation"
        return True, "available"

    def public(self, environ: dict[str, str] | None = None) -> dict[str, Any]:
        available, reason = self.availability(environ)
        result = asdict(self)
        result["risk_by_operation"] = dict(self.risk_by_operation)
        result["required_secrets"] = list(self.required_secrets)
        result["platform"] = list(self.platform)
        result["error_classes"] = list(self.error_classes)
        result["blocked_operations"] = list(self.blocked_operations)
        result["allowed_operations"] = list(self.allowed_operations)
        result["available"] = available
        result["availability_reason"] = reason
        result["network_enabled"] = self.network_enabled(environ)
        result["network_targets"] = list(self.network_targets(environ))
        result["recipient_count"] = len(self.recipients(environ))
        result["retry"] = asdict(self.retry_for({}))
        return result


def _manifest(
    module: str,
    action: str,
    description: str,
    risk: str,
    *,
    operation_field: str = "action",
    operations: dict[str, str] | None = None,
    network: bool = False,
    secrets: tuple[str, ...] = (),
    timeout: int = 45,
    local_adapter_status: str = "ready",
    blocked_operations: tuple[str, ...] = (),
    allowed_operations: tuple[str, ...] = (),
    recipient_allowlist: bool = False,
) -> CapabilityManifest:
    operation_risks = {operation: risk for operation in allowed_operations}
    operation_risks.update(operations or {})
    input_schema = {
        "type": "object",
        "maxProperties": 64,
        "properties": {
            operation_field: {
                "type": "string",
                "enum": list(allowed_operations),
            },
        },
        "additionalProperties": True,
    }
    return CapabilityManifest(
        module=module,
        action=action,
        description=description,
        default_risk=risk,
        operation_field=operation_field,
        risk_by_operation=operation_risks,
        network_required=network,
        required_secrets=secrets,
        timeout_seconds=timeout,
        local_adapter_status=local_adapter_status,
        blocked_operations=blocked_operations,
        allowed_operations=allowed_operations,
        requires_target_allowlist=network,
        requires_recipient_allowlist=recipient_allowlist,
        input_schema=input_schema,
    )


CAPABILITIES: tuple[CapabilityManifest, ...] = (
    _manifest("background_monitor", "manage_monitor", "Themen beobachten", RISK_READ,
              operations={"add": RISK_REVERSIBLE, "remove": RISK_REVERSIBLE, "check": RISK_READ}, network=True,
              allowed_operations=("", "add", "remove", "list", "check")),
    _manifest("browser_control", "browser_control", "Browser bedienen", RISK_REVERSIBLE,
              operations={"get_text": RISK_SENSITIVE_READ, "get_url": RISK_SENSITIVE_READ,
                          "screenshot": RISK_SENSITIVE_READ, "click": RISK_DESTRUCTIVE,
                          "type": RISK_DESTRUCTIVE, "fill_form": RISK_DESTRUCTIVE,
                          "smart_click": RISK_DESTRUCTIVE, "smart_type": RISK_DESTRUCTIVE,
                          "press": RISK_DESTRUCTIVE}, network=True,
              allowed_operations=("switch", "list_browsers", "close_all", "close", "go_to", "search",
                                  "new_tab", "click", "type", "scroll", "fill_form", "smart_click",
                                  "smart_type", "get_text", "get_url", "press", "close_tab", "screenshot",
                                  "back", "forward", "reload")),
    _manifest("code_helper", "code_helper", "Code lesen, erzeugen und ausfuehren", RISK_DESTRUCTIVE,
              operations={"explain": RISK_SENSITIVE_READ}, local_adapter_status="partial",
              blocked_operations=("", "auto", "write", "edit", "explain", "build", "optimize", "screen_debug"),
              allowed_operations=("", "auto", "write", "edit", "explain", "build", "optimize", "screen_debug", "run")),
    _manifest("computer_control", "computer_control", "Maus, Tastatur und Fenster bedienen", RISK_REVERSIBLE,
              operations={"copy": RISK_SENSITIVE_READ, "screenshot": RISK_SENSITIVE_READ,
                          "screen_find": RISK_SENSITIVE_READ, "screen_click": RISK_DESTRUCTIVE,
                          "type": RISK_DESTRUCTIVE, "smart_type": RISK_DESTRUCTIVE,
                          "paste": RISK_DESTRUCTIVE, "click": RISK_DESTRUCTIVE,
                          "double_click": RISK_DESTRUCTIVE, "right_click": RISK_DESTRUCTIVE,
                          "hotkey": RISK_DESTRUCTIVE, "press": RISK_DESTRUCTIVE},
              local_adapter_status="partial", blocked_operations=("screen_find", "screen_click"),
              allowed_operations=("type", "smart_type", "click", "left_click", "double_click", "right_click",
                                  "move", "drag", "hotkey", "press", "scroll", "copy", "paste", "screenshot",
                                  "screen_find", "screen_click", "wait", "clear_field", "focus_window",
                                  "random_data", "user_data")),
    _manifest("computer_settings", "computer_settings", "Windows-Einstellungen aendern", RISK_REVERSIBLE,
              operations={"restart": RISK_DESTRUCTIVE, "shutdown": RISK_DESTRUCTIVE,
                          "type_text": RISK_DESTRUCTIVE, "press_key": RISK_DESTRUCTIVE},
              local_adapter_status="partial", blocked_operations=("", "suggest", "detect"),
              allowed_operations=("", "suggest", "detect", "volume_up", "volume_down", "volume_set", "mute",
                                  "unmute", "toggle_mute", "brightness_up", "brightness_down", "sleep_display",
                                  "screen_off", "pause_video", "play_pause", "close_app", "close_window",
                                  "full_screen", "fullscreen", "minimize", "maximize", "snap_left", "snap_right",
                                  "switch_window", "show_desktop", "task_manager", "focus_search", "refresh_page",
                                  "reload", "close_tab", "new_tab", "next_tab", "prev_tab", "go_back",
                                  "go_forward", "zoom_in", "zoom_out", "zoom_reset", "find_on_page", "scroll_up",
                                  "scroll_down", "scroll_top", "scroll_bottom", "page_up", "page_down", "copy",
                                  "paste", "cut", "undo", "redo", "select_all", "save", "enter", "escape",
                                  "screenshot", "lock_screen", "open_settings", "file_explorer", "open_run",
                                  "dark_mode", "toggle_wifi", "restart", "shutdown", "type_text", "write_on_screen",
                                  "type", "write", "press_key", "reload_n", "refresh_n", "reload_page_n")),
    _manifest("desktop", "desktop_control", "Desktop lesen und organisieren", RISK_REVERSIBLE,
              operations={"list": RISK_SENSITIVE_READ, "stats": RISK_SENSITIVE_READ,
                          "current_wallpaper": RISK_SENSITIVE_READ, "clean": RISK_DESTRUCTIVE,
                          "wallpaper_url": RISK_DESTRUCTIVE}, network=False,
              local_adapter_status="partial", blocked_operations=("", "custom", "ask", "generate", "task"),
              allowed_operations=("", "wallpaper", "wallpaper_url", "current_wallpaper", "organize", "clean",
                                  "list", "stats", "custom", "ask", "generate", "task")),
    _manifest("dev_agent", "dev_agent", "Projekte erzeugen, testen und reparieren", RISK_DESTRUCTIVE,
              operations={"inspect": RISK_SENSITIVE_READ}, timeout=120, local_adapter_status="partial",
              blocked_operations=("", "auto", "create", "build", "fix", "repair", "write"),
              allowed_operations=("", "auto", "create", "build", "fix", "repair", "write", "inspect")),
    _manifest("file_controller", "file_controller", "Dateien lesen und verwalten", RISK_REVERSIBLE,
              operations={"list": RISK_SENSITIVE_READ, "read": RISK_SENSITIVE_READ,
                          "find": RISK_SENSITIVE_READ, "info": RISK_SENSITIVE_READ,
                          "disk_usage": RISK_READ, "delete": RISK_DESTRUCTIVE,
                          "write": RISK_DESTRUCTIVE, "organize_desktop": RISK_DESTRUCTIVE},
              allowed_operations=("list", "create_file", "create_folder", "delete", "move", "copy", "rename",
                                  "read", "write", "find", "largest", "disk_usage", "organize_desktop", "info")),
    _manifest("file_processor", "file_processor", "Lokale Dateien verarbeiten", RISK_REVERSIBLE,
              operations={"info": RISK_SENSITIVE_READ, "word_count": RISK_SENSITIVE_READ,
                          "stats": RISK_SENSITIVE_READ, "validate": RISK_SENSITIVE_READ,
                          "run": RISK_DESTRUCTIVE, "summarize": RISK_SENSITIVE_READ,
                          "analyze": RISK_SENSITIVE_READ, "transcribe": RISK_SENSITIVE_READ,
                          "extract": RISK_DESTRUCTIVE},
              local_adapter_status="partial",
              blocked_operations=("", "auto", "summarize", "analyze", "transcribe", "extract"),
              allowed_operations=("", "auto", "info", "word_count", "stats", "validate", "run", "summarize", "analyze", "transcribe", "extract")),
    _manifest("flight_finder", "flight_finder", "Fluege suchen", RISK_READ, network=True,
              allowed_operations=("", "search")),
    _manifest("game_updater", "game_updater", "Spiele pruefen, installieren und aktualisieren", RISK_DESTRUCTIVE,
              operations={"list": RISK_READ, "download_status": RISK_READ,
                          "schedule_status": RISK_READ}, network=True, timeout=120,
              allowed_operations=("", "update", "install", "list", "download_status", "schedule", "cancel_schedule", "schedule_status")),
    _manifest("open_app", "open_app", "Installierte Anwendung starten", RISK_REVERSIBLE,
              allowed_operations=("", "open")),
    _manifest("proactive", "proactive", "Lokale proaktive Hinweise planen", RISK_REVERSIBLE,
              operations={"status": RISK_READ}, allowed_operations=("", "status", "preview")),
    _manifest("reminder", "reminder", "Erinnerungen verwalten", RISK_REVERSIBLE,
              allowed_operations=("", "create")),
    _manifest("screen_processor", "screen_process", "Bildschirm oder Kamera analysieren", RISK_SENSITIVE_READ,
              local_adapter_status="partial",
              blocked_operations=("", "analyze", "camera", "describe", "read"),
              allowed_operations=("", "analyze", "camera", "describe", "read", "capture_metadata")),
    _manifest("send_message", "send_message", "Nachricht an externen Empfaenger senden", RISK_DESTRUCTIVE,
              network=True, recipient_allowlist=True, allowed_operations=("", "send")),
    _manifest("system_monitor", "system_status", "Systemzustand lesen", RISK_READ, operation_field="operation",
              allowed_operations=("", "status")),
    _manifest("weather_report", "weather_report", "Wetter abrufen", RISK_READ, network=True,
              allowed_operations=("", "get")),
    _manifest("web_search", "web_search", "Websuche ausfuehren", RISK_READ, operation_field="mode", network=True,
              local_adapter_status="partial",
              blocked_operations=("", "search", "compare", "news", "research", "price"),
              allowed_operations=("", "search", "compare", "news", "research", "price")),
    _manifest("youtube_video", "youtube_video", "YouTube suchen, abspielen und zusammenfassen", RISK_REVERSIBLE,
              operations={"summarize": RISK_SENSITIVE_READ, "trending": RISK_READ,
                          "get_info": RISK_READ}, network=True, local_adapter_status="partial",
              blocked_operations=("summarize",), allowed_operations=("", "play", "summarize", "get_info", "trending")),
)

# Phase-4 host-agent scopes use the same registry lookup as the original
# desktop capabilities, while remaining outside the legacy 20-item desktop
# catalogue returned by list_capabilities().
HOST_AGENT_CAPABILITIES: tuple[CapabilityManifest, ...] = (
    CapabilityManifest("host_system", "system.status", "ZimaOS-Systemstatus lesen", RISK_READ, platform=("linux",)),
    CapabilityManifest("host_docker", "docker.status", "Allowlist-Containerstatus lesen", RISK_READ, platform=("linux",)),
    CapabilityManifest("host_files", "files.list", "Allowlist-Verzeichnis lesen", RISK_SENSITIVE_READ, platform=("linux",)),
    CapabilityManifest("host_files", "files.create", "Allowlist-Datei erstellen", RISK_REVERSIBLE, platform=("linux",)),
    CapabilityManifest("host_files", "files.move", "Allowlist-Datei verschieben", RISK_REVERSIBLE, platform=("linux",)),
    CapabilityManifest("host_files", "files.delete", "Allowlist-Datei in Quarantaene verschieben", RISK_DESTRUCTIVE, platform=("linux",)),
    CapabilityManifest("host_network", "network.change", "Allowlist-Netzprofil aendern", RISK_DESTRUCTIVE, platform=("linux",)),
    CapabilityManifest(
        "host_docker", "docker.lifecycle", "Allowlist-Container verwalten", RISK_DESTRUCTIVE,
        operation_field="operation", allowed_operations=("start", "stop", "restart"), platform=("linux",),
    ),
    CapabilityManifest("host_system", "system.admin", "Allowlist-Hostaktion ausfuehren", RISK_DESTRUCTIVE, platform=("linux",)),
)

# Phase 4.5 perception capabilities
PHASE45_CAPABILITIES: tuple[CapabilityManifest, ...] = (
    CapabilityManifest("vision", "vision.capture", "Kamerabild aufnehmen", RISK_SENSITIVE_READ, platform=("windows", "linux")),
    CapabilityManifest("vision", "vision.analyze", "Kamerabild oder Foto analysieren", RISK_SENSITIVE_READ, platform=("windows", "linux")),
    CapabilityManifest("vision", "vision.inspect_rack", "Server-Rack optisch inspizieren", RISK_READ, platform=("windows", "linux")),
)

_BY_ACTION = {manifest.action: manifest for manifest in (*CAPABILITIES, *HOST_AGENT_CAPABILITIES, *PHASE45_CAPABILITIES)}
_BY_MODULE = {manifest.module: manifest for manifest in (*CAPABILITIES, *HOST_AGENT_CAPABILITIES, *PHASE45_CAPABILITIES)}


def capability_for(action: str) -> CapabilityManifest | None:
    return _BY_ACTION.get(action) or _BY_MODULE.get(action)


def list_capabilities(environ: dict[str, str] | None = None) -> list[dict[str, Any]]:
    return [manifest.public(environ) for manifest in CAPABILITIES]


def validate_action(action: str, params: dict[str, Any]) -> tuple[CapabilityManifest, str]:
    manifest = capability_for(action)
    if manifest is None:
        raise ValueError("Action is not present in the Phase-0 capability registry")
    if not isinstance(params, dict):
        raise ValueError("Action parameters must be an object")
    return manifest, manifest.risk_for(params)
