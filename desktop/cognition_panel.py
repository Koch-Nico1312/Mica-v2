"""Inspect and control the current conversation's lightweight response state."""
from __future__ import annotations

from PyQt6.QtWidgets import QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout

from desktop.control_center import ApiPage


STANCE_LABELS = {'neutral': 'Neutral', 'focused': 'Beim laufenden Thema',
                 'careful': 'Besonders sorgfältig', 'supportive': 'Ruhig und zugewandt'}
OBSERVATION_LABELS = {'model_error': 'Modellanfrage fehlgeschlagen',
                      'invalid_citations': 'Ungültige Quellenangabe',
                      'reply_generated': 'Antwort erzeugt'}


class CognitionPage(ApiPage):
    def __init__(self, session_provider, parent=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.session_provider = session_provider
        self._request_session = None
        layout = QVBoxLayout(self)
        explanation = QLabel('MICA hält den Gesprächsfokus und berücksichtigt Korrekturen und Antwortfehler. '
                             'Die Zusatzschicht läuft auf der CPU neben deinem Sprachmodell. '
                             'Zustände gelten für dieses Gespräch und werden nicht dauerhaft gespeichert.')
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.enabled = QCheckBox('Aufmerksamkeit und Zustände verwenden')
        self.enabled.setChecked(True)
        layout.addWidget(self.enabled)
        self.profile = QComboBox()
        self.profile.addItem('Kleiner Kontext · für 4 GB Grafikspeicher', 'low_vram')
        self.profile.addItem('Ausgewogener Kontext · für 8 GB Grafikspeicher', 'balanced')
        self.profile.setCurrentIndex(1)
        layout.addWidget(self.profile)
        row = QHBoxLayout()
        self.apply_button = QPushButton('Für dieses Gespräch übernehmen')
        self.refresh_button = QPushButton('Zustand aktualisieren')
        self.reset_button = QPushButton('Zustand zurücksetzen')
        self.apply_button.clicked.connect(self.apply)
        self.refresh_button.clicked.connect(self.refresh)
        self.reset_button.clicked.connect(self.reset)
        for button in (self.apply_button, self.refresh_button, self.reset_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.status = QLabel('Noch nicht geladen.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details)

    def _request(self, operation):
        if self._busy:
            return
        identifier = self.session_provider()
        if not identifier:
            self.status.setText('Kein aktives Gespräch verfügbar.')
            return
        self._request_session = identifier
        self._controls(False)
        self._run('cognition', lambda client: operation(client, identifier))

    def _controls(self, enabled):
        for widget in (self.enabled, self.profile, self.apply_button, self.refresh_button, self.reset_button):
            widget.setEnabled(enabled)

    def refresh(self):
        self._request(lambda client, identifier: client.cognitive_status(identifier))

    def apply(self):
        enabled, profile = self.enabled.isChecked(), self.profile.currentData()
        self._request(lambda client, identifier: client.cognitive_settings(enabled, profile, identifier))

    def reset(self):
        self._request(lambda client, identifier: client.reset_cognition(identifier))

    def _received(self, kind, value, error):
        self._busy = False
        self._controls(True)
        if self.session_provider() != self._request_session:
            self.details.clear()
            self.status.setText('Gespräch gewechselt. Bitte den aktuellen Zustand neu laden.')
            return
        if error:
            self.details.clear()
            self.status.setText('Zustand konnte nicht geladen werden: ' + error)
            return
        self.enabled.setChecked(value.get('enabled', False))
        index = self.profile.findData(value.get('profile', 'balanced'))
        self.profile.setCurrentIndex(max(0, index))
        self.status.setText('Aktiv für dieses Gespräch.' if value.get('enabled') else 'Für dieses Gespräch ausgeschaltet.')
        lines = ['Antwortverhalten: ' + STANCE_LABELS.get(value.get('stance'), 'Unbekannt'),
                 'Themenkontinuität: ' + str(round(value.get('continuity', 0) * 100)) + ' %',
                 'Vorsicht: ' + str(round(value.get('caution', 0) * 100)) + ' %',
                 'Beobachtete Modellanfragen: ' + str(value.get('turns', 0)),
                 'Fokus: ' + (', '.join(value.get('focus_terms', [])) or 'Noch kein Thema'),
                 '', 'Letzte Beobachtungen:']
        lines.extend(OBSERVATION_LABELS.get(item.get('kind'), 'Unbekannt') +
                     ' · ' + str(item.get('reply_characters', 0)) + ' Antwortzeichen'
                     for item in value.get('observations', []))
        lines.extend(['', 'Diese Werte sind Steuerzustände; sie belegen keine erlebten Gefühle.'])
        self.details.setPlainText('\n'.join(lines))


def open_cognition_dialog(parent, session_provider):
    dialog = QDialog(parent)
    dialog.setWindowTitle('Aufmerksamkeit und Zustand')
    dialog.resize(720, 470)
    layout = QVBoxLayout(dialog)
    page = CognitionPage(session_provider, dialog)
    layout.addWidget(page)
    page.refresh()
    dialog.exec()
