from __future__ import annotations
import threading
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QStyle, QVBoxLayout, QWidget
from desktop.ui_theme import style_toggle_button
from desktop.ui_theme import C

class _HudOverlay(QWidget):
    """Base for the floating panels placed by hand over the HUD.

    They are children of the central widget but sit in no layout, so Qt never
    invalidates the region they occupy when they hide or shrink: the HUD keeps
    painting around them and their last frame stays on screen as a ghost. Any
    overlay positioned with _centre_overlay needs this."""

    def hideEvent(self, e):
        p = self.parentWidget()
        if p is not None:
            # Repaint exactly what we were covering, before we stop covering it.
            p.update(self.geometry())
        super().hideEvent(e)

    def closeEvent(self, e):
        p = self.parentWidget()
        if p is not None:
            p.update(self.geometry())
        super().closeEvent(e)

class FeatureSettingsOverlay(_HudOverlay):
    """Scrollable feature switches backed by the real MICA environment flags."""

    feature_changed = pyqtSignal(str, bool, bool)
    _OW = 760
    _OH = 640

    def __init__(self, parent=None):
        super().__init__(parent)
        from desktop.core.settings_store import FEATURES, SettingsStore

        self._store = SettingsStore()
        self._buttons: dict[str, QPushButton] = {}
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedSize(self._OW, self._OH)
        self.setStyleSheet(f"""
            FeatureSettingsOverlay {{ background: {C.PANEL}; border: 1px solid {C.BORDER}; border-radius: 20px; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        title = QLabel("Funktionen")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        root.addWidget(title)
        note = QLabel("Aktiviere nur, was Mica verwenden darf. Backend-Funktionen werden automatisch aktualisiert.")
        note.setWordWrap(True)
        note.setFont(QFont("Segoe UI", 9))
        note.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        root.addWidget(note)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        rows = QVBoxLayout(content)
        rows.setContentsMargins(0, 4, 8, 4)
        rows.setSpacing(8)
        category = ""
        for feature in FEATURES:
            if feature.category != category:
                category = feature.category
                heading = QLabel(category)
                heading.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
                heading.setStyleSheet(f"color: {C.PRI}; background: transparent; padding-top: 7px;")
                rows.addWidget(heading)
            card = QFrame()
            card.setObjectName("FeatureCard")
            card.setStyleSheet(f"QFrame#FeatureCard {{ background: {C.BG}; border: 1px solid {C.BORDER}; border-radius: 12px; }}")
            line = QHBoxLayout(card)
            line.setContentsMargins(14, 10, 12, 10)
            text_box = QVBoxLayout(); text_box.setSpacing(2)
            name = QLabel(feature.title)
            name.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            name.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
            detail = QLabel(feature.description)
            detail.setWordWrap(True)
            detail.setFont(QFont("Segoe UI", 8))
            detail.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            text_box.addWidget(name); text_box.addWidget(detail)
            line.addLayout(text_box, stretch=1)
            button = QPushButton()
            button.setFixedSize(82, 34)
            button.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            enabled = self._store.feature_enabled(feature.key)
            self._style_toggle(button, enabled)
            button.clicked.connect(lambda _, key=feature.key, b=button: self._toggle(key, b))
            self._buttons[feature.key] = button
            line.addWidget(button)
            rows.addWidget(card)
        rows.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setFont(QFont("Segoe UI", 8))
        self._status.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        root.addWidget(self._status)
        close = QPushButton("Schließen")
        close.setFixedHeight(38)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(f"QPushButton {{ background: {C.PRI}; color: white; border: none; border-radius: 10px; }} QPushButton:hover {{ background: {C.PRI_DIM}; }}")
        close.clicked.connect(self.hide)
        root.addWidget(close)

    _style_toggle = staticmethod(style_toggle_button)

    def _toggle(self, key: str, button: QPushButton) -> None:
        try:
            from desktop.core.settings_store import FEATURE_BY_KEY
            enabled = not self._store.feature_enabled(key)
            self._store.set_feature(key, enabled)
            self._style_toggle(button, enabled)
            self._status.setStyleSheet(f"color: {C.GREEN_D}; background: transparent;")
            needs_backend = "backend" in FEATURE_BY_KEY[key].scopes
            if needs_backend:
                for toggle in self._buttons.values():
                    toggle.setEnabled(False)
                self._status.setText("Gespeichert. Das MICA-Backend wird neu gebaut und aktualisiert …")
            else:
                self._status.setText("Gespeichert und sofort angewendet.")
            self.feature_changed.emit(key, enabled, needs_backend)
        except Exception as error:
            self._status.setStyleSheet(f"color: {C.RED}; background: transparent;")
            self._status.setText(f"Konnte nicht gespeichert werden: {error}")

    def backend_activation_finished(self, success: bool, message: str) -> None:
        for toggle in self._buttons.values():
            toggle.setEnabled(True)
        self._status.setStyleSheet(f"color: {C.GREEN_D if success else C.RED}; background: transparent;")
        self._status.setText(message)

    def backend_activation_queued(self, message: str) -> None:
        for toggle in self._buttons.values():
            toggle.setEnabled(False)
        self._status.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._status.setText(message)

class ProviderSettingsOverlay(_HudOverlay):
    """Manage provider profiles, models and Credential-Manager secrets."""

    activation_requested = pyqtSignal(str, str)
    _OW = 720
    _OH = 620

    def __init__(self, parent=None):
        super().__init__(parent)
        from desktop.core.settings_store import SettingsStore

        self._store = SettingsStore()
        self._profile_id: str | None = None
        self._delete_armed = False
        self._key_delete_armed = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedSize(self._OW, self._OH)
        self.setStyleSheet(f"""
            ProviderSettingsOverlay {{ background: {C.PANEL}; border: 1px solid {C.BORDER}; border-radius: 20px; }}
            ProviderSettingsOverlay QLineEdit, ProviderSettingsOverlay QComboBox {{
                background: {C.PANEL}; color: {C.TEXT}; border: 1px solid {C.BORDER};
                border-radius: 9px; padding: 7px 10px;
            }}
            ProviderSettingsOverlay QLineEdit:focus, ProviderSettingsOverlay QComboBox:focus {{ border-color: {C.PRI}; }}
            ProviderSettingsOverlay QPushButton {{
                background: {C.PANEL}; color: {C.TEXT}; border: 1px solid {C.BORDER};
                border-radius: 9px; padding: 6px 10px;
            }}
            ProviderSettingsOverlay QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.BORDER_B}; }}
            ProviderSettingsOverlay QPushButton:disabled {{ color: {C.TEXT_DIM}; background: {C.BG}; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(10)
        title = QLabel("KI-Anbieter & Modelle")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        root.addWidget(title)
        intro = QLabel("Profile hinzufügen, Modelle auswählen und API-Schlüssel sicher verwalten. Schlüssel werden nie in Projektdateien gespeichert.")
        intro.setWordWrap(True)
        intro.setFont(QFont("Segoe UI", 9))
        intro.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        root.addWidget(intro)

        select_row = QHBoxLayout(); select_row.setSpacing(8)
        self._profiles = QComboBox()
        self._profiles.setMinimumHeight(38)
        self._profiles.currentIndexChanged.connect(self._load_selected)
        select_row.addWidget(self._profiles, stretch=1)
        new_btn = QPushButton("+ Anbieter hinzufügen")
        new_btn.setFixedHeight(38)
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.clicked.connect(self._new_profile)
        select_row.addWidget(new_btn)
        root.addLayout(select_row)

        self._active = QLabel("")
        self._active.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        self._active.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        root.addWidget(self._active)

        form = QFrame()
        form.setObjectName("ProviderForm")
        form.setStyleSheet(f"QFrame#ProviderForm {{ background: {C.BG}; border: 1px solid {C.BORDER}; border-radius: 14px; }} QLabel {{ background: transparent; color: {C.TEXT_MED}; }}")
        fields = QVBoxLayout(form)
        fields.setContentsMargins(16, 14, 16, 14)
        fields.setSpacing(7)
        fields.addWidget(QLabel("Anzeigename"))
        self._name = QLineEdit(); self._name.setPlaceholderText("z. B. Mein OpenAI-Profil")
        fields.addWidget(self._name)
        fields.addWidget(QLabel("Anbietertyp"))
        self._type = QComboBox()
        from desktop.core.settings_store import PROVIDER_LABELS
        for value, label in PROVIDER_LABELS.items():
            self._type.addItem(label, value)
        self._type.currentIndexChanged.connect(self._provider_type_changed)
        fields.addWidget(self._type)
        fields.addWidget(QLabel("Modell"))
        self._model = QComboBox(); self._model.setEditable(True)
        self._model.lineEdit().setPlaceholderText("Modellname")
        fields.addWidget(self._model)
        fields.addWidget(QLabel("API-Schlüssel"))
        key_row = QHBoxLayout(); key_row.setSpacing(8)
        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._key.setPlaceholderText("Leer lassen, um den gespeicherten Schlüssel zu behalten")
        key_row.addWidget(self._key, stretch=1)
        self._remove_key = QPushButton("Schlüssel entfernen")
        self._remove_key.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_key.clicked.connect(self._delete_key)
        key_row.addWidget(self._remove_key)
        fields.addLayout(key_row)
        self._key_status = QLabel("")
        self._key_status.setWordWrap(True)
        self._key_status.setFont(QFont("Segoe UI", 8))
        fields.addWidget(self._key_status)
        root.addWidget(form)

        actions = QHBoxLayout(); actions.setSpacing(8)
        self._save_btn = QPushButton("Speichern")
        self._activate_btn = QPushButton("Speichern & aktivieren")
        self._delete_btn = QPushButton("Anbieter löschen")
        for button in (self._save_btn, self._activate_btn, self._delete_btn):
            button.setFixedHeight(38); button.setCursor(Qt.CursorShape.PointingHandCursor)
            actions.addWidget(button)
        self._save_btn.clicked.connect(self._save)
        self._activate_btn.clicked.connect(self._activate)
        self._delete_btn.clicked.connect(self._delete_profile)
        root.addLayout(actions)
        self._status = QLabel("Änderungen am aktiven Backend werden nach einem Neustart wirksam.")
        self._status.setWordWrap(True)
        self._status.setFont(QFont("Segoe UI", 8))
        self._status.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        root.addWidget(self._status)
        close = QPushButton("Schließen")
        close.setFixedHeight(38); close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(f"QPushButton {{ background: {C.PRI}; color: white; border: none; border-radius: 10px; }} QPushButton:hover {{ background: {C.PRI_DIM}; }}")
        close.clicked.connect(self.hide)
        root.addWidget(close)
        self._reload_profiles()

    def _set_status(self, text: str, error: bool = False) -> None:
        self._status.setStyleSheet(f"color: {C.RED if error else C.GREEN_D}; background: transparent;")
        self._status.setText(text)

    def _reload_profiles(self, select_id: str | None = None) -> None:
        selected = select_id or self._profile_id or self._store.active_profile_id()
        self._profiles.blockSignals(True)
        self._profiles.clear()
        for profile in self._store.profiles():
            suffix = "  • aktiv" if profile.id == self._store.active_profile_id() else ""
            self._profiles.addItem(profile.name + suffix, profile.id)
        index = self._profiles.findData(selected)
        self._profiles.setCurrentIndex(max(0, index))
        self._profiles.blockSignals(False)
        self._load_selected()

    def _load_selected(self, *_args) -> None:
        profile_id = self._profiles.currentData()
        profile = next((item for item in self._store.profiles() if item.id == profile_id), None)
        if profile is None:
            return
        self._profile_id = profile.id
        self._name.setText(profile.name)
        self._type.setCurrentIndex(self._type.findData(profile.provider))
        self._type.setEnabled(False)
        self._provider_type_changed(profile.model)
        self._key.clear()
        self._active.setText("Aktives Profil" if profile.id == self._store.active_profile_id() else "Nicht aktiv")
        present, message = self._store.secret_status(profile)
        self._key_status.setStyleSheet(f"color: {C.GREEN_D if present else C.TEXT_MED}; background: transparent;")
        self._key_status.setText(message)
        self._delete_armed = False; self._key_delete_armed = False
        self._delete_btn.setText("Anbieter löschen")
        self._delete_btn.setEnabled(True)
        self._remove_key.setText("Schlüssel entfernen")

    def _provider_type_changed(self, model: str | None = None) -> None:
        from desktop.core.settings_store import MODEL_SUGGESTIONS
        provider = self._type.currentData()
        current = model if isinstance(model, str) else self._model.currentText()
        self._model.blockSignals(True)
        self._model.clear()
        self._model.addItems(MODEL_SUGGESTIONS.get(provider, ()))
        self._model.setEditText(current or (self._model.itemText(0) if self._model.count() else ""))
        self._model.blockSignals(False)
        cloud = provider != "local_llama"
        self._key.setEnabled(cloud)
        self._remove_key.setEnabled(cloud and self._profile_id is not None)
        if not cloud:
            self._key_status.setText("Für lokale Modelle ist kein API-Schlüssel nötig.")

    def _new_profile(self) -> None:
        self._profile_id = None
        self._profiles.setCurrentIndex(-1)
        self._name.clear()
        self._type.setCurrentIndex(0)
        self._type.setEnabled(True)
        self._provider_type_changed()
        self._key.clear()
        self._active.setText("Neues Profil")
        self._key_status.setText("Der Schlüssel wird erst beim Speichern sicher hinterlegt.")
        self._delete_btn.setEnabled(False)
        self._remove_key.setEnabled(False)

    def _save_profile(self):
        key_changed = bool(self._key.text().strip())
        profile = self._store.save_profile(
            profile_id=self._profile_id,
            name=self._name.text().strip(),
            provider=str(self._type.currentData()),
            model=self._model.currentText().strip(),
        )
        if self._key.text().strip():
            self._store.save_secret(profile, self._key.text())
            self._key.clear()
        self._profile_id = profile.id
        return profile, key_changed

    def _reload_profiles_after_commit(self, profile_id: str) -> None:
        """Refresh presentation state without invalidating a committed backend change."""
        try:
            self._reload_profiles(profile_id)
            self._delete_btn.setEnabled(True)
        except Exception as error:
            self._key_status.setStyleSheet(f"color: {C.RED}; background: transparent;")
            self._key_status.setText(f"Gespeichert; Ansicht konnte nicht aktualisiert werden: {error}")

    def _begin_backend_activation(self, action: str, profile_name: str, message: str) -> None:
        self._save_btn.setEnabled(False)
        self._activate_btn.setEnabled(False)
        self._remove_key.setEnabled(False)
        self._set_status(message)
        self.activation_requested.emit(action, profile_name)

    def _save(self, *_args) -> None:
        try:
            previous = next(
                (item for item in self._store.profiles() if item.id == self._profile_id),
                None,
            )
            previous_runtime = (
                (previous.provider, previous.model) if previous is not None else None
            )
            key_value = self._key.text().strip()
            key_changed = bool(key_value)
            if self._profile_id and self._profile_id == self._store.active_profile_id():
                profile = self._store.save_active_profile(
                    profile_id=self._profile_id,
                    name=self._name.text().strip(),
                    provider=str(self._type.currentData()),
                    model=self._model.currentText().strip(),
                    secret_value=key_value or None,
                )
                self._key.clear()
            else:
                profile, key_changed = self._save_profile()
            runtime_changed = previous_runtime is not None and previous_runtime != (
                profile.provider,
                profile.model,
            )
            if profile.id == self._store.active_profile_id() and (key_changed or runtime_changed):
                action = "key_updated" if key_changed else "provider_updated"
                self._begin_backend_activation(
                    action, profile.name,
                    "Aktives Anbieterprofil gespeichert. Cloud-Container werden sicher neu erstellt …",
                )
                self._reload_profiles_after_commit(profile.id)
            else:
                self._reload_profiles_after_commit(profile.id)
                self._set_status("Anbieterprofil sicher gespeichert.")
        except Exception as error:
            self._set_status(f"Konnte nicht gespeichert werden: {error}", True)

    def _activate(self, *_args) -> None:
        try:
            key_value = self._key.text().strip()
            key_changed = bool(key_value)
            if self._profile_id and self._profile_id == self._store.active_profile_id():
                profile = self._store.save_active_profile(
                    profile_id=self._profile_id,
                    name=self._name.text().strip(),
                    provider=str(self._type.currentData()),
                    model=self._model.currentText().strip(),
                    secret_value=key_value or None,
                )
                self._key.clear()
            else:
                profile, key_changed = self._save_profile()
                self._store.activate_profile(profile.id)
            self._begin_backend_activation(
                "key_updated" if key_changed else "provider_activated", profile.name,
                "Anbieter gespeichert. Das MICA-Backend wird sicher aktualisiert …",
            )
            self._reload_profiles_after_commit(profile.id)
        except Exception as error:
            self._set_status(f"Konnte nicht aktiviert werden: {error}", True)

    def backend_activation_finished(self, success: bool, message: str) -> None:
        self._save_btn.setEnabled(True)
        self._activate_btn.setEnabled(True)
        self._provider_type_changed()
        self._set_status(message, not success)

    def backend_activation_queued(self, message: str) -> None:
        self._save_btn.setEnabled(False)
        self._activate_btn.setEnabled(False)
        self._remove_key.setEnabled(False)
        self._set_status(message)

    def _delete_profile(self, *_args) -> None:
        if not self._profile_id:
            return
        if not self._delete_armed:
            self._delete_armed = True
            self._delete_btn.setText("Wirklich löschen?")
            self._set_status("Nochmal auf „Wirklich löschen?“ klicken. Ein gespeicherter Schlüssel wird ebenfalls entfernt.")
            return
        try:
            self._store.delete_profile(self._profile_id)
            self._profile_id = None
            self._reload_profiles()
            self._set_status("Anbieterprofil und zugehöriger Schlüssel wurden entfernt.")
        except Exception as error:
            self._set_status(f"Konnte nicht gelöscht werden: {error}", True)

    def _delete_key(self, *_args) -> None:
        profile = next((item for item in self._store.profiles() if item.id == self._profile_id), None)
        if profile is None:
            return
        if not self._key_delete_armed:
            self._key_delete_armed = True
            self._remove_key.setText("Wirklich entfernen?")
            self._set_status("Nochmal klicken, um den API-Schlüssel aus dem sicheren Speicher zu entfernen.")
            return
        try:
            self._store.delete_profile_secret(profile)
            self._load_selected()
            if profile.id == self._store.active_profile_id():
                self._begin_backend_activation(
                    "key_removed", profile.name,
                    "Schlüssel entfernt. Cloud-Container werden ohne den alten Schlüssel neu erstellt …",
                )
            else:
                self._set_status("API-Schlüssel aus dem Windows-Anmeldespeicher entfernt.")
        except Exception as error:
            if profile.id == self._store.active_profile_id():
                self._save_btn.setEnabled(False)
                self._activate_btn.setEnabled(False)
                self._remove_key.setEnabled(False)
                self._set_status(
                    f"Konnte den Schlüssel nicht vollständig entfernen: {error} "
                    "Cloud-Container werden vorsichtshalber gestoppt …",
                    True,
                )
                self.activation_requested.emit("credential_failure", profile.name)
            else:
                self._set_status(f"Konnte den Schlüssel nicht entfernen: {error}", True)

class ConfirmBanner(_HudOverlay):
    """The gate in front of an action that cannot be taken back.

    The old confirmation was a tool parameter the model filled in itself, which
    means it confirmed its own shutdown requests. This is the interface asking,
    and the answer travels from a human finger to core/confirm.py without the
    model in the loop. Nothing blocks while it is up: the assistant keeps
    talking, so this costs no latency — unlike the old gate, which spent two
    tool round trips on every power command."""

    answered = pyqtSignal(bool)
    _OW = 430

    def __init__(self, title: str, detail: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            ConfirmBanner {{
                background: {C.PANEL};
                border: 1px solid #f0c5cc;
                border-radius: 18px;
            }}
        """)
        self.setFixedWidth(self._OW)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)

        hdr = QLabel("Aktion bestätigen")
        hdr.setFont(QFont("Segoe UI", 13, QFont.Weight.DemiBold))
        hdr.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        lay.addWidget(hdr)

        ttl = QLabel(title)
        ttl.setWordWrap(True)
        ttl.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        ttl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        lay.addWidget(ttl)

        if detail:
            dtl = QLabel(detail)
            dtl.setWordWrap(True)
            dtl.setFont(QFont("Segoe UI", 9))
            dtl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            lay.addWidget(dtl)

        row = QHBoxLayout(); row.setSpacing(8)

        yes = QPushButton("Bestätigen")
        yes.setFixedHeight(38)
        yes.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        yes.setCursor(Qt.CursorShape.PointingHandCursor)
        yes.setStyleSheet(f"""
            QPushButton {{ background: {C.RED}; color: white;
                border: 1px solid {C.RED}; border-radius: 10px; }}
            QPushButton:hover {{ background: #c95e70; }}
        """)
        yes.clicked.connect(lambda: self.answered.emit(True))
        row.addWidget(yes)

        no = QPushButton("Abbrechen")
        no.setFixedHeight(38)
        no.setFont(QFont("Segoe UI", 9))
        no.setCursor(Qt.CursorShape.PointingHandCursor)
        no.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 10px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        no.clicked.connect(lambda: self.answered.emit(False))
        row.addWidget(no)
        lay.addLayout(row)

        # Default focus on CANCEL: if someone hits Enter without reading, the
        # safe answer wins.
        no.setDefault(True)
        no.setFocus()

class AudioDeviceOverlay(_HudOverlay):
    """Choose which microphone JARVIS listens to and which speakers it uses.

    Both audio streams used to open with no `device=` at all, so they always
    took the OS default — which on Windows moves by itself the moment a headset
    is plugged in. 'JARVIS can't hear me' is usually 'JARVIS is listening to the
    webcam'."""

    picked = pyqtSignal()      # emitted after Apply, when something changed
    voice_settings_requested = pyqtSignal()
    _devices_ready = pyqtSignal(dict)
    _OW = 460

    def __init__(self, parent=None):
        super().__init__(parent)
        from desktop.core.audio_devices import cached_devices
        from desktop.memory.config_manager import get_input_device, get_output_device

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            AudioDeviceOverlay {{
                background: {C.PANEL};
                border: 1px solid {C.BORDER};
                border-radius: 18px;
            }}
        """)
        self.setFixedWidth(self._OW)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)

        hdr = QLabel("Audio-Geraete")
        hdr.setFont(QFont("Segoe UI", 16, QFont.Weight.DemiBold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        lay.addWidget(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        _combo_css = (
            f"QComboBox {{ background: {C.PANEL2}; color: {C.TEXT}; "
            f"border: 1px solid {C.BORDER}; border-radius: 10px; padding: 7px 10px; }}"
            f"QComboBox:hover {{ border-color: {C.BORDER_B}; }}"
            f"QComboBox QAbstractItemView {{ background: {C.PANEL}; color: {C.TEXT}; "
            f"selection-background-color: {C.PRI_GHO}; border: 1px solid {C.BORDER}; }}"
        )

        inventory = cached_devices()

        def _row(label: str, kind: str, current: str) -> QComboBox:
            cap = QLabel(label)
            cap.setFont(QFont("Courier New", 8))
            cap.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            lay.addWidget(cap)

            box = QComboBox()
            box.setFont(QFont("Segoe UI", 9))
            box.setFixedHeight(30)
            box.setStyleSheet(_combo_css)
            # The list is served from a cache warmed on a background thread at
            # startup, so opening this panel never blocks the Qt thread on the
            # host audio API.
            box.addItem("Systemstandard", "")
            for name in inventory[kind]:
                box.addItem(name, name)
            idx = box.findData(current) if current else 0
            box.setCurrentIndex(idx if idx >= 0 else 0)
            if current and idx < 0:
                # Saved device is not plugged in right now. Show it rather than
                # silently resetting the user's choice to default.
                box.addItem(f"{current} (nicht verbunden)", current)
                box.setCurrentIndex(box.count() - 1)
            lay.addWidget(box)
            return box

        self._in_box  = _row("Mikrofon",
                             "input", get_input_device())
        lay.addSpacing(4)
        self._out_box = _row("Lautsprecher",
                             "output", get_output_device())

        note = QLabel("Geraete werden gesucht ...")
        note.setWordWrap(True)
        note.setFont(QFont("Segoe UI", 9))
        note.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        lay.addSpacing(6)
        lay.addWidget(note)
        self._device_status = note

        voice_setup = QPushButton("Sprache einrichten: Mikrofontest, Satzende und Diagnose")
        voice_setup.setMinimumHeight(34)
        voice_setup.clicked.connect(self._voice_setup)
        lay.addWidget(voice_setup)

        row = QHBoxLayout(); row.setSpacing(8)
        self._refresh_button = QPushButton()
        self._refresh_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self._refresh_button.setToolTip("Audio-Geraete aktualisieren")
        self._refresh_button.setFixedSize(32, 32)
        self._refresh_button.clicked.connect(self._load_devices)
        row.addWidget(self._refresh_button)
        ok = QPushButton("Uebernehmen")
        ok.setFixedHeight(32)
        ok.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px; }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.PRI}; }}
        """)
        ok.clicked.connect(self._apply)
        self._apply_button = ok
        row.addWidget(ok)

        cancel = QPushButton("Schliessen")
        cancel.setFixedHeight(32)
        cancel.setFont(QFont("Segoe UI", 9))
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        cancel.clicked.connect(self.hide)
        row.addWidget(cancel)
        lay.addLayout(row)
        self._loading = False
        self._devices_ready.connect(self._populate_devices)
        QTimer.singleShot(0, self._load_devices)

    def _load_devices(self):
        if self._loading:
            return
        self._loading = True
        self._refresh_button.setEnabled(False)
        self._apply_button.setEnabled(False)
        self._device_status.setText("Geraete werden gesucht ...")

        def discover():
            from desktop.core.audio_devices import cached_devices, list_devices
            list_devices("input", refresh=True)
            try:
                self._devices_ready.emit(cached_devices())
            except RuntimeError:
                pass  # The parent window may have closed during enumeration.

        threading.Thread(target=discover, name="mica-audio-inventory", daemon=True).start()

    def _voice_setup(self):
        self.hide()
        self.voice_settings_requested.emit()

    def _populate_devices(self, inventory: dict):
        for kind, box in (("input", self._in_box), ("output", self._out_box)):
            current = box.currentData() or ""
            box.clear()
            box.addItem("Systemstandard", "")
            for name in inventory.get(kind, []):
                box.addItem(name, name)
            index = box.findData(current)
            if current and index < 0:
                box.addItem(f"{current} (nicht verbunden)", current)
                index = box.count() - 1
            box.setCurrentIndex(max(0, index))
        self._loading = False
        self._refresh_button.setEnabled(True)
        self._apply_button.setEnabled(True)
        count = len(inventory.get("input", [])) + len(inventory.get("output", []))
        self._device_status.setText("Geraete aktualisiert." if count else "Keine Audio-Geraete gefunden.")

    def _apply(self):
        from desktop.memory.config_manager import (
            get_input_device, get_output_device,
            save_input_device, save_output_device,
        )
        new_in  = self._in_box.currentData()  or ""
        new_out = self._out_box.currentData() or ""
        changed = (new_in != get_input_device()) or (new_out != get_output_device())
        save_input_device(new_in)
        save_output_device(new_out)
        self.hide()
        # Only rebuild the session if something actually moved — a no-op Apply
        # should not cost a reconnect.
        if changed:
            self.picked.emit()

class MemoryOverlay(_HudOverlay):
    """Everything JARVIS has stored about you, and when it learned it.

    Memory used to be a 2200-character store that deleted its oldest entries
    when full and mentioned it only on stdout. The cap is gone; this panel is
    the other half of that change — a memory you cannot inspect is a memory you
    cannot trust, and 'delete' has to be something the person can do."""

    _OW = 520

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            MemoryOverlay {{
                background: {C.PANEL};
                border: 1px solid {C.BORDER};
                border-radius: 18px;
            }}
        """)
        self.setFixedWidth(self._OW)

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(20, 16, 20, 16)
        self._lay.setSpacing(5)
        self._rebuild()

    def _clear_layout(self):
        """Take every item out of the layout and detach it from the widget tree
        in this call.

        deleteLater() on its own is not enough: it queues destruction for the
        next event-loop pass, and until then the old rows are still children of
        this widget and still paint — which is what drew half of the previous
        panel over the new one. setParent(None) removes them from the tree now;
        deleteLater() then frees them safely."""
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                # hide() stops it painting in this frame; deleteLater() frees it
                # safely afterwards. setParent(None) would also stop the paint,
                # but it turns the widget into a top-level window for the moment
                # between the two calls, which is not something to leave lying
                # around inside a click handler.
                w.hide()
                w.deleteLater()
                continue
            sub = item.layout()
            if sub is not None:
                while sub.count():
                    si = sub.takeAt(0)
                    sw = si.widget()
                    if sw is not None:
                        sw.hide()
                        sw.deleteLater()
                sub.deleteLater()

    def _settle(self, before):
        """Size the panel to its content, re-centre it, and repaint what the old
        size covered.

        The re-size has to happen here rather than at the end of _rebuild
        because Qt has not polished the freshly-created children at that point,
        so the size hint it would read is the empty-layout one. Measured: a
        first adjustSize() returned 32 px for a panel whose content needed 155,
        and a second call — after the same widgets had been through the event
        loop — returned 155. So this runs twice: once now, once on the next
        turn, from _rebuild.

        The re-centre and the repaint are needed because the overlay is placed
        by hand and is in no layout: shrinking it leaves it off-centre and
        leaves its former pixels on screen, since nothing tells the parent that
        region changed. The repaint has to cover the union of the old and new
        rectangles."""
        self._lay.invalidate()
        self._lay.activate()
        self.updateGeometry()
        self.adjustSize()

        p = self.parentWidget()
        if p is None:
            self.update()
            return
        self.move(max(0, (p.width()  - self.width())  // 2),
                  max(0, (p.height() - self.height()) // 2))
        p.update(before.united(self.geometry()))
        self.update()

    def _rebuild(self):
        before = self.geometry()
        self._clear_layout()

        from desktop.memory.memory_manager import all_entries_for_ui

        hdr = QLabel("🧠  WHAT JARVIS REMEMBERS")
        hdr.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        self._lay.addWidget(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        self._lay.addWidget(sep)

        rows = all_entries_for_ui()

        cap = QLabel(f"{len(rows)} stored facts — newest first. "
                     f"Nothing here is sent anywhere; it lives in "
                     f"memory/long_term.json on this machine.")
        cap.setWordWrap(True)
        cap.setFont(QFont("Courier New", 7))
        cap.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._lay.addWidget(cap)

        if not rows:
            empty = QLabel("Nothing stored yet.")
            empty.setFont(QFont("Courier New", 9))
            empty.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            self._lay.addWidget(empty)
        else:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFixedHeight(min(420, 34 * len(rows) + 10))
            scroll.setStyleSheet(
                f"QScrollArea {{ border: 1px solid {C.BORDER}; border-radius: 3px; "
                f"background: transparent; }}"
            )
            inner = QWidget()
            ilay  = QVBoxLayout(inner)
            ilay.setContentsMargins(6, 6, 6, 6)
            ilay.setSpacing(3)

            for r in rows:
                line = QHBoxLayout(); line.setSpacing(6)
                txt = QLabel(f"<b>{r['key'].replace('_', ' ')}</b> "
                             f"<span style='color:{C.TEXT_MED}'>— {r['value']}</span>")
                txt.setWordWrap(True)
                txt.setFont(QFont("Courier New", 8))
                txt.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
                line.addWidget(txt, 1)

                meta = QLabel(f"{r['category'][:4]} · {r['updated'] or '—'}")
                meta.setFont(QFont("Courier New", 7))
                meta.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
                line.addWidget(meta)

                rm = QPushButton("✕")
                rm.setFixedSize(20, 20)
                rm.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
                rm.setCursor(Qt.CursorShape.PointingHandCursor)
                rm.setToolTip("Forget this")
                rm.setStyleSheet(f"""
                    QPushButton {{ background: transparent; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 3px; }}
                    QPushButton:hover {{ color: {C.RED}; border-color: {C.RED}; }}
                """)
                rm.clicked.connect(
                    lambda _=False, c=r["category"], k=r["key"]: self._forget(c, k))
                line.addWidget(rm)

                holder = QWidget()
                holder.setLayout(line)
                ilay.addWidget(holder)

            ilay.addStretch()
            scroll.setWidget(inner)
            self._lay.addWidget(scroll)

        close = QPushButton("CLOSE")
        close.setFixedHeight(30)
        close.setFont(QFont("Courier New", 9))
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        close.clicked.connect(self.hide)
        self._lay.addWidget(close)

        self._settle(before)
        # …and again once Qt has polished the new children, because the size
        # hint is not final until then. Harmless when the first pass already
        # got it right: _settle is idempotent.
        QTimer.singleShot(0, lambda g=before: self._settle(g))

    def _forget(self, category: str, key: str):
        from desktop.memory.memory_manager import forget
        forget(key, category)
        # Rebuild on the NEXT event-loop turn, not inside this click handler.
        # The rebuild destroys the very ✕ button that emitted this signal, and
        # Qt is entitled to touch the sender after a slot returns; tearing it
        # down mid-emission is how a widget ends up half-alive on screen.
        QTimer.singleShot(0, self._rebuild)
