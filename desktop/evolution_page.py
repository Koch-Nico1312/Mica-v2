"""Native review surface for the shared MICA evolution pipeline."""
from __future__ import annotations

import json
from urllib.parse import quote
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)
from desktop.control_center import ApiPage
from desktop.core.local_core_client import LocalCoreClient, LocalCoreError

STATUS = {'proposed': 'Vorschlag', 'validated': 'Prüfung bestanden', 'active': 'Aktiv', 'shadow_failed': 'Prüfung fehlgeschlagen'}
SCOPES = {'global': 'Alle Gespräche', 'personal': 'Persönlich', 'technical': 'Technisch', 'monitoring': 'Monitoring'}


class EvolutionPage(ApiPage):
    def __init__(self, parent=None, client_factory=LocalCoreClient):
        super().__init__(parent, client_factory)
        self.data = {'preferences': [], 'gaps': [], 'suites': [], 'workshop': []}
        self.approval_ids = {}
        layout = QVBoxLayout(self)
        self.status = QLabel('Bestätigte Vorlieben und geprüfte Weiterentwicklung aus dem lokalen Backend.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        controls = QHBoxLayout()
        for label, callback in [('Aktualisieren', self.refresh), ('Freigaben entsperren', self.unlock),
                                ('Offene Freigabe bestätigen', self.pending_approvals)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        self.preferences = QComboBox()
        self.preference_detail = QTextEdit()
        self.preference_detail.setReadOnly(True)
        preferences_page = QWidget()
        preferences_layout = QVBoxLayout(preferences_page)
        preferences_layout.addWidget(self.preferences)
        preferences_layout.addWidget(self.preference_detail)
        self.preferences.currentIndexChanged.connect(self.show_preference)
        row = QHBoxLayout()
        for label, callback in [('Vorliebe bestätigen', self.add_preference), ('Korrigieren', self.correct_preference), ('Vergessen', self.forget_preference)]:
            button = QPushButton(label); button.clicked.connect(callback); row.addWidget(button)
        preferences_layout.addLayout(row)
        tabs.addTab(preferences_page, 'Nutzerkorrekturen')
        workshop_page = QWidget()
        workshop_layout = QVBoxLayout(workshop_page)
        self.gaps = QComboBox()
        self.suites = QComboBox()
        self.jobs = QComboBox()
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        for widget in (QLabel('Beobachtete Fähigkeitslücke'), self.gaps, QLabel('Unabhängige Prüfaufgabe'), self.suites,
                       QLabel('Entwicklungskandidat'), self.jobs, self.report):
            workshop_layout.addWidget(widget)
        self.jobs.currentIndexChanged.connect(self.show_job)
        for actions in [
            [('Prüfaufgabe bestätigen', self.add_suite), ('Fähigkeit entwickeln', self.forge), ('Aktive Fähigkeit reparieren', self.repair)],
            [('Isoliert prüfen', self.evaluate), ('Geprüfte Version übernehmen', self.promote), ('Vorherige Version', self.rollback)],
            [('Fähigkeit nutzen', self.invoke), ('Alltagsergebnis bestätigen', self.observe)],
        ]:
            row = QHBoxLayout()
            for label, callback in actions:
                button = QPushButton(label); button.clicked.connect(callback); row.addWidget(button)
            workshop_layout.addLayout(row)
        tabs.addTab(workshop_page, 'Skill-Werkstatt')

    def refresh(self):
        self._run('state', lambda client: client.evolution_state())

    def _received(self, kind, value, error):
        self._busy = False
        if error:
            self.status.setText(error)
            return
        if kind == 'state':
            self.data = value
            for combo, records, label in [
                (self.preferences, value['preferences'], lambda row: row['preference_key'] + ' · ' + SCOPES[row['scope']]),
                (self.gaps, value['gaps'], lambda row: row['action'] + ' · ' + {'missing_tool':'Werkzeug fehlt','broken_tool':'Werkzeugfehler','missing_permission':'Freigabe fehlt','temporary_outage':'Ausfall'}[row['category']]),
                (self.suites, value['suites'], lambda row: row['goal']),
                (self.jobs, value['workshop'], lambda row: (row.get('improvement') or {}).get('name', 'Revision nicht vorhanden') + ' · ' + STATUS.get((row.get('improvement') or {}).get('status'), '')),
            ]:
                current = combo.currentData()
                current_id = current.get('id') if isinstance(current, dict) else None
                combo.clear()
                for record in records:
                    combo.addItem(label(record), record)
                if current_id:
                    index = next((index for index, record in enumerate(records) if record.get('id') == current_id), -1)
                    if index >= 0:
                        combo.setCurrentIndex(index)
            self.status.setText('Lokale Daten geladen.')
        elif kind == 'auth':
            self.status.setText('Freigaben sind für zehn Minuten entsperrt.')
        elif kind == 'pending':
            pending = value.get('approvals', [])
            if not pending:
                self.status.setText('Keine offenen Freigaben.')
                return
            choices = [f"{row['action']}: {json.dumps(row['params'], ensure_ascii=False)}" for row in pending]
            choice, accepted = QInputDialog.getItem(self, 'Exakte Aktion bestätigen', 'Freigabe:', choices, editable=False)
            if accepted:
                identifier = pending[choices.index(choice)]['id']
                self._run('approved', lambda client: client.approve(identifier))
        elif kind == 'change' and value.get('approval'):
            self.approval_ids[value['key']] = value['approval']['approval_id']
            self.status.setText('Die exakte Aktion wartet auf Freigabe. Freigabe bestätigen und denselben Schritt erneut starten.')
        elif kind == 'change':
            self.approval_ids.pop(value['key'], None)
            if value['key'].startswith('/v1/tasks/execute'):
                self.status.setText(json.dumps(value.get('result'), ensure_ascii=False))
                return
            self.status.setText('Änderung gespeichert. Daten können aktualisiert werden.')
            self.refresh()
        elif kind == 'approved':
            self.status.setText('Freigabe bestätigt. Den ursprünglichen Schritt erneut starten.')
        else:
            self.status.setText(json.dumps(value, ensure_ascii=False))

    def change(self, method, path, body=None):
        key = path + json.dumps(body, sort_keys=True)
        payload = {**body, 'approval_id': self.approval_ids[key]} if body is not None and key in self.approval_ids else body
        def action(client):
            try:
                return {'key': key, 'result': client.evolution_change(method, path, payload)}
            except LocalCoreError as error:
                if error.status_code == 403 and isinstance(error.detail, dict) and error.detail.get('approval_id'):
                    return {'key': key, 'approval': error.detail}
                raise
        self._run('change', action)

    def pending_approvals(self):
        self._run('pending', lambda client: client.approvals())

    def show_preference(self):
        row = self.preferences.currentData()
        self.preference_detail.setPlainText(
            f"{row['preference_key']}\n\n{row['value']}\n\nGilt für: {SCOPES[row['scope']]}\nQuelle: {row['source']}\nBestätigt: {row.get('created_at', 'nicht angegeben')}"
            if row else 'Noch keine bestätigten Vorlieben.'
        )

    def show_job(self):
        row = self.jobs.currentData()
        if not row:
            self.report.setPlainText('Noch keine Entwicklungskandidaten.')
            return
        improvement = row.get('improvement') or {}
        lines = [improvement.get('name', 'Revision nicht vorhanden'), STATUS.get(improvement.get('status'), ''), '']
        quality = row.get('quality')
        if quality:
            lines.append('Qualitätsvergleich: ' + ('bestanden' if quality.get('passed') else 'nicht bestanden'))
            for key, label in [('baseline', 'Vorher'), ('candidate', 'Kandidat')]:
                metrics = quality.get(key, {})
                lines.append(f"{label}: {metrics.get('correct', 'nicht erfasst')} richtige Ergebnisse · {metrics.get('errors', 'nicht erfasst')} Ausführungsfehler · {metrics.get('duration_ms', 'nicht erfasst')} ms")
            lines.append('Fehler der alten Version reproduziert: ' + ('ja' if quality.get('reproduced') else 'nein'))
            lines.append('Schlechter gewordene Beispiele: ' + (', '.join(quality.get('regressions', [])) or 'keine'))
        else:
            lines.append('Noch kein Qualitätsvergleich durchgeführt.')
        for key, label in [('baseline', 'Vorher'), ('candidate', 'Kandidat')]:
            metrics = row.get('observations', {}).get(key, {})
            if metrics.get('tasks'):
                lines.append(f"Alltag {label}: {metrics['tasks']} Aufgaben · {metrics['user_corrections']} Nutzerkorrekturen · {metrics['provider_cost']} EUR")
            else:
                lines.append(f'Alltag {label}: noch keine bestätigten Beobachtungen.')
        lines.extend(['', 'Änderung zur vorherigen Version:', row.get('patch', 'Noch keine Änderung verfügbar.')])
        self.report.setPlainText('\n'.join(lines))

    def add_preference(self):
        key, accepted = QInputDialog.getText(self, 'Vorliebe', 'Vorliebe zu:')
        if not accepted:
            return
        self.save_preference({'preference_key': key, 'scope': 'global', 'value': ''})

    def save_preference(self, row):
        value, accepted = QInputDialog.getMultiLineText(self, 'Bestätigte Korrektur', 'Gewünschtes Verhalten:', row['value'])
        if not accepted:
            return
        scope, accepted = QInputDialog.getItem(self, 'Geltungsbereich', 'Gilt für:', ['global', 'personal', 'technical', 'monitoring'], ['global', 'personal', 'technical', 'monitoring'].index(row['scope']), False)
        if accepted:
            self.change('POST', '/v1/evolution/preferences', {'key': row['preference_key'], 'value': value, 'scope': scope, 'source': 'Bestätigte Nutzerkorrektur im Desktop'})

    def correct_preference(self):
        row = self.preferences.currentData()
        if row:
            self.save_preference(row)

    def forget_preference(self):
        row = self.preferences.currentData()
        if row and QMessageBox.question(self, 'Vergessen', 'Vorliebe und frühere Fassungen löschen?') == QMessageBox.StandardButton.Yes:
            self.change('DELETE', '/v1/evolution/preferences/' + row['id'])

    def add_suite(self):
        goal, accepted = QInputDialog.getText(self, 'Prüfaufgabe', 'Was muss die Fähigkeit können?')
        if not accepted:
            return
        examples, accepted = QInputDialog.getMultiLineText(self, 'Unabhängige Prüfbeispiele', '3–12 Beispiele mit id, input und expected als JSON:', '[{"id":"positiv","input":{"n":2},"expected":4},{"id":"negativ","input":{"n":-2},"expected":-4},{"id":"null","input":{"n":0},"expected":0}]')
        if accepted:
            try:
                self.change('POST', '/v1/evolution/suites', {'goal': goal, 'cases': json.loads(examples), 'source': 'Unabhängig bestätigte Nutzerbeispiele im Desktop'})
            except ValueError:
                self.status.setText('Prüfbeispiele sind kein gültiges JSON.')

    def forge(self):
        suite, gap = self.suites.currentData(), self.gaps.currentData()
        if not suite or not gap:
            self.status.setText('Zuerst eine Prüfaufgabe und eine Fähigkeitslücke auswählen.')
            return
        name, accepted = QInputDialog.getText(self, 'Neue Fähigkeit', 'Name:')
        if accepted:
            self.change('POST', '/v1/evolution/workshop', {'name': name, 'suite_id': suite['id'], 'gap_id': gap['id'], 'intent': 'forge'})

    def repair(self):
        row, suite = self.jobs.currentData(), self.suites.currentData()
        if not row or not suite or not row.get('improvement') or row['improvement']['status'] != 'active':
            self.status.setText('Eine aktive Fähigkeit und eine unabhängige Prüfaufgabe auswählen.')
            return
        self.change('POST', '/v1/evolution/workshop', {'name': row['improvement']['name'], 'suite_id': suite['id'], 'intent': 'repair'})

    def revision_action(self, action):
        row = self.jobs.currentData()
        if row and row.get('improvement'):
            body = {'auto_promote': False} if action == 'evaluate' else {}
            self.change('POST', f"/v1/improvements/{row['improvement_id']}/{action}", body)

    def evaluate(self):
        self.revision_action('evaluate')

    def promote(self):
        self.revision_action('promote')

    def rollback(self):
        row = self.jobs.currentData()
        if row and row.get('improvement'):
            self.change('POST', '/v1/improvements/' + quote(row['improvement']['name'], safe='') + '/rollback', {})

    def invoke(self):
        row = self.jobs.currentData()
        if not row or not row.get('improvement') or row['improvement']['status'] != 'active':
            return
        raw, accepted = QInputDialog.getMultiLineText(self, 'Fähigkeit nutzen', 'Eingabedaten als JSON:', '{}')
        if accepted:
            try:
                payload = json.loads(raw)
            except ValueError:
                self.status.setText('Ungültige JSON-Eingabe.')
                return
            self.change('POST', '/v1/tasks/execute', {'action': 'improvement.invoke', 'params': {'improvement_id': row['improvement_id'], 'payload': payload}, 'dry_run': False})

    def observe(self):
        row = self.jobs.currentData()
        if not row or not row.get('improvement'):
            return
        raw, accepted = QInputDialog.getMultiLineText(self, 'Alltagsergebnis', 'Tatsächlich gemessene Aufgabe bestätigen (Kosten in EUR):', '{"task_id":"","success":true,"duration_ms":0,"provider_cost":0,"user_corrections":0}')
        if accepted:
            try:
                body = json.loads(raw)
                body['source'] = 'Bestätigtes Alltagsergebnis im Desktop'
                self.change('POST', f"/v1/evolution/revisions/{row['improvement_id']}/observations", body)
            except (ValueError, TypeError):
                self.status.setText('Ungültiges Alltagsergebnis.')
