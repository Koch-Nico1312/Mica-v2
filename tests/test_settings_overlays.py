from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMainWindow

from desktop import ui
import core.settings_store as runtime_settings


APP = QApplication.instance() or QApplication([])


class FeatureStore:
    def __init__(self):
        self.values = {feature.key: feature.default for feature in runtime_settings.FEATURES}
        self.writes = []

    def feature_enabled(self, key):
        return self.values[key]

    def set_feature(self, key, enabled):
        self.values[key] = enabled
        self.writes.append((key, enabled))


class ProviderStore:
    def __init__(self):
        self.profile = SimpleNamespace(
            id="openai", name="OpenAI", provider="openai_api",
            model="gpt-4.1-mini", credential_name="MICA_OPENAI_API_KEY",
        )
        self.saved_secrets = []
        self.deleted_secrets = []
        self.activations = []
        self.active_id = self.profile.id

    def profiles(self):
        return [self.profile]

    def active_profile_id(self):
        return self.active_id

    def secret_status(self, _profile):
        return True, "API-Schlüssel ist sicher gespeichert."

    def save_profile(self, **values):
        self.profile.name = values["name"]
        self.profile.model = values["model"]
        return self.profile

    def save_secret(self, profile, value):
        self.saved_secrets.append((profile.id, value))

    def activate_profile(self, _profile_id):
        self.activations.append(_profile_id)
        self.active_id = _profile_id
        return self.profile

    def save_active_profile(self, *, profile_id, name, provider, model, secret_value=None):
        self.profile.name = name
        self.profile.model = model
        if secret_value:
            self.saved_secrets.append((profile_id, secret_value))
        self.activations.append(profile_id)
        return self.profile

    def delete_profile_secret(self, profile):
        self.deleted_secrets.append(profile.id)


def test_backend_feature_toggle_requests_real_backend_update(monkeypatch) -> None:
    store = FeatureStore()
    monkeypatch.setattr(runtime_settings, "SettingsStore", lambda: store)
    overlay = ui.FeatureSettingsOverlay()
    events = []
    overlay.feature_changed.connect(lambda key, enabled, backend: events.append((key, enabled, backend)))

    overlay._toggle("MICA_LAYA_ENABLED", overlay._buttons["MICA_LAYA_ENABLED"])

    assert store.writes[-1] == ("MICA_LAYA_ENABLED", True)
    assert events[-1] == ("MICA_LAYA_ENABLED", True, True)
    assert all(not button.isEnabled() for button in overlay._buttons.values())


def test_active_key_update_requests_container_recreation(monkeypatch) -> None:
    store = ProviderStore()
    monkeypatch.setattr(runtime_settings, "SettingsStore", lambda: store)
    overlay = ui.ProviderSettingsOverlay()
    events = []
    overlay.activation_requested.connect(lambda action, name: events.append((action, name)))
    overlay._key.setText("replacement-secret")

    overlay._save()

    assert store.saved_secrets == [("openai", "replacement-secret")]
    assert events == [("key_updated", "OpenAI")]
    assert not overlay._activate_btn.isEnabled()


def test_active_key_removal_requests_container_recreation(monkeypatch) -> None:
    store = ProviderStore()
    monkeypatch.setattr(runtime_settings, "SettingsStore", lambda: store)
    overlay = ui.ProviderSettingsOverlay()
    events = []
    overlay.activation_requested.connect(lambda action, name: events.append((action, name)))
    overlay._key_delete_armed = True

    overlay._delete_key()

    assert store.deleted_secrets == ["openai"]
    assert events == [("key_removed", "OpenAI")]
    assert not overlay._activate_btn.isEnabled()


def test_active_model_edit_reactivates_profile_and_recreates_backend(monkeypatch) -> None:
    store = ProviderStore()
    monkeypatch.setattr(runtime_settings, "SettingsStore", lambda: store)
    overlay = ui.ProviderSettingsOverlay()
    events = []
    overlay.activation_requested.connect(lambda action, name: events.append((action, name)))
    overlay._model.setEditText("gpt-5-mini")

    overlay._save()

    assert store.activations == ["openai"]
    assert events == [("provider_updated", "OpenAI")]
    assert not overlay._activate_btn.isEnabled()


def test_activate_button_uses_atomic_path_for_active_key_update(monkeypatch) -> None:
    store = ProviderStore()
    monkeypatch.setattr(runtime_settings, "SettingsStore", lambda: store)
    overlay = ui.ProviderSettingsOverlay()
    events = []
    overlay.activation_requested.connect(lambda action, name: events.append((action, name)))
    overlay._key.setText("rotated-secret")

    overlay._activate()

    assert store.saved_secrets == [("openai", "rotated-secret")]
    assert store.activations == ["openai"]
    assert events == [("key_updated", "OpenAI")]


def test_active_key_commit_still_requests_backend_when_ui_reload_fails(monkeypatch) -> None:
    store = ProviderStore()
    monkeypatch.setattr(runtime_settings, "SettingsStore", lambda: store)
    overlay = ui.ProviderSettingsOverlay()
    events = []
    overlay.activation_requested.connect(lambda action, name: events.append((action, name)))
    overlay._key.setText("rotated-secret")
    monkeypatch.setattr(
        overlay,
        "_reload_profiles",
        lambda *_args: (_ for _ in ()).throw(OSError("injected reload failure")),
    )

    overlay._save()

    assert events == [("key_updated", "OpenAI")]
    assert "Ansicht konnte nicht aktualisiert" in overlay._key_status.text()


def test_newly_activated_profile_requests_backend_before_ui_reload(monkeypatch) -> None:
    store = ProviderStore()
    store.active_id = "different-profile"
    monkeypatch.setattr(runtime_settings, "SettingsStore", lambda: store)
    overlay = ui.ProviderSettingsOverlay()
    events = []
    overlay.activation_requested.connect(lambda action, name: events.append((action, name)))
    monkeypatch.setattr(
        overlay,
        "_reload_profiles",
        lambda *_args: (_ for _ in ()).throw(OSError("injected reload failure")),
    )

    overlay._activate()

    assert events == [("provider_activated", "OpenAI")]
    assert store.active_id == "openai"


def test_parallel_feature_and_credential_updates_are_serialized(monkeypatch) -> None:
    window = ui.MainWindow.__new__(ui.MainWindow)
    QMainWindow.__init__(window)
    window._provider_backend_busy = False
    window._pending_backend_updates = []
    window._log = SimpleNamespace(append_log=lambda _message: None)
    window._feature_settings_overlay = SimpleNamespace(
        backend_activation_finished=lambda *_args: None,
        backend_activation_queued=lambda *_args: None,
    )
    provider_events = []
    window._provider_settings_overlay = SimpleNamespace(
        backend_activation_finished=lambda *args: provider_events.append(("finished", args)),
        backend_activation_queued=lambda *args: provider_events.append(("queued", args)),
    )
    urgent_stops = []
    window._stop_cloud_backend_urgent = lambda: urgent_stops.append(True)
    workers = []

    class DeferredThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            workers.append(self.target)

    monkeypatch.setattr(ui.threading, "Thread", DeferredThread)

    window._start_backend_update("feature", "MICA_LAYA_ENABLED")
    window._start_backend_update("provider", "key_removed:OpenAI")

    assert len(workers) == 1
    assert window._pending_backend_updates == [("provider", "key_removed:OpenAI")]
    assert provider_events[0][0] == "queued"
    assert urgent_stops == [True]

    window._on_backend_update_result("feature", True, "feature done")

    assert len(workers) == 2
    assert window._pending_backend_updates == []
    assert window._provider_backend_busy is True
