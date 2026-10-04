from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from desktop.core import settings_store as module
from desktop.core.settings_store import (
    FEATURES,
    SettingsStore,
    apply_backend_configuration,
    load_desktop_feature_environment,
    stop_cloud_backend,
)


@pytest.fixture
def store(tmp_path: Path) -> SettingsStore:
    (tmp_path / "backend").mkdir()
    (tmp_path / "desktop" / "config").mkdir(parents=True)
    return SettingsStore(tmp_path)


def test_feature_toggle_preserves_env_and_uses_declared_scopes(store: SettingsStore, monkeypatch) -> None:
    store.backend_env.write_text("# keep this comment\nUNCHANGED=value\nMICA_LAYA_ENABLED=0\n", encoding="utf-8")
    store.root_env.write_text("OTHER=1\n", encoding="utf-8")
    monkeypatch.delenv("MICA_LAYA_ENABLED", raising=False)

    store.set_feature("MICA_LAYA_ENABLED", True)

    assert "# keep this comment" in store.backend_env.read_text(encoding="utf-8")
    assert "UNCHANGED=value" in store.backend_env.read_text(encoding="utf-8")
    assert store.backend_env.read_text(encoding="utf-8").count("MICA_LAYA_ENABLED=1") == 1
    assert "MICA_LAYA_ENABLED=1" in store.root_env.read_text(encoding="utf-8")
    assert store.feature_enabled("MICA_LAYA_ENABLED") is True


def test_feature_toggle_rolls_back_every_scope_when_second_write_fails(store: SettingsStore, monkeypatch) -> None:
    store.root_env.write_text("MICA_LAYA_ENABLED=0\n", encoding="utf-8")
    store.backend_env.write_text("MICA_LAYA_ENABLED=0\n", encoding="utf-8")
    original_update = module._update_env

    def fail_backend(path, updates):
        if path == store.backend_env:
            raise OSError("injected backend write failure")
        original_update(path, updates)

    monkeypatch.setattr(module, "_update_env", fail_backend)
    with pytest.raises(OSError, match="injected backend write failure"):
        store.set_feature("MICA_LAYA_ENABLED", True)

    assert store.root_env.read_text(encoding="utf-8") == "MICA_LAYA_ENABLED=0\n"
    assert store.backend_env.read_text(encoding="utf-8") == "MICA_LAYA_ENABLED=0\n"


def test_desktop_loader_only_imports_allowlisted_feature_flags(store: SettingsStore, monkeypatch) -> None:
    store.root_env.write_text(
        "MICA_WAKE_WORD_ENABLED=1\nOPENAI_API_KEY=must-not-load\nMICA_LLM_PROVIDER=gemini\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("MICA_WAKE_WORD_ENABLED", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MICA_LLM_PROVIDER", raising=False)

    load_desktop_feature_environment(store.project_root)

    assert os.environ["MICA_WAKE_WORD_ENABLED"] == "1"
    assert "OPENAI_API_KEY" not in os.environ
    assert "MICA_LLM_PROVIDER" not in os.environ


def test_provider_profile_contains_metadata_but_never_secret(store: SettingsStore, monkeypatch) -> None:
    secrets: dict[str, str] = {}
    monkeypatch.setattr(module, "set_secret", lambda name, value: secrets.__setitem__(name, value))
    monkeypatch.setattr(module, "get_secret", lambda name: secrets.get(name))
    monkeypatch.setattr(module, "delete_secret", lambda name: secrets.pop(name, None))

    profile = store.save_profile(
        profile_id=None,
        name="Privates OpenAI",
        provider="openai_api",
        model="gpt-4.1-mini",
    )
    store.save_secret(profile, "sk-test-secret")

    raw = store.profiles_file.read_text(encoding="utf-8")
    assert "sk-test-secret" not in raw
    assert "Privates OpenAI" in raw
    assert secrets[profile.credential_name] == "sk-test-secret"


def test_activation_writes_provider_model_and_secure_mapping(store: SettingsStore, monkeypatch) -> None:
    secrets: dict[str, str] = {}
    monkeypatch.setattr(module, "set_secret", lambda name, value: secrets.__setitem__(name, value))
    monkeypatch.setattr(module, "get_secret", lambda name: secrets.get(name))
    monkeypatch.setattr(module, "delete_secret", lambda name: secrets.pop(name, None))

    profile = store.save_profile(
        profile_id=None,
        name="Gemini schnell",
        provider="gemini",
        model="gemini-2.5-flash",
    )
    store.save_secret(profile, "gemini-secret")
    store.activate_profile(profile.id)

    backend = store.backend_env.read_text(encoding="utf-8")
    assert "MICA_LLM_PROVIDER=gemini" in backend
    assert "MICA_GEMINI_MODEL=gemini-2.5-flash" in backend
    mapping = json.loads(store.credentials_file.read_text(encoding="utf-8"))
    assert mapping == {"GEMINI_API_KEY": profile.credential_name}
    assert store.active_profile_id() == profile.id


def test_cloud_activation_without_key_does_not_change_environment(store: SettingsStore, monkeypatch) -> None:
    monkeypatch.setattr(module, "get_secret", lambda _name: None)
    store.backend_env.write_text("MICA_LLM_PROVIDER=ollama\n", encoding="utf-8")
    profile = store.save_profile(
        profile_id=None,
        name="OpenAI ohne Key",
        provider="openai_api",
        model="gpt-4.1-mini",
    )

    with pytest.raises(ValueError, match="API-Schlüssel"):
        store.activate_profile(profile.id)

    assert store.backend_env.read_text(encoding="utf-8") == "MICA_LLM_PROVIDER=ollama\n"


def test_existing_profile_type_is_immutable_and_active_profile_cannot_be_deleted(store: SettingsStore) -> None:
    active_id = store.active_profile_id()
    active = next(item for item in store.profiles() if item.id == active_id)

    with pytest.raises(ValueError, match="neues Profil"):
        store.save_profile(
            profile_id=active.id,
            name=active.name,
            provider="gemini" if active.provider != "gemini" else "openai_api",
            model="different-model",
        )
    with pytest.raises(ValueError, match="Aktiviere zuerst"):
        store.delete_profile(active.id)


def test_default_profiles_reuse_existing_credential_names(store: SettingsStore) -> None:
    store.credentials_file.write_text(
        json.dumps({
            "MICA_APPROVAL_SECRET": "MICA_APPROVAL_SECRET",
            "OPENAI_API_KEY": "MICA_OPENAI_API_KEY",
            "GOOGLE_API_KEY": "MICA_EXISTING_GOOGLE_KEY",
        }),
        encoding="utf-8",
    )

    profiles = {profile.id: profile for profile in store.profiles()}

    assert profiles["openai"].credential_name == "MICA_OPENAI_API_KEY"
    assert profiles["gemini"].credential_name == "MICA_EXISTING_GOOGLE_KEY"


def test_legacy_builtin_profiles_are_migrated_to_existing_credential_mapping(store: SettingsStore) -> None:
    store.credentials_file.write_text(
        json.dumps({"OPENAI_API_KEY": "MICA_OPENAI_API_KEY"}), encoding="utf-8",
    )
    store.profiles_file.write_text(json.dumps({
        "schema_version": 1,
        "active_profile_id": "local",
        "profiles": [
            {"id": "local", "name": "Lokal", "provider": "local_llama", "model": "model.gguf", "credential_name": ""},
            {"id": "openai", "name": "OpenAI", "provider": "openai_api", "model": "gpt-4.1-mini", "credential_name": "MICA_PROVIDER_OPENAI_KEY"},
        ],
    }), encoding="utf-8")

    profiles = {profile.id: profile for profile in store.profiles()}

    assert profiles["openai"].credential_name == "MICA_OPENAI_API_KEY"


def test_malformed_credential_map_cannot_partially_activate_cloud(store: SettingsStore, monkeypatch) -> None:
    secrets: dict[str, str] = {}
    monkeypatch.setattr(module, "set_secret", lambda name, value: secrets.__setitem__(name, value))
    monkeypatch.setattr(module, "get_secret", lambda name: secrets.get(name))
    store.backend_env.write_text("MICA_LLM_PROVIDER=ollama\n", encoding="utf-8")
    profile = store.save_profile(
        profile_id=None,
        name="Cloud atomar",
        provider="openai_api",
        model="gpt-4.1-mini",
    )
    store.save_secret(profile, "secret")
    store.credentials_file.write_text("{broken", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        store.activate_profile(profile.id)

    assert store.backend_env.read_text(encoding="utf-8") == "MICA_LLM_PROVIDER=ollama\n"
    assert store.active_profile_id() != profile.id


def test_active_secret_is_not_overwritten_when_mapping_validation_fails(store: SettingsStore, monkeypatch) -> None:
    secrets = {"MICA_PROVIDER_OPENAI_KEY": "old-secret"}
    monkeypatch.setattr(module, "get_secret", lambda name: secrets.get(name))
    monkeypatch.setattr(module, "set_secret", lambda name, value: secrets.__setitem__(name, value))
    profile = next(item for item in store.profiles() if item.id == "openai")
    store.credentials_file.write_text("{broken", encoding="utf-8")
    document = store._read_profile_document()
    document["active_profile_id"] = profile.id
    store._write_profile_document(document)

    with pytest.raises(json.JSONDecodeError):
        store.save_secret(profile, "new-secret")

    assert secrets[profile.credential_name] == "old-secret"


def test_secret_mapping_is_removed_before_credential_deletion(store: SettingsStore, monkeypatch) -> None:
    calls = []
    profile = next(item for item in store.profiles() if item.id == "openai")
    store.credentials_file.write_text(
        json.dumps({"OPENAI_API_KEY": profile.credential_name}), encoding="utf-8",
    )
    monkeypatch.setattr(module, "delete_secret", lambda name: calls.append(("secret", name)))
    original_write = store._write_credential_map

    def record_mapping(mapping):
        calls.append(("mapping", dict(mapping)))
        original_write(mapping)

    monkeypatch.setattr(store, "_write_credential_map", record_mapping)
    store.delete_profile_secret(profile)

    assert calls[0] == ("mapping", {})
    assert calls[1] == ("secret", profile.credential_name)


def test_profile_delete_write_failure_preserves_profile_and_secret(store: SettingsStore, monkeypatch) -> None:
    profile = next(item for item in store.profiles() if item.id == "openai")
    store.credentials_file.write_text(
        json.dumps({"OPENAI_API_KEY": profile.credential_name}), encoding="utf-8",
    )
    deleted = []
    monkeypatch.setattr(module, "delete_secret", lambda name: deleted.append(name))
    monkeypatch.setattr(
        store,
        "_write_credential_map",
        lambda _mapping: (_ for _ in ()).throw(OSError("injected write failure")),
    )

    with pytest.raises(OSError, match="injected write failure"):
        store.delete_profile(profile.id)

    assert any(item.id == profile.id for item in store.profiles())
    assert json.loads(store.credentials_file.read_text(encoding="utf-8")) == {
        "OPENAI_API_KEY": profile.credential_name,
    }
    assert deleted == []


def test_profile_delete_secret_failure_restores_files(store: SettingsStore, monkeypatch) -> None:
    profile = next(item for item in store.profiles() if item.id == "openai")
    store.credentials_file.write_text(
        json.dumps({"OPENAI_API_KEY": profile.credential_name}), encoding="utf-8",
    )
    monkeypatch.setattr(
        module,
        "delete_secret",
        lambda _name: (_ for _ in ()).throw(OSError("credential manager failure")),
    )

    with pytest.raises(OSError, match="credential manager failure"):
        store.delete_profile(profile.id)

    assert any(item.id == profile.id for item in store.profiles())
    assert json.loads(store.credentials_file.read_text(encoding="utf-8")) == {
        "OPENAI_API_KEY": profile.credential_name,
    }


def test_active_profile_update_rolls_back_profile_and_env_on_failure(store: SettingsStore, monkeypatch) -> None:
    profile = next(item for item in store.profiles() if item.id == "openai")
    document = store._read_profile_document()
    document["active_profile_id"] = profile.id
    store._write_profile_document(document)
    store.backend_env.write_text("MICA_OPENAI_MODEL=old-model\n", encoding="utf-8")
    monkeypatch.setattr(module, "get_secret", lambda _name: "existing-secret")
    original_write = store._write_credential_map

    def fail_mapping(_mapping):
        raise OSError("injected mapping failure")

    monkeypatch.setattr(store, "_write_credential_map", fail_mapping)
    with pytest.raises(OSError, match="injected mapping failure"):
        store.save_active_profile(
            profile_id=profile.id,
            name=profile.name,
            provider=profile.provider,
            model="new-model",
        )

    monkeypatch.setattr(store, "_write_credential_map", original_write)
    restored = next(item for item in store.profiles() if item.id == profile.id)
    assert restored.model == profile.model
    assert store.backend_env.read_text(encoding="utf-8") == "MICA_OPENAI_MODEL=old-model\n"


def test_backend_apply_uses_credential_aware_launcher(store: SettingsStore, monkeypatch) -> None:
    managed_python = store.project_root / ".venv-local" / "Scripts" / "python.exe"
    managed_python.parent.mkdir(parents=True)
    managed_python.write_bytes(b"")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    apply_backend_configuration(store.project_root, timeout=60)

    command, kwargs = calls[0]
    assert command == [
        str(managed_python), "-m", "backend.windows_launcher", "--",
        "up", "-d", "--build", "--force-recreate",
    ]
    assert kwargs["cwd"] == store.project_root
    assert kwargs["shell"] is False


def test_cloud_backend_stop_targets_every_service_that_receives_provider_keys(store: SettingsStore, monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    stop_cloud_backend(store.project_root, timeout=60)

    assert calls[0][0][-4:] == ["--", "stop", "mica-api", "tts"]


def test_feature_menu_only_lists_capabilities_reachable_from_supported_runtime() -> None:
    keys = {feature.key for feature in FEATURES}
    assert "MICA_CUA_ENABLED" not in keys
    assert "MICA_SELF_EDIT_ENABLED" not in keys
    assert "MICA_OPENSEO_ENABLED" not in keys


def test_ui_exposes_feature_and_provider_settings_without_plaintext_key_storage() -> None:
    desktop = Path(__file__).parents[1] / "desktop"
    source = "\n".join((desktop / name).read_text(encoding="utf-8")
                       for name in ("ui.py", "ui_settings.py"))
    assert '"Funktionen", "Mica-Features einzeln aktivieren oder deaktivieren"' in source
    assert '"KI-Anbieter & Modelle", "Anbieter, Modelle und API-Schlüssel verwalten"' in source
    assert "QLineEdit.EchoMode.Password" in source
    assert "FeatureSettingsOverlay" in source
    assert "ProviderSettingsOverlay" in source
    assert "activation_requested" in source
    assert "feature_changed" in source
    assert "key_removed" in source
