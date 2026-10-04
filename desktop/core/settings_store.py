"""Persistent settings used by the desktop settings panels.

Feature switches and provider metadata are ordinary configuration. Provider
secrets are deliberately kept out of these files and delegated to Windows
Credential Manager through :mod:`desktop.core.secure_store`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

from desktop.core.secure_store import delete_secret, get_secret, set_secret


TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
SUPPORTED_PROVIDERS = frozenset({"local_llama", "openai_api", "gemini"})
PROVIDER_LABELS = {
    "local_llama": "Lokales MICA-Modell",
    "openai_api": "OpenAI API",
    "gemini": "Google Gemini",
}
MODEL_SUGGESTIONS = {
    "local_llama": ("Qwen3-4B-Q4_K_M.gguf",),
    "openai_api": ("gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"),
    "gemini": ("gemini-2.5-flash", "gemini-2.5-pro"),
}
PROVIDER_SECRET_ENV = {
    "openai_api": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


@dataclass(frozen=True)
class FeatureDefinition:
    key: str
    title: str
    description: str
    category: str
    default: bool = False
    scopes: tuple[str, ...] = ("backend",)


FEATURES = (
    FeatureDefinition("MICA_WAKE_WORD_ENABLED", "Aktivierungswort", "Mica per Sprachbefehl aufwecken.", "Sprache", scopes=("root",)),
    FeatureDefinition("MICA_LEARNING_NETWORK", "Web-Recherche", "Öffentliche Quellen für Lernaufgaben verwenden.", "Lernen"),
    FeatureDefinition("MICA_LEARNING_MONITORING_ENABLED", "Lern-Monitoring", "Lernfortschritt im Hintergrund beobachten.", "Lernen"),
    FeatureDefinition("MICA_PHASE3_ENABLED", "Aufgabenautomatisierung", "Phase-3-Aufgaben und Arbeitsabläufe freigeben.", "Automatisierung"),
    FeatureDefinition("MICA_AUTOMATIONS_ENABLED", "Geplante Automationen", "Gespeicherte Automationen ausführen.", "Automatisierung"),
    FeatureDefinition("MICA_PHASE4_ENABLED", "Autonome Funktionen", "Gemeinsame Basis für Planung und Server-Funktionen.", "Autonomie"),
    FeatureDefinition("MICA_SELF_PLANNING_ENABLED", "Selbstplanung", "Mehrstufige Aufgaben eigenständig planen.", "Autonomie"),
    FeatureDefinition("MICA_SERVER_AGENT_ENABLED", "Server-Agent", "Freigegebene Homelab-Systeme verwalten.", "Autonomie"),
    FeatureDefinition("MICA_DIGITAL_TWIN_ENABLED", "Digitaler Zwilling", "Lokales Zustandsmodell deiner Systeme führen.", "Autonomie"),
    FeatureDefinition("MICA_SELF_IMPROVEMENT_ENABLED", "Verbesserungsvorschläge", "Wiederkehrende Fehler erkennen und Vorschläge erstellen.", "Autonomie"),
    FeatureDefinition("MICA_PHASE45_ENABLED", "Phase 4.5", "Erweiterte Pilotfunktionen aktivieren.", "Experimentell"),
    FeatureDefinition("MICA_DREAM_RSI_ENABLED", "Dream-RSI", "Offline-Verbesserungsvorschläge erzeugen; Änderungen bleiben prüfpflichtig.", "Experimentell", scopes=("root", "backend")),
    FeatureDefinition("MICA_LAYA_ENABLED", "Laya-Bewertung", "Antwortkandidaten lokal bewerten und neu ordnen.", "Experimentell", scopes=("root", "backend")),
    FeatureDefinition("MICA_SCRAPLING_ENABLED", "Scrapling-Parser", "Optionalen Webseiten-Parser für Recherche nutzen.", "Experimentell", True),
)
FEATURE_BY_KEY = {item.key: item for item in FEATURES}
DESKTOP_FEATURE_KEYS = frozenset(
    item.key for item in FEATURES if "root" in item.scopes
)


@dataclass(frozen=True)
class ProviderProfile:
    id: str
    name: str
    provider: str
    model: str
    credential_name: str = ""


def _read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            result[key] = value.strip()
    return result


def _update_env(path: Path, updates: dict[str, str]) -> None:
    """Update selected variables without discarding comments or other keys."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    pending = dict(updates)
    output: list[str] = []
    written: set[str] = set()
    for line in lines:
        match = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s*=", line)
        key = match.group(1) if match else ""
        if key in pending:
            if key not in written:
                output.append(f"{key}={pending[key]}")
                written.add(key)
            continue
        output.append(line)
    if output and output[-1] != "" and set(pending) - written:
        output.append("")
    for key, value in pending.items():
        if key not in written:
            output.append(f"{key}={value}")
    _atomic_write_text(path, "\n".join(output).rstrip() + "\n")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def load_desktop_feature_environment(project_root: Path | None = None) -> None:
    """Load only allowlisted non-secret desktop switches from the root env."""
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    values = _read_env(root / ".env")
    for key in DESKTOP_FEATURE_KEYS | {'MICA_CORE_URL', 'MICA_CORE_CA_FILE'}:
        if key in values:
            os.environ[key] = values[key]


def _run_backend_launcher(
    arguments: list[str], project_root: Path | None = None, timeout: int = 1800,
) -> None:
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    managed_python = root / ".venv-local" / "Scripts" / "python.exe"
    executable = managed_python if managed_python.is_file() else Path(sys.executable)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        completed = subprocess.run(
            [str(executable), "-m", "backend.windows_launcher", "--", *arguments],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            check=False,
            timeout=max(30, int(timeout)),
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Zeitüberschreitung beim Neustart des MICA-Backends.") from error
    except OSError as error:
        raise RuntimeError("Der sichere Backend-Launcher konnte nicht gestartet werden.") from error
    if completed.returncode != 0:
        raise RuntimeError(f"Der MICA-Backend-Befehl ist fehlgeschlagen (Code {completed.returncode}).")


def apply_backend_configuration(project_root: Path | None = None, timeout: int = 1800) -> None:
    """Rebuild and recreate Compose through the credential-aware launcher."""
    _run_backend_launcher(
        ["up", "-d", "--build", "--force-recreate"], project_root, timeout,
    )


def stop_cloud_backend(project_root: Path | None = None, timeout: int = 180) -> None:
    """Stop every container that can retain a cloud API key in its environment."""
    _run_backend_launcher(["stop", "mica-api", "tts"], project_root, timeout)


class SettingsStore:
    def __init__(self, project_root: Path | None = None):
        self.project_root = (project_root or Path(__file__).resolve().parents[2]).resolve()
        self.root_env = self.project_root / ".env"
        self.backend_env = self.project_root / "backend" / ".env"
        self.config_dir = self.project_root / "desktop" / "config"
        self.profiles_file = self.config_dir / "provider_profiles.json"
        self.credentials_file = self.config_dir / "credential-names.json"

    def _env_path(self, scope: str) -> Path:
        if scope == "root":
            return self.root_env
        if scope == "backend":
            return self.backend_env
        raise ValueError(f"Unknown settings scope: {scope}")

    def feature_enabled(self, key: str) -> bool:
        feature = FEATURE_BY_KEY.get(key)
        if feature is None:
            raise KeyError(key)
        if key in os.environ:
            return os.environ[key].strip().lower() in TRUE_VALUES
        for scope in reversed(feature.scopes):
            values = _read_env(self._env_path(scope))
            if key in values:
                return values[key].strip().lower() in TRUE_VALUES
        return feature.default

    def set_feature(self, key: str, enabled: bool) -> None:
        feature = FEATURE_BY_KEY.get(key)
        if feature is None:
            raise KeyError(key)
        value = "1" if enabled else "0"
        paths = tuple(self._env_path(scope) for scope in feature.scopes)
        snapshots = {path: path.read_bytes() if path.is_file() else None for path in paths}
        try:
            for path in paths:
                _update_env(path, {key: value})
        except Exception:
            self._restore_files(snapshots)
            raise
        os.environ[key] = value

    def _default_profiles(self) -> list[ProviderProfile]:
        root = _read_env(self.root_env)
        backend = _read_env(self.backend_env)
        values = {**root, **backend, **os.environ}
        try:
            credential_map = self._read_credential_map()
        except (OSError, ValueError, json.JSONDecodeError):
            credential_map = {}
        return [
            ProviderProfile("local", "Lokales MICA-Modell", "local_llama", values.get("LLAMA_MODEL", "Qwen3-4B-Q4_K_M.gguf")),
            ProviderProfile(
                "openai", "OpenAI", "openai_api",
                values.get("MICA_OPENAI_MODEL", "gpt-4.1-mini"),
                credential_map.get("OPENAI_API_KEY", "MICA_PROVIDER_OPENAI_KEY"),
            ),
            ProviderProfile(
                "gemini", "Google Gemini", "gemini",
                values.get("MICA_GEMINI_MODEL", "gemini-2.5-flash"),
                credential_map.get("GEMINI_API_KEY", credential_map.get("GOOGLE_API_KEY", "MICA_PROVIDER_GEMINI_KEY")),
            ),
        ]

    def _read_profile_document(self) -> dict:
        if not self.profiles_file.is_file():
            profiles = self._default_profiles()
            configured = (_read_env(self.backend_env).get("MICA_LLM_PROVIDER") or os.getenv("MICA_LLM_PROVIDER", "ollama")).strip().lower()
            active = {"ollama": "local", "openai_api": "openai", "gemini": "gemini"}.get(configured, "local")
            return {"schema_version": 1, "active_profile_id": active, "profiles": [asdict(item) for item in profiles]}
        data = json.loads(self.profiles_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("profiles"), list):
            raise ValueError("Die Anbieter-Konfiguration hat ein unbekanntes Format.")
        # Migrate built-in profiles created before the UI learned to reuse the
        # existing credential-name mapping. Custom profiles keep their own key.
        try:
            mapping = self._read_credential_map()
        except (OSError, ValueError, json.JSONDecodeError):
            mapping = {}
        legacy_names = {
            "openai": ("MICA_PROVIDER_OPENAI_KEY", mapping.get("OPENAI_API_KEY")),
            "gemini": (
                "MICA_PROVIDER_GEMINI_KEY",
                mapping.get("GEMINI_API_KEY") or mapping.get("GOOGLE_API_KEY"),
            ),
        }
        for raw in data["profiles"]:
            if not isinstance(raw, dict) or raw.get("id") not in legacy_names:
                continue
            legacy, mapped = legacy_names[str(raw["id"])]
            if mapped and raw.get("credential_name") == legacy:
                raw["credential_name"] = mapped
        return data

    def _write_profile_document(self, data: dict) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(self.profiles_file, json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    def profiles(self) -> list[ProviderProfile]:
        result: list[ProviderProfile] = []
        for raw in self._read_profile_document()["profiles"]:
            result.append(self._validated_profile(raw))
        return result

    def active_profile_id(self) -> str:
        return str(self._read_profile_document().get("active_profile_id") or "")

    @staticmethod
    def _validated_profile(raw: dict) -> ProviderProfile:
        if not isinstance(raw, dict):
            raise ValueError("Ungültiges Anbieterprofil.")
        profile_id = str(raw.get("id", "")).strip()
        name = str(raw.get("name", "")).strip()
        provider = str(raw.get("provider", "")).strip()
        model = str(raw.get("model", "")).strip()
        credential_name = str(raw.get("credential_name", "")).strip().upper()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", profile_id):
            raise ValueError("Ungültige Profil-ID.")
        if not name or len(name) > 80:
            raise ValueError("Der Anbietername muss 1 bis 80 Zeichen lang sein.")
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError("Dieser Anbietertyp wird nicht unterstützt.")
        if not model or len(model) > 160 or any(ch in model for ch in "\r\n"):
            raise ValueError("Der Modellname muss 1 bis 160 Zeichen lang sein.")
        if provider in PROVIDER_SECRET_ENV and not re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", credential_name):
            raise ValueError("Ungültiger Name für den sicheren API-Schlüssel.")
        if provider == "local_llama":
            credential_name = ""
        return ProviderProfile(profile_id, name, provider, model, credential_name)

    def save_profile(self, *, profile_id: str | None, name: str, provider: str, model: str) -> ProviderProfile:
        data = self._read_profile_document()
        existing = {str(item.get("id")): item for item in data["profiles"] if isinstance(item, dict)}
        if profile_id:
            profile_key = profile_id
            previous = existing.get(profile_key, {})
            previous_provider = str(previous.get("provider", ""))
            if previous_provider and previous_provider != provider:
                raise ValueError("Der Anbietertyp eines bestehenden Profils kann nicht geändert werden. Lege dafür ein neues Profil an.")
            credential_name = str(previous.get("credential_name", ""))
        else:
            profile_key = f"provider-{uuid.uuid4().hex[:12]}"
            credential_name = ""
        if provider in PROVIDER_SECRET_ENV and not credential_name:
            credential_name = f"MICA_PROV_{uuid.uuid4().hex[:16].upper()}_KEY"
        raw = {"id": profile_key, "name": name, "provider": provider, "model": model, "credential_name": credential_name}
        profile = self._validated_profile(raw)
        replaced = False
        output = []
        for item in data["profiles"]:
            if isinstance(item, dict) and item.get("id") == profile.id:
                output.append(asdict(profile))
                replaced = True
            else:
                output.append(item)
        if not replaced:
            output.append(asdict(profile))
        data["profiles"] = output
        if not data.get("active_profile_id"):
            data["active_profile_id"] = profile.id
        self._write_profile_document(data)
        return profile

    def save_active_profile(
        self,
        *,
        profile_id: str,
        name: str,
        provider: str,
        model: str,
        secret_value: str | None = None,
    ) -> ProviderProfile:
        """Atomically persist an active profile and its effective runtime config."""
        data = self._read_profile_document()
        if data.get("active_profile_id") != profile_id:
            raise ValueError("Das Profil ist nicht aktiv.")
        existing = next(
            (item for item in data["profiles"] if isinstance(item, dict) and item.get("id") == profile_id),
            None,
        )
        if existing is None:
            raise KeyError(profile_id)
        if str(existing.get("provider", "")) != provider:
            raise ValueError("Der Anbietertyp eines bestehenden Profils kann nicht geändert werden.")
        profile = self._validated_profile({
            "id": profile_id,
            "name": name,
            "provider": provider,
            "model": model,
            "credential_name": str(existing.get("credential_name", "")),
        })
        clean_secret = secret_value.strip() if secret_value is not None else None
        if provider in PROVIDER_SECRET_ENV and not clean_secret:
            present, _ = self.secret_status(profile)
            if not present:
                raise ValueError("Für diesen Anbieter muss zuerst ein API-Schlüssel gespeichert werden.")
        data["profiles"] = [
            asdict(profile) if isinstance(item, dict) and item.get("id") == profile_id else item
            for item in data["profiles"]
        ]
        mapping = self._prepared_credential_map(profile)
        updates = {"MICA_LLM_PROVIDER": "ollama" if provider == "local_llama" else provider}
        if provider == "local_llama":
            updates.update({"LLAMA_MODEL": model, "MICA_LLM_MODEL": model})
        elif provider == "openai_api":
            updates.update({"MICA_OPENAI_MODEL": model, "MICA_LLM_MODEL": model})
        else:
            updates.update({"MICA_GEMINI_MODEL": model, "MICA_LLM_MODEL": model})
        paths = (self.root_env, self.backend_env, self.profiles_file, self.credentials_file)
        snapshots = {path: path.read_bytes() if path.is_file() else None for path in paths}
        try:
            _update_env(self.root_env, updates)
            _update_env(self.backend_env, updates)
            self._write_profile_document(data)
            self._write_credential_map(mapping)
            # This is deliberately last: after a successful credential write,
            # no fallible file operation remains that could strand old runtime
            # state with a replaced key.
            if clean_secret:
                set_secret(profile.credential_name, clean_secret)
        except Exception:
            self._restore_files(snapshots)
            raise
        os.environ.update(updates)
        return profile

    def delete_profile(self, profile_id: str) -> None:
        data = self._read_profile_document()
        profiles = [self._validated_profile(item) for item in data["profiles"]]
        target = next((item for item in profiles if item.id == profile_id), None)
        if target is None:
            raise KeyError(profile_id)
        if len(profiles) <= 1:
            raise ValueError("Mindestens ein Anbieterprofil muss erhalten bleiben.")
        if data.get("active_profile_id") == profile_id:
            raise ValueError("Aktiviere zuerst ein anderes Anbieterprofil, bevor du dieses löschst.")
        remaining = [item for item in profiles if item.id != profile_id]
        data["profiles"] = [asdict(item) for item in remaining]
        mapping = self._read_credential_map()
        for env_name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            if mapping.get(env_name) == target.credential_name:
                mapping.pop(env_name, None)
        paths = (self.profiles_file, self.credentials_file)
        snapshots = {path: path.read_bytes() if path.is_file() else None for path in paths}
        try:
            self._write_profile_document(data)
            self._write_credential_map(mapping)
            # If Credential Manager rejects deletion, restore the still-valid
            # references so the user can retry from the UI.
            if target.credential_name:
                delete_secret(target.credential_name)
        except Exception:
            self._restore_files(snapshots)
            raise

    def _read_credential_map(self) -> dict[str, str]:
        if not self.credentials_file.is_file():
            return {}
        data = json.loads(self.credentials_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Ungültige Credential-Konfiguration.")
        return {str(key): str(value) for key, value in data.items()}

    def _write_credential_map(self, data: dict[str, str]) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(self.credentials_file, json.dumps(data, indent=2) + "\n")

    def _remove_credential_mapping(self, profile: ProviderProfile) -> None:
        if profile.provider not in PROVIDER_SECRET_ENV:
            return
        mapping = self._read_credential_map()
        changed = False
        for env_name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            if mapping.get(env_name) == profile.credential_name:
                mapping.pop(env_name, None)
                changed = True
        if changed:
            self._write_credential_map(mapping)

    def secret_status(self, profile: ProviderProfile) -> tuple[bool, str]:
        if profile.provider not in PROVIDER_SECRET_ENV:
            return True, "Für lokale Modelle ist kein API-Schlüssel nötig."
        try:
            present = bool(get_secret(profile.credential_name))
        except Exception as error:
            return False, f"Sicherer Speicher nicht verfügbar: {error}"
        return present, "API-Schlüssel ist sicher gespeichert." if present else "Noch kein API-Schlüssel gespeichert."

    def save_secret(self, profile: ProviderProfile, value: str) -> None:
        if profile.provider not in PROVIDER_SECRET_ENV:
            raise ValueError("Für lokale Modelle ist kein API-Schlüssel nötig.")
        # Validate and persist the non-secret mapping before replacing an
        # existing credential. If config is malformed, the running key remains
        # untouched and the UI can report a clean failure.
        if self.active_profile_id() == profile.id:
            self._write_credential_map(self._prepared_credential_map(profile))
        set_secret(profile.credential_name, value.strip())

    def delete_profile_secret(self, profile: ProviderProfile) -> None:
        if profile.provider not in PROVIDER_SECRET_ENV:
            return
        self._remove_credential_mapping(profile)
        delete_secret(profile.credential_name)

    def _map_profile_secret(self, profile: ProviderProfile) -> None:
        self._write_credential_map(self._prepared_credential_map(profile))

    def _prepared_credential_map(self, profile: ProviderProfile) -> dict[str, str]:
        env_name = PROVIDER_SECRET_ENV.get(profile.provider)
        if not env_name:
            mapping = self._read_credential_map()
            for provider_env in PROVIDER_SECRET_ENV.values():
                mapping.pop(provider_env, None)
            mapping.pop("GOOGLE_API_KEY", None)
            return mapping
        mapping = self._read_credential_map()
        mapping[env_name] = profile.credential_name
        # Only one cloud provider is active. Remove the other provider mapping
        # so stale credentials are not injected into unrelated containers.
        for other in set(PROVIDER_SECRET_ENV.values()) - {env_name}:
            mapping.pop(other, None)
        mapping.pop("GOOGLE_API_KEY", None)
        return mapping

    @staticmethod
    def _restore_files(snapshots: dict[Path, bytes | None]) -> None:
        for path, content in snapshots.items():
            try:
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = path.with_name(path.name + ".rollback.tmp")
                    temporary.write_bytes(content)
                    os.replace(temporary, path)
            except OSError:
                # Preserve the original activation error. A following start is
                # still fail-closed because cloud providers require their key.
                continue

    def activate_profile(self, profile_id: str) -> ProviderProfile:
        data = self._read_profile_document()
        profile = next((item for item in self.profiles() if item.id == profile_id), None)
        if profile is None:
            raise KeyError(profile_id)
        if profile.provider in PROVIDER_SECRET_ENV:
            present, _ = self.secret_status(profile)
            if not present:
                raise ValueError("Für diesen Anbieter muss zuerst ein API-Schlüssel gespeichert werden.")
        # Parse and validate the credential mapping before changing provider
        # state. This catches malformed JSON without a partial activation.
        prepared_mapping = self._prepared_credential_map(profile)
        updates = {"MICA_LLM_PROVIDER": "ollama" if profile.provider == "local_llama" else profile.provider}
        if profile.provider == "local_llama":
            updates["LLAMA_MODEL"] = profile.model
            updates["MICA_LLM_MODEL"] = profile.model
        elif profile.provider == "openai_api":
            updates["MICA_OPENAI_MODEL"] = profile.model
            updates["MICA_LLM_MODEL"] = profile.model
        else:
            updates["MICA_GEMINI_MODEL"] = profile.model
            updates["MICA_LLM_MODEL"] = profile.model
        data["active_profile_id"] = profile.id
        paths = (self.root_env, self.backend_env, self.profiles_file, self.credentials_file)
        snapshots = {path: path.read_bytes() if path.is_file() else None for path in paths}
        try:
            _update_env(self.root_env, updates)
            _update_env(self.backend_env, updates)
            self._write_profile_document(data)
            self._write_credential_map(prepared_mapping)
        except Exception:
            self._restore_files(snapshots)
            raise
        os.environ.update(updates)
        return profile
