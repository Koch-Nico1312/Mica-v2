import json
import sys
from pathlib import Path

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR    = get_base_dir()
CONFIG_DIR  = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "api_keys.json"

def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def config_exists() -> bool:
    return CONFIG_FILE.exists()

def save_api_keys(gemini_api_key: str) -> None:
    ensure_config_dir()

    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    data["gemini_api_key"] = gemini_api_key.strip()

    CONFIG_FILE.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8"
    )

def load_api_keys() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ Failed to load api_keys.json: {e}")
        return {}

def get_gemini_key() -> str | None:
    return load_api_keys().get("gemini_api_key")

def is_configured() -> bool:
    key = get_gemini_key()
    return bool(key and len(key) > 15)


def get_assistant_name() -> str:
    """Return the configured assistant name, or 'JARVIS' if not set."""
    return load_api_keys().get("assistant_name", "JARVIS") or "JARVIS"


def get_user_name() -> str:
    """Return the configured user name for addressing."""
    return load_api_keys().get("user_name", "")


def save_assistant_config(assistant_name: str, user_name: str) -> None:
    """Persist assistant name and user name to config."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["assistant_name"] = assistant_name.strip() or "JARVIS"
    data["user_name"] = user_name.strip()
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


# ── Assistant voice ──────────────────────────────────────────────────────────
# MICA has one stable voice identity: every selectable Gemini Live voice is
# female.  Older configs that contain Charon/Puck/Fenrir are migrated safely
# by get_voice() to the default instead of reusing a male voice.
AVAILABLE_VOICES = ["Aoede", "Kore"]
DEFAULT_VOICE    = "Aoede"

def get_voice() -> str:
    """Return a female Live voice and persist migration of legacy values."""
    data = load_api_keys()
    stored = data.get("voice_name")
    selected = stored if stored in AVAILABLE_VOICES else DEFAULT_VOICE

    # Old releases offered male voices such as Charon, Puck and Fenrir.  A
    # runtime-only fallback would leave the stale value on disk forever and
    # let another config reader revive it, so migrate an existing bad value.
    if "voice_name" in data and stored != selected:
        try:
            _patch_config(voice_name=selected)
        except OSError as exc:
            # A read-only config must not prevent MICA from starting.  The
            # safe in-memory value is still returned for this session.
            print(f"[Config] Could not migrate voice_name: {exc}")
    return selected


def save_voice(voice_name: str) -> None:
    """Persist the chosen Live voice. Unknown names collapse to the default so a
    bad value can never reach the API and break the session."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    v = (voice_name or "").strip()
    data["voice_name"] = v if v in AVAILABLE_VOICES else DEFAULT_VOICE
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def get_brief_enabled() -> bool:
    return load_api_keys().get("morning_brief_enabled", True)


def save_brief_enabled(enabled: bool) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["morning_brief_enabled"] = enabled
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


# ── Audio devices ────────────────────────────────────────────────────────────
# Stored as device NAMES, not sounddevice indices. Indices shift every time a
# USB device is plugged in or removed, so a saved index silently starts pointing
# at a different microphone. The empty string means "system default", which is
# both the factory setting and what an unresolvable saved device falls back to —
# so unplugging a headset degrades to the built-in speakers instead of crashing.

def _patch_config(**fields) -> None:
    """Read-modify-write one or more keys in api_keys.json.

    Every setter in this file open-coded this. Collapsing it here means a new
    setting is one line, and there is one place where a corrupt config file is
    handled instead of nine."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data.update(fields)
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def get_input_device() -> str:
    """Microphone device name, or '' for the system default."""
    return (load_api_keys().get("input_device", "") or "").strip()


def save_input_device(name: str) -> None:
    _patch_config(input_device=(name or "").strip())


def get_output_device() -> str:
    """Speaker device name, or '' for the system default."""
    return (load_api_keys().get("output_device", "") or "").strip()


def save_output_device(name: str) -> None:
    _patch_config(output_device=(name or "").strip())


def get_plugin_enabled(plugin_name: str) -> bool:
    """Plugins are enabled by default the moment they're discovered (opt-out model)."""
    return load_api_keys().get("plugins_enabled", {}).get(plugin_name, True)


def save_plugin_enabled(plugin_name: str, enabled: bool) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    plugins_cfg = data.get("plugins_enabled")
    if not isinstance(plugins_cfg, dict):
        plugins_cfg = {}
    plugins_cfg[plugin_name] = enabled
    data["plugins_enabled"] = plugins_cfg
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


# ── Personality Modes ───────────────────────────────────────────────────────────
AVAILABLE_PERSONALITIES = ["normal", "technical", "concentrated", "casual"]
DEFAULT_PERSONALITY = "normal"

PERSONALITY_SYSTEM_PROMPTS = {
    "normal": "You are a helpful, friendly AI assistant.",
    "technical": "You are a technical expert assistant. Focus on precision, technical details, and accurate terminology.",
    "concentrated": "You are a focused, direct assistant. Be concise and get straight to the point without unnecessary elaboration.",
    "casual": "You are a casual, relaxed assistant. Use informal language and be conversational."
}


def get_personality_mode() -> str:
    """Return the current personality mode."""
    return load_api_keys().get("personality_mode", DEFAULT_PERSONALITY) or DEFAULT_PERSONALITY


def save_personality_mode(mode: str) -> None:
    """Persist the chosen personality mode."""
    mode = (mode or "").strip()
    selected = mode if mode in AVAILABLE_PERSONALITIES else DEFAULT_PERSONALITY
    _patch_config(personality_mode=selected)


def get_personality_prompt() -> str:
    """Return the system prompt for the current personality mode."""
    mode = get_personality_mode()
    return PERSONALITY_SYSTEM_PROMPTS.get(mode, PERSONALITY_SYSTEM_PROMPTS[DEFAULT_PERSONALITY])


# ── Model Selection ─────────────────────────────────────────────────────────────
AVAILABLE_MODELS = {
    "flash": "models/gemini-2.5-flash-native-audio-preview-12-2025",
    "pro": "models/gemini-2.5-pro",
    "flash_lite": "models/gemini-2.5-flash-lite"
}
DEFAULT_MODEL = "flash"

MODEL_DESCRIPTIONS = {
    "flash": "Schnelles, Audio-fähiges Modell für tägliche Aufgaben",
    "pro": "Hochwertiges Modell für komplexe Aufgaben",
    "flash_lite": "Leichtes Modell für einfache Anfragen"
}


def get_model_selection() -> str:
    """Return the current selected model key."""
    return load_api_keys().get("model_selection", DEFAULT_MODEL) or DEFAULT_MODEL


def save_model_selection(model_key: str) -> None:
    """Persist the chosen model selection."""
    model_key = (model_key or "").strip()
    selected = model_key if model_key in AVAILABLE_MODELS else DEFAULT_MODEL
    _patch_config(model_selection=selected)


def get_model_name() -> str:
    """Return the actual model name for API calls."""
    model_key = get_model_selection()
    return AVAILABLE_MODELS.get(model_key, AVAILABLE_MODELS[DEFAULT_MODEL])


def get_model_description() -> str:
    """Return description of current model."""
    model_key = get_model_selection()
    return MODEL_DESCRIPTIONS.get(model_key, MODEL_DESCRIPTIONS[DEFAULT_MODEL])
