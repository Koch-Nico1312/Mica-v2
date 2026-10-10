"""Jira connection and read workflows in the canonical desktop control center."""
from __future__ import annotations

import json
import threading

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit,
                            QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget)

from desktop.core.jira_mcp import EMAIL_SECRET, JiraError, JiraMcpClient, forget_account, save_account
from desktop.core.secure_store import SecureStoreUnavailable, get_secret


class JiraPage(QWidget):
    completed = pyqtSignal(str, object, str)

    def __init__(self, parent=None, client_factory=JiraMcpClient.from_saved_account, task_store=None, can_save=lambda: True):
        super().__init__(parent)
        self.client_factory = client_factory
        self.busy = False
        self.task_store, self.can_save = task_store, can_save
        self.import_draft, self._issue_context = None, None
        self.completed.connect(self._receive)
        layout = QVBoxLayout(self)
        intro = QLabel('Verbinde dein Atlassian-Konto, um Jira-Vorgänge in MICA zu lesen und zu suchen. '
                       'E-Mail und eingeschränkter API-Token bleiben im Windows-Anmeldetresor. '
                       'Deine Organisation muss API-Token für den Atlassian-MCP-Server freigeben.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.email = QLineEdit()
        self.email.setPlaceholderText('Atlassian-E-Mail-Adresse')
        try:
            self.email.setText(get_secret(EMAIL_SECRET) or '')
        except SecureStoreUnavailable:
            pass
        layout.addWidget(self.email)
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText('Eingeschränkter Atlassian-API-Token')
        layout.addWidget(self.token)
        row = QHBoxLayout()
        self.save_button = QPushButton('Zugang speichern und verbinden')
        self.save_button.clicked.connect(self._save)
        self.connect_button = QPushButton('Gespeicherten Zugang prüfen')
        self.connect_button.clicked.connect(lambda: self._run('resources', lambda client: client.resources()))
        self.forget_button = QPushButton('Zugang entfernen')
        self.forget_button.clicked.connect(self._forget)
        for button in (self.save_button, self.connect_button, self.forget_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.status = QLabel('Noch nicht verbunden. Die Verbindung wird erst auf deinen Klick geprüft.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.sites = QComboBox()
        self.sites.setPlaceholderText('Atlassian-Website auswählen')
        layout.addWidget(self.sites)
        row = QHBoxLayout()
        self.query = QLineEdit('assignee = currentUser() AND resolution = Unresolved ORDER BY updated DESC')
        self.query.setPlaceholderText('Jira-Suchausdruck (JQL)')
        self.search_button = QPushButton('Vorgänge suchen')
        self.search_button.clicked.connect(self._search)
        row.addWidget(self.query, 1)
        row.addWidget(self.search_button)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.issue_key = QLineEdit()
        self.issue_key.setPlaceholderText('Vorgangsnummer, z. B. MICA-123')
        self.issue_button = QPushButton('Vorgang lesen')
        self.issue_button.clicked.connect(self._issue)
        row.addWidget(self.issue_key, 1)
        row.addWidget(self.issue_button)
        layout.addLayout(row)
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        layout.addWidget(self.report, 1)
        self.import_button = QPushButton('Gelesenen Vorgang als lokale Aufgabe übernehmen …')
        self.import_button.clicked.connect(self._import_task)
        layout.addWidget(self.import_button)
        self.issue_key.textChanged.connect(self._clear_import)
        self.sites.currentIndexChanged.connect(self._clear_import)
        self._set_busy(False)

    def _set_busy(self, busy):
        self.busy = busy
        for widget in (self.email, self.token, self.save_button, self.connect_button,
                       self.forget_button, self.sites, self.query, self.issue_key):
            widget.setEnabled(not busy)
        available = not busy and bool(self.sites.currentData())
        self.search_button.setEnabled(available)
        self.issue_button.setEnabled(available)
        self.import_button.setEnabled(not busy and self.import_draft is not None)

    def _clear_import(self, *_):
        self.import_draft = None
        self.import_button.setEnabled(False)

    def _import_task(self):
        if self.busy or self.import_draft is None:
            return
        if not self.can_save():
            self.status.setText('Lokale Aufgaben benötigen den Modus mit Speicherung.')
            return
        draft = dict(self.import_draft)
        text = draft['title'] + '\n\n' + draft['description'] + '\n\nAls offene lokale Aufgabe übernehmen? Kein Jira-Vorgang wird geändert. Dauer zunächst 30 Minuten; bitte unter Tagesplanung anpassen. Dort erfolgt später auch der ausdrückliche Backend-Abgleich.'
        if QMessageBox.question(self, 'Lokale Aufgabe prüfen', text) != QMessageBox.StandardButton.Yes:
            return
        try:
            from desktop.core.offline_tasks import OfflineTasks
            store = self.task_store or OfflineTasks()
            store.stage(draft, create_only=True)
        except (ValueError, OSError) as error:
            self.status.setText('Lokale Aufgabe nicht übernommen: ' + str(error))
            return
        self.status.setText('Als offene lokale Aufgabe vorgemerkt. Unter Tagesplanung prüfen und ausdrücklich abgleichen.')
        self._clear_import()

    def _save(self):
        if self.busy:
            return
        try:
            save_account(self.email.text(), self.token.text())
        except (JiraError, SecureStoreUnavailable):
            self.status.setText('Zugang konnte nicht gespeichert werden. E-Mail, Token und Windows-Anmeldetresor prüfen.')
            return
        self.token.clear()
        self.sites.clear()
        self.report.clear()
        self._run('resources', lambda client: client.resources())

    def _forget(self):
        if self.busy:
            return
        if QMessageBox.question(self, 'Jira-Zugang entfernen',
                                'Gespeicherte Atlassian-Zugangsdaten aus MICA entfernen?') != QMessageBox.StandardButton.Yes:
            return
        try:
            forget_account()
        except SecureStoreUnavailable:
            self.status.setText('Windows-Anmeldetresor ist nicht verfügbar.')
            return
        self.email.clear()
        self.token.clear()
        self.sites.clear()
        self.report.clear()
        self.status.setText('Jira-Zugang entfernt.')
        self._set_busy(False)

    def _search(self):
        cloud_id, query = self.sites.currentData(), self.query.text()
        self._run('search', lambda client: client.search(cloud_id, query))

    def _issue(self):
        cloud_id, key = self.sites.currentData(), self.issue_key.text()
        self._issue_context = (cloud_id, key)
        self._run('issue', lambda client: client.issue(cloud_id, key))

    def _run(self, kind, action):
        if self.busy:
            return
        self._clear_import()
        self._set_busy(True)
        self.status.setText('Atlassian wird abgefragt …')
        self.report.clear()
        if kind == 'resources':
            self.sites.clear()

        def worker():
            value, error = None, ''
            try:
                with self.client_factory() as client:
                    value = action(client)
            except JiraError as exc:
                error = str(exc)
            except Exception:
                error = 'Jira konnte nicht abgefragt werden. Verbindung und Windows-Anmeldetresor prüfen.'
            try:
                self.completed.emit(kind, value, error)
            except RuntimeError:
                pass

        threading.Thread(target=worker, daemon=True, name='mica-jira').start()

    def _receive(self, kind, value, error):
        if error:
            self.status.setText(error)
        elif kind == 'resources':
            for item in value:
                self.sites.addItem(str(item.get('name') or item.get('url') or item['id']), item['id'])
            if self.sites.count():
                self.sites.setCurrentIndex(0)
            self.status.setText(f'Zugang geprüft: {len(value)} Atlassian-Websites verfügbar.' if value
                                else 'Zugang geprüft, aber keine Atlassian-Website freigegeben.')
        else:
            self.status.setText('Jira-Antwort geladen. Es wurden keine Vorgänge geändert.')
            texts = [item['text'] for item in value.get('content', [])
                     if isinstance(item, dict) and item.get('type') == 'text' and isinstance(item.get('text'), str)]
            self.report.setPlainText('\n\n'.join(texts) if texts else json.dumps(value, ensure_ascii=False, indent=2))
            if kind == 'issue' and self._issue_context:
                from desktop.core.jira_task_import import issue_task_draft
                try:
                    self.import_draft = issue_task_draft(value, *self._issue_context)
                except ValueError:
                    self.status.setText('Vorgang geladen. Das Antwortformat ist für den lokalen Aufgabenimport nicht eindeutig.')
        self._set_busy(False)
