"""Desktop operations view backed by the same API as local MICA."""
from __future__ import annotations

import threading
import os
import json
import re
import tempfile
from statistics import median
from pathlib import Path

from PyQt6.QtCore import QDateTime, QTimeZone, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QHeaderView, QMessageBox, QPushButton, QStyle, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from desktop.core.local_core_client import LocalCoreClient
from desktop.core.response_timing import RESPONSE_TIMINGS


STATUS_LABELS = {
    'open': 'Offen', 'in_progress': 'In Arbeit', 'running': 'Wird ausgeführt',
    'completed': 'Erledigt', 'succeeded': 'Erledigt', 'failed': 'Fehlgeschlagen',
    'cancelled': 'Abgebrochen', 'paused': 'Pausiert', 'active': 'Aktiv',
    'draft': 'Entwurf', 'ready': 'Bereit', 'not_dispatched': 'Nicht ausgeführt',
    'approval_required': 'Wartet auf Freigabe', 'uncertain': 'Ausgang prüfen',
    'idle': 'Bereit', 'offline': 'Offline', 'thinking': 'Denkt nach',
    'listening': 'Hört zu', 'speaking': 'Spricht', 'executing': 'Führt aus',
    'error': 'Fehler', 'blocked': 'Gesperrt',
}

TASK_REASONS = {
    'uncertain_outcome': 'Das Ergebnis einer bereits gestarteten Aktion ist noch unklar.',
    'budget_exhausted': 'Das Zeit- oder Aktionsbudget ist ausgeschöpft.',
    'A saved user approval is required': 'Eine lokale Freigabe für diese Aktion ist erforderlich.',
    'A parameter-bound user approval is required': 'Die exakten Aktionsparameter benötigen eine lokale Freigabe.',
    'A parameter-bound plan approval is required': 'Dieser Plan benötigt eine lokale Freigabe.',
    'Explicit human approval is required': 'Eine ausdrückliche lokale Freigabe ist erforderlich.',
    'Explicit single-use human approval is required': 'Eine neue, einmalige lokale Freigabe ist erforderlich.',
    'A fresh single-use approval is required for this destructive plan': 'Dieser Plan benötigt eine neue, einmalige lokale Freigabe.',
    'Emergency stop is active': 'Not-Aus ist aktiv.',
}


def task_presentation(item):
    """Interpret lifecycle and dispatch evidence without granting execution rights."""
    status, kind = item.get('status', ''), item['kind']
    steps = item.get('steps', [])
    unresolved = kind == 'execution' and (item.get('needs_reconciliation') or status == 'uncertain')
    if kind == 'plan':
        unresolved = item.get('last_error') == 'uncertain_outcome' or any(
            step.get('status') in {'running', 'failed'} or
            (step.get('status') == 'blocked' and step.get('dispatch_started_at')) for step in steps
        )
    label = STATUS_LABELS.get(status, status or 'Unbekannt')
    category, hint = 'attention', 'Details prüfen.'
    if status == 'cancelled' and unresolved:
        label, hint = 'Ergebnis unklar', 'Plan abgebrochen. Das Ergebnis einer bereits gestarteten Aktion ist noch offen.'
    elif status in {'completed', 'succeeded', 'cancelled'}:
        category = 'done'
        hint = 'Abgeschlossen.' if status != 'cancelled' else 'Abgebrochen. Bereits ausgeführte Änderungen bleiben bestehen.'
    elif status in {'active', 'running', 'in_progress'}:
        category, hint = 'running', 'Die Aufgabe läuft.'
        if kind == 'execution':
            hint = 'Ausführung läuft oder Ergebnis steht aus. Vor einer Fortsetzung das Ergebnis prüfen.'
    elif unresolved:
        label, hint = 'Ergebnis unklar', 'Das tatsächliche Ergebnis muss mit dem Aktionsdienst abgeglichen werden.'
    elif status == 'approval_required' or (
        kind == 'plan' and any(step.get('status') == 'blocked' for step in steps)
        and 'approval' in str(item.get('last_error', '')).lower()
    ):
        label, hint = 'Wartet auf Freigabe', 'Die exakte Aktion wartet auf eine lokale Freigabe.'
    elif item.get('last_error') == 'budget_exhausted':
        hint = 'Das Zeit- oder Aktionsbudget ist ausgeschöpft.'
    elif kind == 'plan' and not item.get('dry_run_at'):
        hint = 'Die Vorschau ist vor dem Start erforderlich.'
    elif status in {'paused', 'ready'}:
        hint = 'Der Plan kann nach den lokalen Prüfungen fortgesetzt werden.'
    elif status == 'not_dispatched':
        hint = 'Die Aktion wurde nicht ausgeführt; gespeicherte Parameter können erneut geprüft werden.'
    elif status == 'open':
        hint = 'Die Aufgabe ist noch offen.'
    progress = f"{sum(step.get('status') == 'completed' for step in steps)} / {len(steps)}" if kind == 'plan' else ''
    return {'label': label, 'category': category, 'hint': hint,
            'unresolved': bool(unresolved), 'progress': progress}


def task_identity(item):
    return item['kind'], item.get('key') if item['kind'] == 'execution' else item.get('id')


def task_timestamp(value):
    timestamp = QDateTime.fromString(value or '', Qt.DateFormat.ISODate)
    return timestamp.toTimeZone(QTimeZone(b'Europe/Vienna')).toString('dd.MM. HH:mm') if timestamp.isValid() else ''


def task_deadline(item, now=None):
    """Describe open task deadlines in Vienna, without changing their status."""
    if item.get('kind') != 'task' or item.get('status') not in {'open', 'in_progress'}:
        return {'category': '', 'label': '', 'timestamp': None}
    value = item.get('due_at')
    if not isinstance(value, str) or not value:
        return {'category': '', 'label': '', 'timestamp': None}
    zone = QTimeZone(b'Europe/Vienna')
    due = QDateTime.fromString(value, Qt.DateFormat.ISODate)
    if not due.isValid():
        return {'category': 'invalid', 'label': 'Termin prüfen', 'timestamp': None}
    if not re.search(r'(?:Z|[+-]\d\d:\d\d)$', value, re.IGNORECASE):
        due.setTimeZone(zone)
    due = due.toTimeZone(zone)
    now = (now or QDateTime.currentDateTimeUtc()).toTimeZone(zone)
    category = 'overdue' if due < now else 'today' if due.date() == now.date() else 'later'
    prefix = {'overdue': 'Überfällig: ', 'today': 'Heute: ', 'later': ''}[category]
    return {'category': category, 'label': prefix + due.toString('dd.MM. HH:mm'),
            'timestamp': due.toMSecsSinceEpoch()}


def task_snapshot_markdown(items, *, fresh, generated_at=None):
    """Export displayed task metadata, never action parameters or execution output."""
    timestamp = generated_at or QDateTime.currentDateTimeUtc()
    lines = ['# MICA Aufgaben', '', 'Stand: ' + timestamp.toTimeZone(QTimeZone(b'Europe/Vienna')).toString('dd.MM.yyyy HH:mm'),
             'Zeitzone: Europe/Vienna', '']
    if not fresh:
        lines.extend(['Hinweis: Der Backend-Stand ist nicht aktuell. Dies ist die zuletzt geladene Ansicht.', ''])
    def escape(value):
        text = str(value or '').replace('\r', ' ').replace('\n', ' ')
        return re.sub(r'([\\`*_{}\[\]()<>#!|])', r'\\\1', text)
    for item in items:
        title = item.get('goal', item.get('title', item.get('action', '')))
        presentation = task_presentation(item)
        lines.extend(['## ' + escape(title), '', 'Status: ' + escape(presentation['label'])])
        if item.get('priority'):
            lines.append('Priorität: ' + {'high': 'Hoch', 'normal': 'Normal', 'low': 'Niedrig'}.get(item['priority'], escape(item['priority'])))
        deadline = task_deadline(item, timestamp)
        if deadline['label']:
            lines.append('Fällig: ' + escape(deadline['label']))
        if presentation['unresolved']:
            lines.append('Ergebnis einer bereits gestarteten Aktion ist ungeklärt. Vor Fortsetzung prüfen.')
        if item.get('description'):
            lines.extend(['', escape(item['description'])])
        lines.append('')
    if not items:
        lines.extend(['Keine Aufgaben in dieser Ansicht.', ''])
    return '\n'.join(lines)


def save_task_snapshot(path, text):
    """Publish complete UTF-8 contents atomically; failed writes keep the old file."""
    target = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=target.parent, prefix='.mica-export-', suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class ApiPage(QWidget):
    _result = pyqtSignal(str, object, str, object)

    def __init__(self, parent=None, client_factory=LocalCoreClient):
        super().__init__(parent)
        self.client_factory = client_factory
        self._busy = False
        self._cookies = {}
        self._result.connect(self._receive_worker)
        self.setStyleSheet('''
            QLabel { color: #26384d; background: transparent; }
            QPushButton { color: #355273; background: #ffffff; border: 1px solid #dbe5f1;
                border-radius: 9px; padding: 9px 12px; }
            QPushButton:hover { border-color: #548fff; background: #edf4ff; }
            QPushButton:disabled { color: #8797aa; }
            QTabWidget::pane { border: 1px solid #dbe5f1; border-radius: 12px; }
            QTabBar::tab { color: #597694; padding: 10px 14px; border: none; }
            QTabBar::tab:selected { color: #548fff; background: #e8f1ff; border-radius: 8px; }
            QTableWidget, QTextEdit, QLineEdit { color: #26384d; background: #ffffff;
                border: 1px solid #dbe5f1; border-radius: 9px; padding: 6px;
                selection-background-color: #e8f1ff; selection-color: #26384d; }
            QHeaderView::section { background: #f0f5fc; color: #597694; border: none; padding: 7px; }
            QCheckBox { color: #355273; padding: 6px 0; }
        ''')

    def _receive_worker(self, kind, value, error, cookies):
        self._cookies = cookies
        self._received(kind, value, error)

    def unlock(self):
        secret, accepted = QInputDialog.getText(self, 'Lokale Freigabe',
            'Lokales MICA-Freigabepasswort (wird nicht gespeichert):', QLineEdit.EchoMode.Password)
        if accepted and secret:
            self._run('auth', lambda c: c.login(secret))

    def _run(self, kind, action):
        if self._busy:
            return
        self._busy = True
        self.status.setText('Wird geladen …')
        cookies = dict(self._cookies)

        def worker():
            client = None
            value, error = None, ''
            try:
                client = self.client_factory()
                client.session.cookies.update(cookies)
                value = action(client)
                cookies.update(client.session.cookies.get_dict())
            except Exception as exc:
                error = str(exc)
            finally:
                if client is not None:
                    client.session.close()
            try:
                self._result.emit(kind, value, error, cookies)
            except RuntimeError:
                pass

        threading.Thread(target=worker, daemon=True, name='mica-control-center').start()


class ControlCenter(ApiPage):
    restore_busy = pyqtSignal(bool)
    open_settings = pyqtSignal()

    def __init__(self, parent=None, client_factory=LocalCoreClient, can_save=lambda: True):
        super().__init__(parent)
        self.client_factory = client_factory
        self._items = []
        self._all_items = []
        self._activity_fresh = False
        self._emergency_stopped = False
        self._task_notice = ''
        self._approved = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        title = QLabel('MICA im Alltag')
        title.setStyleSheet('font-size: 24px; font-weight: 600;')
        layout.addWidget(title)
        self.status = QLabel('Aufgaben und Prüfungen werden aus dem lokalen Backend geladen.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        tasks = QWidget()
        task_layout = QVBoxLayout(tasks)
        row = QHBoxLayout()
        self.task_search = QLineEdit()
        self.task_search.setPlaceholderText('Aufgaben suchen')
        self.task_search.textChanged.connect(self._render_tasks)
        row.addWidget(self.task_search, 1)
        self.task_filter = QComboBox()
        for label, key in [('Alle', 'all'), ('Handlungsbedarf', 'attention'),
                           ('Laufend', 'running'), ('Abgeschlossen', 'done')]:
            self.task_filter.addItem(label, key)
        self.task_filter.currentIndexChanged.connect(self._render_tasks)
        row.addWidget(self.task_filter)
        self.task_sort = QComboBox()
        for label, key in [('Bisherige Reihenfolge', 'original'), ('Dringlichkeit', 'urgency'),
                           ('Fälligkeit', 'deadline'), ('Titel', 'title')]:
            self.task_sort.addItem(label, key)
        self.task_sort.setToolTip('Aufgaben sortieren; Freigaben und Ausführungen bleiben unverändert.')
        self.task_sort.currentIndexChanged.connect(self._render_tasks)
        row.addWidget(self.task_sort)
        self.refresh_button = QPushButton()
        self.refresh_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.refresh_button.setToolTip('Aufgaben aktualisieren')
        self.refresh_button.setFixedSize(38, 38)
        self.refresh_button.clicked.connect(self.refresh)
        row.addWidget(self.refresh_button)
        task_layout.addLayout(row)
        self.task_count = QLabel('Noch keine Aufgaben geladen.')
        task_layout.addWidget(self.task_count)
        self.deadline_filter = QComboBox()
        for label, key in [('Alle Termine', 'all'), ('Heute fällig oder überfällig', 'today'),
                           ('Überfällig', 'overdue'), ('Hohe Priorität', 'high')]:
            self.deadline_filter.addItem(label, key)
        self.deadline_filter.currentIndexChanged.connect(self._render_tasks)
        task_layout.addWidget(self.deadline_filter)
        self.export_tasks_button = QPushButton('Sichtbare Aufgaben als Markdown speichern …')
        self.export_tasks_button.clicked.connect(self.export_tasks)
        task_layout.addWidget(self.export_tasks_button)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['Aufgabe / Aktion', 'Typ', 'Status', 'Schritte', 'Geändert', 'Priorität', 'Fällig'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 7):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().hide()
        self.table.itemSelectionChanged.connect(self._show_detail)
        task_layout.addWidget(self.table, 2)
        self.task_empty = QLabel('Keine Aufgaben vorhanden.')
        task_layout.addWidget(self.task_empty)
        self.task_hint = QLabel('Keine Aufgabe ausgewählt.')
        self.task_hint.setWordWrap(True)
        task_layout.addWidget(self.task_hint)
        actions = QHBoxLayout()

        def task_button(label, tooltip, icon, callback):
            button = QPushButton(label)
            button.setIcon(self.style().standardIcon(icon))
            button.setToolTip(tooltip)
            button.clicked.connect(callback)
            actions.addWidget(button)
            return button

        self.pause_button = task_button('', 'Plan pausieren', QStyle.StandardPixmap.SP_MediaPause, self.pause)
        self.resume_button = task_button('Fortsetzen', 'Plan fortsetzen', QStyle.StandardPixmap.SP_MediaPlay, self.resume)
        self.preview_button = task_button('Vorschau', 'Plan ohne Ausführung prüfen', QStyle.StandardPixmap.SP_FileDialogContentsView, self.preview)
        self.reconcile_button = task_button('Ergebnis prüfen', 'Ergebnis mit dem Aktionsdienst abgleichen', QStyle.StandardPixmap.SP_BrowserReload, self.reconcile_selected)
        self.retry_button = task_button('Fortsetzen', 'Nicht ausgeführte Einzelaktion fortsetzen', QStyle.StandardPixmap.SP_MediaPlay, self.retry_execution)
        self.approvals_button = task_button('Freigaben', 'Offene Freigaben prüfen', QStyle.StandardPixmap.SP_FileDialogDetailedView, self.open_approvals)
        self.history_button = task_button('Aktionsverlauf', 'Bereits gestartete Aktionen prüfen', QStyle.StandardPixmap.SP_FileDialogDetailedView, self.open_action_history)
        self.task_start_button = task_button('In Arbeit', 'Aufgabe als in Arbeit markieren', QStyle.StandardPixmap.SP_MediaPlay, lambda: self.update_task('in_progress'))
        self.task_done_button = task_button('Erledigt', 'Aufgabe als erledigt markieren', QStyle.StandardPixmap.SP_DialogApplyButton, lambda: self.update_task('completed'))
        self.cancel_button = task_button('', 'Aufgabe oder Plan abbrechen', QStyle.StandardPixmap.SP_DialogCancelButton, self.cancel_selected)
        actions.addStretch()
        task_layout.addLayout(actions)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        task_layout.addWidget(self.detail, 1)
        self.tabs.addTab(tasks, 'Aufgaben')
        diagnostics = QWidget()
        diagnostic_layout = QVBoxLayout(diagnostics)
        self.probe = QPushButton('Backend, Modelle und Sprache prüfen')
        self.probe.clicked.connect(lambda: self._run('diagnostics', lambda c: c.diagnostics()))
        diagnostic_layout.addWidget(self.probe)
        repair_row = QVBoxLayout()
        for text, callback in [('Lokales Backend starten', self.start_backend),
                               ('Verbindung einstellen', self.configure_connection),
                               ('Modelle / Anbieter einstellen', self.open_settings.emit)]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            repair_row.addWidget(button)
        diagnostic_layout.addLayout(repair_row)
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        self.report.setPlainText('Starte eine Prüfung. Es werden keine Audioaufnahmen oder Cloud-Anfragen gesendet.')
        diagnostic_layout.addWidget(self.report)
        self.tabs.addTab(diagnostics, 'Diagnose')
        timing_row = QHBoxLayout()
        timing_title = QLabel('Antwortzeiten dieser Sitzung')
        timing_title.setStyleSheet('font-weight: 600;')
        timing_row.addWidget(timing_title, 1)
        clear_timings = QPushButton()
        clear_timings.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        clear_timings.setToolTip('Gemessene Antwortzeiten löschen')
        clear_timings.setFixedSize(38, 38)
        clear_timings.clicked.connect(self.clear_response_timings)
        timing_row.addWidget(clear_timings)
        diagnostic_layout.addLayout(timing_row)
        self.timing_summary = QLabel()
        self.timing_summary.setWordWrap(True)
        diagnostic_layout.addWidget(self.timing_summary)
        self.timing_table = QTableWidget(0, 6)
        self.timing_table.setHorizontalHeaderLabels(['Zeit / Art', 'Ergebnis', 'Transkript', 'Antwort', 'Audio', 'Gesamt'])
        self.timing_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.timing_table.verticalHeader().hide()
        self.timing_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.timing_table.setMinimumHeight(140)
        diagnostic_layout.addWidget(self.timing_table)
        self._timing_snapshot = None
        self._timing_timer = QTimer(self)
        self._timing_timer.timeout.connect(self.refresh_response_timings)
        self._timing_timer.start(1000)
        self.refresh_response_timings()
        history_page = QWidget()
        history_layout = QVBoxLayout(history_page)
        history_buttons = QHBoxLayout()
        for text, callback in [('Aktionsverlauf laden', self.refresh_history),
                               ('Letzte Desktop-Änderung rückgängig', self.undo_last)]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            history_buttons.addWidget(button)
        history_layout.addLayout(history_buttons)
        self.host_change = QComboBox()
        history_layout.addWidget(self.host_change)
        host_undo = QPushButton('Ausgewählte Windows-Dateiänderung rückgängig')
        host_undo.clicked.connect(self.undo_host_change)
        history_layout.addWidget(host_undo)
        self.history_report = QTextEdit()
        self.history_report.setReadOnly(True)
        history_layout.addWidget(self.history_report)
        self.tabs.addTab(history_page, 'Aktionen')
        backup_page = QWidget()
        backup_layout = QVBoxLayout(backup_page)
        explanation = QLabel('Gedächtnis, Einstellungen und Automationen sichern. '
            'Vor einer Wiederherstellung entsteht eine Recovery-Kopie. '
            'Danach bleiben Backend-Automationen deaktiviert und Not-Aus aktiv, bis du den Stand geprüft hast.')
        explanation.setWordWrap(True)
        backup_layout.addWidget(explanation)
        for text, callback in [('Backup-Zugriff entsperren', self.unlock),
                               ('Backup speichern …', self.save_backup),
                               ('Backup-Datei prüfen …', self.inspect_backup_file),
                               ('Update-Sicherung erstellen', self.prepare_update_checkpoint),
                               ('Backup wiederherstellen …', self.restore_backup),
                               ('Recovery-Status prüfen', self.recovery_status),
                               ('Recovery-Backup herunterladen …', self.download_recovery)]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            backup_layout.addWidget(button)
        self.backup_report = QTextEdit()
        self.backup_report.setReadOnly(True)
        backup_layout.addWidget(self.backup_report)
        self.tabs.addTab(backup_page, 'Backup')
        self._recovery_id = None
        approval_page = QWidget()
        approval_layout = QVBoxLayout(approval_page)
        for text, callback in [('Freigaben entsperren', self.unlock), ('Offene Freigaben laden', self.load_approvals)]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            approval_layout.addWidget(button)
        self.approval_choice = QComboBox()
        self.approval_choice.currentIndexChanged.connect(self._approval_selected)
        approval_layout.addWidget(self.approval_choice)
        self.approval_detail = QTextEdit()
        self.approval_detail.setReadOnly(True)
        approval_layout.addWidget(self.approval_detail)
        button = QPushButton('Ausgewählte Freigabe bestätigen')
        button.clicked.connect(self.approve_selected)
        approval_layout.addWidget(button)
        clear_stop = QPushButton('Not-Aus nach Prüfung aufheben')
        clear_stop.clicked.connect(self.clear_stop)
        approval_layout.addWidget(clear_stop)
        self.tabs.addTab(approval_page, 'Freigaben')
        from desktop.evolution_page import EvolutionPage
        self.evolution_page = EvolutionPage(client_factory=client_factory)
        self.tabs.addTab(self.evolution_page, 'Weiterentwicklung')
        from desktop.jira_page import JiraPage
        self.jira_page = JiraPage(can_save=can_save)
        self.tabs.addTab(self.jira_page, 'Jira')
        from desktop.checklists_page import ChecklistsPage
        self.checklists_page = ChecklistsPage(can_save=can_save)
        self.tabs.addTab(self.checklists_page, 'Listen')
        from desktop.quick_notes_page import QuickNotesPage
        self.quick_notes_page = QuickNotesPage(can_save=can_save)
        self.quick_notes_page.checklist_created.connect(self.checklists_page.refresh)
        self.tabs.addTab(self.quick_notes_page, 'Notizblock')
        from desktop.password_page import PasswordPage
        self.password_page = PasswordPage()
        self.tabs.addTab(self.password_page, 'Kennwort')
        from desktop.folder_analysis_page import FolderAnalysisPage
        self.folder_analysis_page = FolderAnalysisPage()
        self.tabs.addTab(self.folder_analysis_page, 'Dateigrößen')
        self.tabs.currentChanged.connect(lambda index: self.evolution_page.refresh() if self.tabs.widget(index) is self.evolution_page else None)
        self.timer = QTimer(self)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self._refresh_visible)
        self.timer.start()
        self._update_task_actions()

    def _run(self, kind, action):
        if kind != 'activity' and not self._busy:
            self._task_notice = ''
        super()._run(kind, action)
        self._update_task_actions()

    def clear_response_timings(self):
        RESPONSE_TIMINGS.clear()
        self.refresh_response_timings()

    def refresh_response_timings(self):
        records = RESPONSE_TIMINGS.snapshot()
        if records == self._timing_snapshot:
            return
        self._timing_snapshot = records
        summary = []
        for kind, label in [('text', 'Text'), ('voice', 'Sprache')]:
            values = [record['reply_ms'] for record in records
                      if record['kind'] == kind and record['outcome'] == 'success' and 'reply_ms' in record]
            if values:
                summary.append(f'{label}: {median(values) / 1000:.2f} s Median ({len(values)})')
        self.timing_summary.setText(' | '.join(summary) or 'Noch keine erfolgreichen Antworten gemessen.')
        self.timing_table.setRowCount(len(records))
        outcomes = {'success': 'Erfolgreich', 'failed': 'Fehlgeschlagen', 'cancelled': 'Abgebrochen'}
        for row, record in enumerate(reversed(records)):
            kind = 'Text' if record['kind'] == 'text' else 'Sprache'
            values = [task_timestamp(record['created_at']) + '\n' + kind, outcomes[record['outcome']]]
            values.extend(f"{record[key] / 1000:.2f} s" if key in record else '-'
                          for key in ('transcript_ms', 'reply_ms', 'audio_ms', 'total_ms'))
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                hint = value
                if column in {2, 3, 4}:
                    hint += '\nAb Absenden der Aufnahme.' if kind == 'Sprache' else '\nAb Beginn der Textanfrage.'
                if column == 4:
                    hint += '\nAudio vollständig empfangen; nicht der Beginn der hörbaren Wiedergabe.'
                if column == 5:
                    hint += ('\nInklusive Aufnahme und Wiedergabe, ohne nachträgliche Bereinigung.' if kind == 'Sprache'
                             else '\nVollständige Core-Anfrage, ohne Wartezeit vor dem Aufruf oder UI-Anzeige.')
                if 'connect_ms' in record:
                    hint += f"\nVerbindung: {record['connect_ms'] / 1000:.2f} s"
                cell.setToolTip(hint)
                self.timing_table.setItem(row, column, cell)
        self.timing_table.resizeRowsToContents()

    def refresh(self):
        self._run('activity', lambda c: c.activity())

    def start_backend(self):
        from desktop.core.settings_store import _run_backend_launcher
        def start(_client):
            _run_backend_launcher(['up', '-d'], timeout=180)
            return {'started': True}
        self._run('backend_started', start)

    def configure_connection(self):
        address, accepted = QInputDialog.getText(self, 'Backend-Verbindung', 'Lokale HTTPS-Adresse:',
            text=os.getenv('MICA_CORE_URL', 'https://mica.local'))
        if not accepted:
            return
        ca_file, _ = QFileDialog.getOpenFileName(self, 'CA-Zertifikat auswählen (Abbrechen: Systemvertrauen)',
                                               '', 'CA-Zertifikat (*.crt *.pem)')
        try:
            client = LocalCoreClient(address.strip(), ca_file=ca_file or None)
            client.session.close()
            from desktop.core.settings_store import _update_env
            values = {'MICA_CORE_URL': address.strip(), 'MICA_CORE_CA_FILE': ca_file}
            _update_env(Path(__file__).resolve().parents[1] / '.env', values)
            os.environ.update(values)
        except Exception as error:
            self.status.setText('Verbindungseinstellung abgelehnt: ' + str(error))
            return
        self.status.setText('Verbindung gespeichert. Diagnose erneut starten; MICA für Chat und Sprache neu starten.')

    def save_backup(self):
        if self._busy:
            return
        filename, _ = QFileDialog.getSaveFileName(self, 'MICA-Backup speichern', 'mica-backup.zip', 'MICA-Backup (*.zip)')
        if not filename:
            return
        from desktop.core.desktop_backup import save_bundle
        root = Path(__file__).resolve().parents[1]
        self._run('backup_saved', lambda c: save_bundle(Path(filename), root, c.download_backup()))

    def inspect_backup_file(self):
        if self._busy:
            return
        filename, _ = QFileDialog.getOpenFileName(self, 'Backup prüfen', '', 'MICA-Backup (*.zip *.tar.gz)')
        if filename:
            from desktop.core.update_recovery import inspect_backup
            self._run('backup_checked', lambda _c: inspect_backup(Path(filename)))

    def prepare_update_checkpoint(self):
        if self._busy:
            return
        from desktop.core.update_recovery import prepare_checkpoint
        root = Path(__file__).resolve().parents[1]
        self._run('update_checkpoint', lambda client: prepare_checkpoint(root, client))

    def restore_backup(self):
        if self._busy:
            return
        filename, _ = QFileDialog.getOpenFileName(self, 'MICA-Backup auswählen', '', 'MICA-Backup (*.zip *.tar.gz)')
        if not filename:
            return
        if QMessageBox.question(self, 'Backup wiederherstellen',
            'Das ausgewählte Backup ersetzt Gedächtnis, Einstellungen und Automationen. '
            'Eine Recovery-Kopie wird vorher angelegt. Laufende Sprachaufnahme wird beendet. '
            'Nachher MICA neu starten und den wiederhergestellten Stand prüfen. Fortfahren?',
            defaultButton=QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        if self._busy:
            self.status.setText('Eine andere Anfrage läuft noch; danach erneut versuchen.')
            return
        from desktop.core.desktop_backup import read_bundle, restore_desktop
        root = Path(__file__).resolve().parents[1]
        def restore(client):
            from desktop.core.update_recovery import inspect_backup
            inspect_backup(Path(filename))
            if filename.lower().endswith('.tar.gz'):
                if Path(filename).stat().st_size > 64 * 1024 * 1024:
                    raise ValueError('Backup ist zu groß.')
                return {'backend': client.restore_backup(Path(filename).read_bytes()), 'backend_only': True}
            desktop, archive = read_bundle(Path(filename))
            remote = client.restore_backup(archive)
            try:
                local = restore_desktop(root, desktop)
            except Exception as error:
                return {'backend': remote, 'desktop_error': str(error)}
            return {'backend': remote, 'desktop': local}
        self.restore_busy.emit(True)
        self._run('backup_restored', restore)

    def recovery_status(self):
        self._run('backup_status', lambda c: c.backup_status())

    def download_recovery(self):
        if not self._recovery_id:
            self.status.setText('Zuerst Recovery-Status prüfen oder ein Backup wiederherstellen.')
            return
        filename, _ = QFileDialog.getSaveFileName(self, 'Recovery-Backup speichern', 'mica-recovery.tar.gz', 'Backend-Backup (*.tar.gz)')
        if not filename:
            return
        identifier = self._recovery_id
        def download(client):
            content = client.download_backup(identifier)
            target = Path(filename)
            temporary = target.with_suffix('.partial')
            temporary.write_bytes(content)
            temporary.replace(target)
            return {'path': str(target)}
        self._run('backup_saved', download)

    def refresh_history(self):
        from desktop.core.undo import history_entries
        def load(client):
            result = {'desktop': history_entries(), 'backend': [], 'host': [], 'plans': [], 'backend_error': ''}
            try:
                activity = client.activity()
                result['backend'] = activity['executions']
                result['plans'] = activity.get('plans', [])
                result['host'] = client.action_history()['items']
            except Exception as error:
                result['backend_error'] = str(error)
            return result
        self._run('history', load)

    def undo_host_change(self):
        item = self.host_change.currentData()
        if not item or not item['undo_available']:
            self.status.setText('Keine rückgängig machbare Windows-Dateiänderung ausgewählt.')
            return
        if QMessageBox.question(self, 'Dateiänderung rückgängig machen',
                item['operation'] + '\n' + '\n'.join(item['paths']) +
                '\n\nNur ausführen, wenn die Dateien seitdem unverändert sind?') != QMessageBox.StandardButton.Yes:
            return
        def compensate(client):
            params = {'action': 'undo_change', 'change_id': item['id']}
            plan = client.plan('Dateiänderung rückgängig machen', 'file_controller', params, dry_run=False)['plan']
            permission = plan['permission']
            approval = permission.get('approval_id')
            if approval:
                client.approve(approval)
            elif not permission['allowed']:
                raise RuntimeError(permission['reason'])
            return client.execute(item['id'], 'file_controller', params, approval_id=approval,
                                  idempotency_key='undo:' + item['id'])
        self._run('host_undo', compensate)

    def undo_last(self):
        from desktop.core import undo
        if not undo.can_undo():
            self.status.setText('Keine Desktop-Änderung dieser Sitzung ist rückgängig machbar.')
            return
        entries = undo.history_entries()
        latest = next((item for item in entries if item['is_next_undo']), None)
        if latest is None:
            self.status.setText('Aktionsverlauf nicht verfügbar.')
            return
        label = latest['label']
        if QMessageBox.question(self, 'Änderung rückgängig machen', label) != QMessageBox.StandardButton.Yes:
            return
        self._run('undo', lambda _c: undo.undo_last(expected_id=latest['id']))

    def _refresh_visible(self):
        if self.isVisible() and self.tabs.currentIndex() == 0:
            self.refresh()

    def export_tasks(self):
        snapshot = task_snapshot_markdown(list(self._items), fresh=self._activity_fresh)
        path, _ = QFileDialog.getSaveFileName(self, 'Sichtbare Aufgaben speichern', 'MICA-Aufgaben.md', 'Markdown (*.md)')
        if not path:
            return
        try:
            save_task_snapshot(path, snapshot)
        except OSError:
            self.status.setText('Aufgabenexport konnte nicht gespeichert werden. Speicherort und Zugriffsrechte prüfen.')
            return
        self.status.setText('Sichtbare Aufgaben lokal als Markdown gespeichert.')

    def selected(self):
        row = self.table.currentRow()
        return self._items[row] if 0 <= row < len(self._items) else None

    def _task_permissions(self):
        item = self.selected()
        allowed = dict.fromkeys(('pause', 'resume', 'preview', 'reconcile', 'retry',
                                 'approvals', 'history', 'task_start', 'task_done', 'cancel'), False)
        if not item:
            return allowed
        kind, status = item['kind'], item['status']
        presentation = task_presentation(item)
        allowed['pause'] = kind == 'plan' and status == 'active'
        allowed['resume'] = (kind == 'plan' and status in {'ready', 'paused'}
                             and not presentation['unresolved'] and bool(item.get('dry_run_at'))
                             and item.get('last_error') != 'budget_exhausted'
                             and not self._emergency_stopped)
        allowed['preview'] = (kind == 'plan' and status in {'draft', 'ready', 'paused'}
                              and not item.get('dry_run_at') and not presentation['unresolved']
                              and not self._emergency_stopped)
        allowed['reconcile'] = presentation['unresolved'] and (
            kind == 'execution' or (kind == 'plan' and status == 'paused'))
        allowed['retry'] = (kind == 'execution' and status in {'not_dispatched', 'approval_required'}
                            and bool(item.get('can_retry')) and isinstance(item.get('params'), dict)
                            and not presentation['unresolved'] and not self._emergency_stopped)
        allowed['approvals'] = (presentation['label'] == 'Wartet auf Freigabe' or
                                (kind == 'plan' and status in {'ready', 'paused'}
                                 and item.get('risk') not in {None, 'read'} and not presentation['unresolved']))
        if item.get('last_error') == 'budget_exhausted':
            allowed['approvals'] = False
        allowed['history'] = kind == 'plan' and status == 'cancelled' and presentation['unresolved']
        allowed['task_start'] = kind == 'task' and status == 'open'
        allowed['task_done'] = kind == 'task' and status in {'open', 'in_progress'}
        allowed['cancel'] = ((kind == 'task' and status in {'open', 'in_progress'}) or
                              (kind == 'plan' and status in {'draft', 'ready', 'active', 'paused'}))
        return allowed

    def _update_task_actions(self):
        permissions = self._task_permissions()
        for name in permissions:
            button = getattr(self, name + '_button')
            button.setVisible(permissions[name])
            button.setEnabled(permissions[name] and self._activity_fresh and not self._busy)
        self.refresh_button.setEnabled(not self._busy)
        selected = self.selected()
        if selected and selected['kind'] == 'plan':
            self.resume_button.setText('Starten' if selected['status'] == 'ready' else 'Fortsetzen')

    def _task_action_allowed(self, action):
        if self._busy:
            return False
        if not self._activity_fresh:
            self.status.setText('Aufgabenstand nicht aktuell. Zuerst aktualisieren.')
            return False
        return self._task_permissions()[action]

    def _render_tasks(self, *_args):
        selected = self.selected()
        selected_id = task_identity(selected) if selected else None
        query = self.task_search.text().strip().casefold()
        category = self.task_filter.currentData()
        deadline_filter = self.deadline_filter.currentData()
        now = QDateTime.currentDateTimeUtc()
        deadlines = {task_identity(item): task_deadline(item, now) for item in self._all_items}
        def matches_deadline(item):
            deadline = deadlines[task_identity(item)]['category']
            if deadline_filter == 'all':
                return True
            if deadline_filter == 'high':
                return (item['kind'] == 'task' and item.get('status') in {'open', 'in_progress'}
                        and item.get('priority') == 'high')
            return deadline in {'today', 'overdue'} if deadline_filter == 'today' else deadline == 'overdue'
        self._items = [item for item in self._all_items
                       if (category == 'all' or task_presentation(item)['category'] == category)
                       and matches_deadline(item)
                       and (not query or query in ' '.join(str(item.get(field, ''))
                            for field in ('goal', 'title', 'action', 'description')).casefold())]
        order = self.task_sort.currentData()
        def title(item):
            return str(item.get('goal', item.get('title', item.get('action', '')))).casefold()
        def due_key(item):
            value = deadlines[task_identity(item)]['timestamp']
            return (value is None, value or 0)
        if order == 'title':
            self._items.sort(key=title)
        elif order == 'deadline':
            self._items.sort(key=due_key)
        elif order == 'urgency':
            def urgency(item):
                presentation = task_presentation(item)
                deadline = deadlines[task_identity(item)]['category']
                return (0 if presentation['unresolved'] else 1 if deadline == 'overdue' else
                        2 if deadline == 'today' else 3 if presentation['category'] != 'done' else 4,
                        {'high': 0, 'normal': 1, 'low': 2}.get(item.get('priority', 'normal'), 1),
                        due_key(item), title(item))
            self._items.sort(key=urgency)
        self.table.blockSignals(True)
        try:
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
            self.table.setRowCount(0)
            self.table.setRowCount(len(self._items))
            for row, item in enumerate(self._items):
                presentation = task_presentation(item)
                values = [item.get('goal', item.get('title', item.get('action', ''))),
                          {'plan': 'Plan', 'task': 'Aufgabe', 'execution': 'Ausführung'}[item['kind']],
                          presentation['label'], presentation['progress'], task_timestamp(item.get('updated_at')),
                          {'high': 'Hoch', 'normal': 'Normal', 'low': 'Niedrig'}.get(item.get('priority'), ''),
                          deadlines[task_identity(item)]['label']]
                for col, text in enumerate(values):
                    cell = QTableWidgetItem(str(text))
                    cell.setToolTip(presentation['hint'] if col == 2 else str(text))
                    if col == 2:
                        color = '#b53b50' if (presentation['category'] == 'attention' and presentation['unresolved']) or item['status'] == 'failed' else (
                            '#208361' if item['status'] in {'completed', 'succeeded'} else '#355273')
                        cell.setForeground(QColor(color))
                    if col == 4:
                        cell.setToolTip(item.get('updated_at', ''))
                    if col == 6 and deadlines[task_identity(item)]['category'] in {'overdue', 'invalid'}:
                        cell.setForeground(QColor('#b53b50'))
                    self.table.setItem(row, col, cell)
                if task_identity(item) == selected_id:
                    self.table.selectRow(row)
        finally:
            self.table.blockSignals(False)
        attention = sum(task_presentation(item)['category'] == 'attention' for item in self._all_items)
        overdue = sum(value['category'] == 'overdue' for value in deadlines.values())
        self.task_count.setText(f'{len(self._items)} von {len(self._all_items)} Einträgen · {attention} mit Handlungsbedarf · {overdue} überfällig'
                               if self._activity_fresh else 'Stand nicht aktuell. Aufgaben erneut laden.')
        self.task_empty.setVisible(not self._items)
        self.task_empty.setText('Keine passenden Aufgaben.' if self._all_items else 'Keine Aufgaben vorhanden.')
        self._show_detail()

    def preview(self):
        if self._task_action_allowed('preview'):
            item = self.selected()
            self._run('preview', lambda c: c.preview_plan(item['id']))

    def open_approvals(self):
        if self._busy:
            return
        self.tabs.setCurrentIndex(4)
        self.load_approvals()

    def open_action_history(self):
        if self._busy:
            return
        self.tabs.setCurrentIndex(2)
        self.refresh_history()

    def update_task(self, status):
        action = 'task_start' if status == 'in_progress' else 'task_done'
        if status not in {'in_progress', 'completed'} or not self._task_action_allowed(action):
            return
        item = self.selected()
        self._run('task_updated', lambda c: c.update_task(item['id'], status))

    def cancel_selected(self):
        if not self._task_action_allowed('cancel'):
            return
        item = self.selected()
        title = item.get('goal', item.get('title', ''))
        consequence = ('Weitere Planschritte werden gestoppt. Eine laufende Einzelaktion kann noch abschließen; '
                       'bereits ausgeführte Änderungen bleiben bestehen.' if item['kind'] == 'plan' else
                       'Diese Aufgabe wird als abgebrochen markiert.')
        if QMessageBox.question(self, 'Aufgabe abbrechen', title + '\n\n' + consequence) != QMessageBox.StandardButton.Yes:
            return
        self._run('task_cancelled', lambda c: c.cancel_plan(item['id']) if item['kind'] == 'plan'
                  else c.update_task(item['id'], 'cancelled'))

    def pause(self):
        item = self.selected()
        if self._task_action_allowed('pause'):
            self._run('plan', lambda c: c.pause_plan(item['id']))
        else:
            self.status.setText('Wähle einen aktiven Agentenplan aus.')

    def reconcile_selected(self):
        item = self.selected()
        if not self._task_action_allowed('reconcile'):
            self.status.setText('Eine ungeklärte Ausführung oder einen pausierten Plan auswählen.')
            return
        identifier = item['id'] if item['kind'] == 'plan' else item['key']
        self._run('reconcile', lambda c: c.reconcile(identifier, plan=item['kind'] == 'plan'))

    def load_approvals(self):
        self._run('approvals', lambda c: c.approvals())

    def _approval_selected(self):
        item = self.approval_choice.currentData()
        self.approval_detail.setPlainText(json.dumps(item, ensure_ascii=False, indent=2) if item else 'Keine offene Freigabe ausgewählt.')

    def approve_selected(self):
        item = self.approval_choice.currentData()
        if not item:
            return
        if QMessageBox.question(self, 'Exakte Aktion freigeben',
                item['action'] + '\n\n' + json.dumps(item['params'], ensure_ascii=False, indent=2)) != QMessageBox.StandardButton.Yes:
            return
        self._run('approved', lambda c: {'approval': item, 'result': c.approve(item['id'])})

    def clear_stop(self):
        if QMessageBox.question(self, 'Not-Aus aufheben',
            'Wiederhergestellte Aufgaben und Automationen geprüft? Neue freigegebene Aktionen wieder zulassen?') != QMessageBox.StandardButton.Yes:
            return
        self._run('stop_cleared', lambda c: c.clear_emergency_stop())

    def resume(self):
        item = self.selected()
        if self._task_action_allowed('resume'):
            params = {'plan_hash': item['plan_hash'], 'risk': item['risk'], 'budget': item['budget']}
            action = 'agent.plan.activate'
            blocked = next((step for step in item['steps'] if step['status'] == 'blocked'), None)
            if blocked:
                action, params = blocked['action'], blocked['params']
            approval = next((entry['id'] for entry in reversed(self._approved)
                             if entry['action'] == action and entry['params'] == params), None)
            self._run('plan', lambda c: c.resume_plan(item['id'], approval))
        else:
            self.status.setText('Wähle einen bereiten oder pausierten Plan aus. Unklare Einzelausführungen werden nicht wiederholt.')

    def retry_execution(self):
        item = self.selected()
        if not self._task_action_allowed('retry'):
            self.status.setText('Nur nachweislich nicht ausgeführte Einzelaktionen können fortgesetzt werden.')
            return
        if QMessageBox.question(self, 'Exakte Einzelaktion fortsetzen', item['action'] + '\n\n' +
                json.dumps(item['params'], ensure_ascii=False, indent=2)) != QMessageBox.StandardButton.Yes:
            return
        approval = next((entry['id'] for entry in reversed(self._approved)
                         if entry['action'] == item['action'] and entry['params'] == item['params']), None)
        self._run('plan', lambda c: c.resume_execution(item['key'], approval))

    def _show_detail(self):
        item = self.selected()
        self._update_task_actions()
        if not item:
            self.detail.clear()
            self.task_hint.setText('Keine Aufgabe ausgewählt.')
            return
        presentation = task_presentation(item)
        self.task_hint.setText(presentation['hint'] if self._activity_fresh else 'Stand nicht aktuell. Zuerst aktualisieren.')
        title = item.get('goal', item.get('title', item.get('action', '')))
        reason = item.get('last_error', '')
        lines = [title, 'Status: ' + presentation['label'], item.get('description', ''),
                 TASK_REASONS.get(reason, reason), item.get('detail', '')]
        deadline = task_deadline(item)
        if deadline['label']:
            lines.append('Fällig: ' + deadline['label'])
        if item.get('priority'):
            lines.append('Priorität: ' + {'high': 'Hoch', 'normal': 'Normal', 'low': 'Niedrig'}.get(item['priority'], item['priority']))
        if item.get('params') is not None:
            lines.append(json.dumps(item['params'], ensure_ascii=False, indent=2))
        if item.get('needs_reconciliation'):
            lines.append('Diese Ausführung bleibt gesperrt, bis ihr tatsächliches Ergebnis geklärt ist. Ein Neustart löst keine Wiederholung aus.')
        for step in item.get('steps', []):
            lines.append(f"{step['position']}. {step['action']}: {STATUS_LABELS.get(step['status'], step['status'])}")
        result = item.get('result')
        if result:
            lines.append(str(result.get('output', result)))
        self.detail.setPlainText('\n\n'.join(str(line) for line in lines if line))

    def _received(self, kind, value, error):
        self._busy = False
        self._update_task_actions()
        if kind == 'backup_restored':
            self.restore_busy.emit(False)
        self.probe.setEnabled(True)
        if error:
            if kind in {'backup_checked', 'update_checkpoint', 'backup_saved', 'backup_restored'}:
                self.backup_report.setPlainText('Vorgang fehlgeschlagen.\n\n' + error)
            if kind in {'activity', 'plan', 'task_updated', 'task_cancelled', 'preview', 'reconcile'}:
                self._activity_fresh = False
                self.task_count.setText('Stand nicht aktuell. Aufgaben erneut laden.')
                self._show_detail()
            self.status.setText('Anfrage fehlgeschlagen: ' + error)
            if kind == 'diagnostics':
                self.report.setPlainText('Backend nicht erreichbar oder Anfrage abgelehnt.\n\n'
                    'Backend starten und die lokale HTTPS-Adresse sowie das CA-Zertifikat in den Einstellungen prüfen.\n\n' + error)
            return
        if kind == 'auth':
            self.status.setText('Zugriff für zehn Minuten entsperrt.')
        elif kind == 'backend_started':
            self.status.setText('Startbefehl erfolgreich. Dienstzustand wird jetzt geprüft.')
            self._run('diagnostics', lambda c: c.diagnostics())
        elif kind == 'approvals':
            self.approval_choice.clear()
            for item in value['approvals']:
                self.approval_choice.addItem(item['action'] + ' · ' + item['id'][:8], item)
            self._approval_selected()
            self.status.setText(f"{len(value['approvals'])} offene Freigaben geladen.")
        elif kind == 'approved':
            self._approved.append(value['approval'])
            self.status.setText('Exakte Aktion freigegeben. Den ausgewählten Plan jetzt fortsetzen.')
            self.load_approvals()
        elif kind == 'stop_cleared':
            self.status.setText('Not-Aus aufgehoben. Automationen bleiben deaktiviert, bis du sie einzeln aktivierst.')
        elif kind == 'reconcile':
            resolved = (value.get('resolved_steps') or value.get('resolved')
                        or value.get('status') == 'succeeded'
                        or value.get('plan', {}).get('status') == 'completed')
            self._task_notice = ('Ergebnis bestätigt. Keine Aktion erneut ausgeführt.' if resolved else
                                 'Ergebnis weiterhin unklar. Keine Aktion erneut ausgeführt.')
            self.refresh()
        elif kind == 'preview':
            self._task_notice = 'Vorschau abgeschlossen. Keine Aktion ausgeführt.'
            self.refresh()
        elif kind in {'task_updated', 'task_cancelled'}:
            self._task_notice = 'Aufgabenstatus gespeichert.'
            self.refresh()
        elif kind == 'backup_checked':
            self.backup_report.setPlainText('Backup erfolgreich geprüft. Keine bestehenden Daten verändert.\n\n'
                f"{value['markdown_documents']} Backend-Dokumente.\n" +
                ('Nur Backend-Daten; keine Desktop-Einstellungen.' if value['backend_only'] else
                 f"{value['desktop_files']} Desktop-Dateien.\nProgrammcode und Zugangsschlüssel sind nicht enthalten."))
            self.status.setText('Backup geprüft; keine Wiederherstellung ausgeführt.')
        elif kind == 'update_checkpoint':
            self.backup_report.setPlainText('Update-Sicherung erfolgreich geprüft.\n\n' + value['path'] +
                '\n\nProgrammstand: ' + value['head'][:12] +
                '\nDaten und eingecheckter Programmcode gesichert. Windows-Zugangsschlüssel, Modelle und Python-Umgebung sind nicht enthalten.'
                '\nFür diesen Programmstand höchstens 24 Stunden gültig. Update beim nächsten Start des Installationshelfers.')
            self.status.setText('Update-Sicherung erstellt; noch kein Update ausgeführt.')
        elif kind == 'backup_saved':
            self.backup_report.setPlainText('Backup gespeichert: ' + value['path'])
            self.status.setText('Backup gespeichert.')
        elif kind == 'backup_restored':
            self._recovery_id = value['backend']['recovery_id']
            report = ['Backend wiederhergestellt. Not-Aus bleibt aktiv; Automationen sind deaktiviert.',
                      'Recovery-ID: ' + self._recovery_id]
            if value.get('desktop_error'):
                report.append('Desktop-Wiederherstellung fehlgeschlagen: ' + value['desktop_error'])
            elif not value.get('backend_only'):
                report.extend(['Desktop wiederhergestellt; MICA neu starten.',
                               'Desktop-Recovery: ' + value['desktop']['recovery']])
            self.backup_report.setPlainText('\n\n'.join(report))
            self.status.setText('Backend wiederhergestellt; Desktop-Wiederherstellung fehlgeschlagen.' if value.get('desktop_error') else
                                'Wiederherstellung abgeschlossen; Ergebnis prüfen.')
        elif kind == 'backup_status':
            self._recovery_id = value.get('recovery_id') or self._recovery_id
            self.backup_report.setPlainText('Wiederherstellung unvollständig; Recovery-Backup herunterladen und wiederherstellen.'
                                           if value['maintenance'] else 'Keine unvollständige Wiederherstellung gemeldet.')
            self.status.setText('Recovery-Status geprüft.')
        elif kind == 'activity':
            self._activity_fresh = True
            self._all_items = [{**item, 'kind': kind} for field, kind in
                           [('plans', 'plan'), ('tasks', 'task'), ('executions', 'execution')]
                           for item in value.get(field, [])]
            presence = value.get('presence', {})
            self._emergency_stopped = bool(presence.get('emergency_stopped'))
            self._render_tasks()
            state = 'Not-Aus aktiv' if presence.get('emergency_stopped') else STATUS_LABELS.get(presence.get('state'), presence.get('state', ''))
            self.status.setText(self._task_notice or f"MICA: {state} · {len(self._all_items)} Aufgaben, Pläne und Ausführungen.")
        elif kind == 'diagnostics':
            self.report.setPlainText('\n\n'.join(
                f"{item['label']}: {item['status']}\n{item['detail']}\n{item['remedy']}"
                for item in value['checks']))
            self.status.setText('Prüfung abgeschlossen: ' + value['status'])
        elif kind == 'plan':
            self.refresh()
        elif kind == 'history':
            self.host_change.clear()
            lines = ['Desktop-Änderungen:']
            for item in value['desktop']:
                availability = ('Als Nächstes rückgängig machbar' if item['is_next_undo'] else
                                'In dieser Sitzung rückgängig machbar' if item['undo_available'] else
                                'Keine Rückgängig-Funktion verfügbar')
                lines.append(f"{item['created_at']} · {item['label']} · {item['status']}\n{availability}")
            lines.append('\nBackend-Ausführungen:')
            for item in value['backend']:
                lines.append(f"{item['created_at']} · {item['action']} · {STATUS_LABELS.get(item['status'], item['status'])}")
                if item.get('result'):
                    lines.append(json.dumps(item['result'].get('output'), ensure_ascii=False, indent=2))
            lines.append('\nWindows-Dienst:')
            for item in value.get('host', []):
                availability = 'Rückgängig verfügbar' if item['undo_available'] else 'Rückgängig: ' + item['undo_status']
                lines.append(f"{item['created_at']} · {item['action']} / {item['operation']} · {item['status']}\n" +
                             '\n'.join(item['paths']) + '\n' + availability)
                self.host_change.addItem(item['operation'] + ' · ' + item['id'][:8] + ' · ' + availability, item)
            lines.append('\nPlanausführungen (einschließlich Server-Aktionen):')
            for plan in value.get('plans', []):
                for step in plan['steps']:
                    if step['status'] == 'pending':
                        continue
                    lines.append(plan['goal'] + ' · ' + step['action'] + ' · ' + STATUS_LABELS.get(step['status'], step['status']) +
                                 '\n' + json.dumps(step.get('params', {}), ensure_ascii=False) +
                                 '\nRückgängig: keine geprüfte automatische Funktion verfügbar')
            if value.get('backend_error'):
                lines.append('Backend-Verlauf nicht verfügbar: ' + value['backend_error'])
            self.history_report.setPlainText('\n\n'.join(lines))
            self.status.setText('Aktionsverlauf geladen. Windows-Dateiänderungen können auch nach Neustarts rückgängig sein.')
        elif kind == 'host_undo':
            self.history_report.setPlainText(json.dumps(value, ensure_ascii=False, indent=2))
            self.status.setText('Rückgängig-Ergebnis: ' + STATUS_LABELS.get(value['status'], value['status']))
        elif kind == 'undo':
            self.history_report.setPlainText(str(value))
            self.status.setText(str(value))


MEMORY_KINDS = {
    'memory': 'Erinnerung', 'conversations': 'Gespräch', 'tasks': 'Aufgabenbericht',
    'research': 'Recherche', 'lessons': 'Lerneintrag', 'runbooks': 'Ablauf',
    'knowledge': 'Wissen', 'code': 'Code',
    'reflection': 'Rückblick', 'reflections': 'Rückblick', 'notes': 'Notiz',
}


def memory_certainty(item):
    if item.get('inferred') is True or item.get('kind') in {'reflection', 'reflections'}:
        return 'inferred', 'Vermutung'
    if item.get('explicitly_remembered') is True:
        return 'explicit', 'Von dir gespeichert'
    if item.get('confirmed') is True:
        return 'confirmed', 'Bestätigt'
    return 'unconfirmed', 'Unbestätigt'


class BackendMemoryPage(ApiPage):
    remember_changed = pyqtSignal(bool)

    def __init__(self, parent=None, client_factory=LocalCoreClient):
        super().__init__(parent, client_factory)
        self._items = []
        self._all_items = []
        self._editing_item = None
        self._baseline = ('', '')
        self._fresh = False
        self._conflict = False
        self._unlocked = False
        self._saving = False
        self._save_operation = ''
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        title = QLabel('Gedächtnis')
        title.setStyleSheet('font-size: 24px; font-weight: 600;')
        layout.addWidget(title)
        self.private = QCheckBox('Neue Gespräche nicht dauerhaft speichern (Text und Sprache)')
        self.private.toggled.connect(lambda checked: self.remember_changed.emit(not checked))
        layout.addWidget(self.private)
        self.status = QLabel('Noch keine Informationen geladen.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Gedächtnis durchsuchen')
        self.search.textChanged.connect(self._render_memory)
        row.addWidget(self.search, 1)
        self.certainty_filter = QComboBox()
        for label, key in [('Alle', 'all'), ('Von dir gespeichert', 'explicit'),
                           ('Bestätigt', 'confirmed'), ('Vermutungen', 'inferred'), ('Unbestätigt', 'unconfirmed')]:
            self.certainty_filter.addItem(label, key)
        self.certainty_filter.currentIndexChanged.connect(self._render_memory)
        row.addWidget(self.certainty_filter)
        self.refresh_button = QPushButton()
        self.refresh_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.refresh_button.setToolTip('Gedächtnis aktualisieren')
        self.refresh_button.setFixedSize(38, 38)
        self.refresh_button.clicked.connect(self.refresh)
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        self.count = QLabel('Noch keine Informationen geladen.')
        layout.addWidget(self.count)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Titel', 'Art', 'Einordnung', 'Geändert'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 4):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().hide()
        self.table.itemSelectionChanged.connect(self._selected)
        layout.addWidget(self.table, 1)
        self.metadata = QTextEdit()
        self.metadata.setReadOnly(True)
        self.metadata.setMaximumHeight(100)
        layout.addWidget(self.metadata)
        editor_row = QHBoxLayout()
        self.title = QLineEdit()
        self.title.setMaxLength(160)
        self.title.setPlaceholderText('Titel einer neuen Information')
        self.title.textChanged.connect(self._update_controls)
        editor_row.addWidget(self.title, 1)
        self.new_button = QPushButton()
        self.new_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
        self.new_button.setToolTip('Neue Information')
        self.new_button.setFixedSize(38, 38)
        self.new_button.clicked.connect(self.new_entry)
        editor_row.addWidget(self.new_button)
        self.reload_button = QPushButton()
        self.reload_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.reload_button.setToolTip('Gespeicherten Eintrag neu laden und Entwurf verwerfen')
        self.reload_button.setFixedSize(38, 38)
        self.reload_button.clicked.connect(self.reload_entry)
        editor_row.addWidget(self.reload_button)
        layout.addLayout(editor_row)
        self.body = QTextEdit()
        self.body.setPlaceholderText('Information hinzufügen oder ausgewählten Inhalt korrigieren')
        self.body.textChanged.connect(self._update_controls)
        layout.addWidget(self.body, 1)
        buttons = QHBoxLayout()
        self.unlock_button = QPushButton('Bearbeitung entsperren')
        self.unlock_button.clicked.connect(self.unlock)
        buttons.addWidget(self.unlock_button)
        self.remember_button = QPushButton('Dauerhaft merken')
        self.remember_button.clicked.connect(self.remember)
        buttons.addWidget(self.remember_button)
        self.correct_button = QPushButton('Korrektur speichern')
        self.correct_button.clicked.connect(self.correct)
        buttons.addWidget(self.correct_button)
        self.forget_button = QPushButton()
        self.forget_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        self.forget_button.setToolTip('Ausgewählten Eintrag löschen')
        self.forget_button.clicked.connect(self.forget)
        buttons.addWidget(self.forget_button)
        layout.addLayout(buttons)
        self._auth_timer = QTimer(self)
        self._auth_timer.setSingleShot(True)
        self._auth_timer.timeout.connect(self._lock_editing)
        self._load_editor(None)

    def _lock_editing(self):
        self._unlocked = False
        self.status.setText('Bearbeitung wieder gesperrt. Der Entwurf bleibt erhalten.')
        self._update_controls()

    def _run(self, kind, action):
        if self._busy:
            return
        self._saving = kind == 'saved'
        super()._run(kind, action)
        self._update_controls()

    def _dirty(self):
        return (self.title.text(), self.body.toPlainText()) != self._baseline

    def _update_controls(self):
        if not hasattr(self, 'forget_button'):
            return
        editable = self._unlocked and self._fresh and not self._busy and not self._conflict
        self.remember_button.setVisible(self._editing_item is None)
        self.correct_button.setVisible(self._editing_item is not None)
        self.remember_button.setEnabled(editable and bool(self.title.text().strip()) and bool(self.body.toPlainText().strip()))
        self.correct_button.setEnabled(editable and self._editing_item is not None and self._dirty())
        self.forget_button.setEnabled(editable and self._editing_item is not None)
        self.new_button.setEnabled(not self._busy)
        self.reload_button.setVisible(self._editing_item is not None)
        self.reload_button.setEnabled(not self._busy and self._fresh and any(
            item['id'] == self._editing_item['id'] for item in self._all_items) if self._editing_item else False)
        self.refresh_button.setEnabled(not self._busy)
        self.unlock_button.setEnabled(not self._busy)
        self.unlock_button.setText('Bearbeitung entsperrt' if self._unlocked else 'Bearbeitung entsperren')
        self.table.setEnabled(not self._busy)
        self.body.setReadOnly(self._saving)
        self.title.setReadOnly(self._saving or self._editing_item is not None)

    def _discard_allowed(self):
        return not self._dirty() or QMessageBox.question(
            self, 'Entwurf verwerfen', 'Die nicht gespeicherten Änderungen verwerfen?',
            defaultButton=QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _load_editor(self, item):
        self._editing_item = dict(item) if item else None
        self._conflict = False
        self._baseline = (item.get('title', ''), item.get('body', '')) if item else ('', '')
        self.title.setMaxLength(max(160, len(self._baseline[0])))
        self.title.setText(self._baseline[0])
        self.body.setPlainText(self._baseline[1])
        self._show_metadata(item)
        self._update_controls()

    def _show_metadata(self, item):
        if not item:
            self.metadata.setPlainText('Neue Information')
            return
        source = str(item.get('source', ''))
        if source == 'desktop_user':
            source = 'Direkt von dir gespeichert'
        sources = item.get('sources', [])
        lines = [memory_certainty(item)[1], 'Herkunft: ' + (source or 'Nicht angegeben'),
                 'Gespeichert: ' + task_timestamp(item.get('created_at')),
                 'Geändert: ' + task_timestamp(item.get('updated_at') or item.get('created_at'))]
        if isinstance(sources, list):
            lines.extend(str(value) for value in sources)
        self.metadata.setPlainText('\n'.join(lines))

    def new_entry(self):
        if self._busy or not self._discard_allowed():
            return
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.table.blockSignals(False)
        self._load_editor(None)

    def reload_entry(self):
        if self._busy or not self._editing_item or not self._discard_allowed():
            return
        item = next((entry for entry in self._all_items if entry['id'] == self._editing_item['id']), None)
        if item:
            self._load_editor(item)

    def _render_memory(self, *_args):
        if not hasattr(self, 'table'):
            return
        query, certainty = self.search.text().strip().casefold(), self.certainty_filter.currentData()
        self._items = [item for item in self._all_items
                       if (certainty == 'all' or memory_certainty(item)[0] == certainty)
                       and (not query or query in ' '.join(str(item.get(key, ''))
                            for key in ('title', 'body', 'source', 'sources')).casefold())]
        self.table.blockSignals(True)
        try:
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
            self.table.setRowCount(0)
            self.table.setRowCount(len(self._items))
            for row, item in enumerate(self._items):
                values = [item.get('title', ''), MEMORY_KINDS.get(item.get('kind'), item.get('kind', '')),
                          memory_certainty(item)[1], task_timestamp(item.get('updated_at') or item.get('created_at'))]
                for column, text in enumerate(values):
                    cell = QTableWidgetItem(str(text))
                    cell.setToolTip(str(text))
                    if column == 2 and memory_certainty(item)[0] in {'inferred', 'unconfirmed'}:
                        cell.setForeground(QColor('#996012'))
                    self.table.setItem(row, column, cell)
                if self._editing_item and item['id'] == self._editing_item['id']:
                    self.table.selectRow(row)
        finally:
            self.table.blockSignals(False)
        self.count.setText(f'{len(self._items)} von {len(self._all_items)} Informationen' if self._fresh else 'Stand nicht aktuell.')
        self._update_controls()

    def refresh(self):
        self._run('memory', lambda c: c.memory_items())

    def selected(self):
        return self._editing_item

    def _selected(self):
        row = self.table.currentRow()
        item = self._items[row] if 0 <= row < len(self._items) else None
        if not item or self._busy or (self._editing_item and item['id'] == self._editing_item['id']):
            return
        if not self._discard_allowed():
            self._render_memory()
            return
        self._load_editor(item)

    def remember(self):
        if not self.remember_button.isEnabled() or self._editing_item:
            return
        title, body = self.title.text().strip(), self.body.toPlainText().strip()
        if not title or not body:
            self.status.setText('Titel und Inhalt eingeben.')
            return
        self._save_operation = 'create'
        self._run('saved', lambda c: c.remember_item(title, body))

    def correct(self):
        if not self.correct_button.isEnabled():
            return
        item, body = self.selected(), self.body.toPlainText()
        if not item:
            self.status.setText('Eine gespeicherte Information auswählen.')
            return
        self._save_operation = 'correct'
        self._run('saved', lambda c: c.correct_memory(item['id'], body))

    def forget(self):
        if not self.forget_button.isEnabled():
            return
        item = self.selected()
        if not item:
            return
        if QMessageBox.question(self, 'Information löschen',
                f"„{item['title']}“ aus dem Backend-Gedächtnis löschen?" +
                ('\n\nDer ungespeicherte Entwurf wird ebenfalls verworfen.' if self._dirty() else ''),
                defaultButton=QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self._save_operation = 'forget'
        self._run('saved', lambda c: c.forget_memory(item['id']))

    def _received(self, kind, value, error):
        self._busy = False
        self._saving = False
        if error:
            if kind in {'memory', 'saved'}:
                self._fresh = False
                self.count.setText('Stand nicht aktuell. Gedächtnis erneut laden.')
            self.status.setText('Anfrage fehlgeschlagen: ' + error)
        elif kind == 'auth':
            self._unlocked = True
            self._auth_timer.start(600000)
            self.status.setText('Bearbeitung für zehn Minuten entsperrt.')
        elif kind == 'saved':
            document = value.get('document') if isinstance(value, dict) else None
            if self._save_operation == 'forget':
                self._load_editor(None)
            elif document:
                self._load_editor({**(self._editing_item or {}), **document,
                                   'title': self.title.text(), 'body': self.body.toPlainText()})
            self.refresh()
        elif kind == 'memory':
            self._all_items = value['items']
            self._fresh = True
            if self._editing_item:
                remote = next((item for item in self._all_items if item['id'] == self._editing_item['id']), None)
                changed = remote is None or any(remote.get(key) != self._editing_item.get(key)
                                               for key in ('body', 'updated_at'))
                if remote and not self._dirty():
                    self._load_editor(remote)
                elif changed:
                    self._conflict = True
                    self.metadata.setPlainText('Der gespeicherte Eintrag wurde geändert oder gelöscht. Dein Entwurf bleibt erhalten.')
            self._render_memory()
            self.status.setText('Entwurf erhalten; gespeicherten Stand vor einer Korrektur neu laden.' if self._conflict else
                                f'{len(self._all_items)} Informationen im lokalen Backend.')
        self._update_controls()
