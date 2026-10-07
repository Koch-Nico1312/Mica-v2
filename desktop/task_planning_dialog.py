"""Task editing, ordered step previews, time-box planning and explicit offline reconciliation."""
from datetime import datetime, UTC
import threading
import uuid
from zoneinfo import ZoneInfo
from PyQt6.QtCore import Qt, QDate, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QTabWidget, QWidget, QTableWidget, QTableWidgetItem,
    QSpinBox, QComboBox, QDateEdit, QMessageBox)
from desktop.core.offline_tasks import OfflineTasks
from desktop.core.day_planner import build_day_plan
from desktop.core.local_state import DATA_DIR, read_json, write_json

STATUSES = {'open': 'Offen', 'in_progress': 'In Arbeit', 'completed': 'Erledigt', 'cancelled': 'Abgebrochen'}
PRIORITIES = {'low': 'Niedrig', 'normal': 'Normal', 'high': 'Hoch'}


class StepsDialog(QDialog):
    def __init__(self, parent, steps):
        super().__init__(parent)
        self.setWindowTitle('Schrittfolge prüfen und bearbeiten')
        self.resize(720, 440)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Die Reihenfolge bildet Voraussetzungen. Dauern sind Schätzungen. Es wird noch nichts ausgeführt.'))
        self.table = QTableWidget(len(steps), 3)
        self.table.setHorizontalHeaderLabels(['Schritt', 'Beschreibung', 'Minuten'])
        self.table.horizontalHeader().setStretchLastSection(True)
        for row, step in enumerate(steps):
            for column, key in enumerate(('title', 'description', 'minutes')):
                self.table.setItem(row, column, QTableWidgetItem(str(step.get(key, ''))))
        layout.addWidget(self.table)
        self.status = QLabel()
        layout.addWidget(self.status)
        save = QPushButton('Diese Schrittfolge lokal vormerken')
        save.clicked.connect(self.validate)
        layout.addWidget(save)
        cancel = QPushButton('Verwerfen')
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)

    def validate(self):
        try:
            self.steps = [{'title': self.table.item(row, 0).text().strip(), 'description': self.table.item(row, 1).text(),
                'minutes': int(self.table.item(row, 2).text())} for row in range(self.table.rowCount())]
            if any(not 1 <= len(step['title']) <= 160 or len(step['description']) > 2000 or not 5 <= step['minutes'] <= 240 for step in self.steps):
                raise ValueError('Titel: 1–160 Zeichen, Beschreibung: höchstens 2.000 Zeichen, Dauer: 5–240 Minuten.')
            self.accept()
        except (ValueError, AttributeError) as error:
            self.status.setText(str(error))


class TaskPlanningDialog(QDialog):
    _done = pyqtSignal(str, object, str)

    def __init__(self, parent, operation, *, store=None, page='tasks'):
        super().__init__(parent)
        self.operation, self.store = operation, store or OfflineTasks()
        self.busy, self.tasks, self.plan, self.review = False, [], None, []
        self.setWindowTitle('Aufgaben und Tagesplanung · auch offline')
        self.resize(820, 740)
        layout = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.task_tab, self.plan_tab, self.sync_tab = QWidget(), QWidget(), QWidget()
        self.tabs.addTab(self.task_tab, 'Aufgaben')
        self.tabs.addTab(self.plan_tab, 'Tagesplan')
        self.tabs.addTab(self.sync_tab, 'Abgleich')
        self.build_tasks()
        self.build_plan()
        self.build_sync()
        close = QPushButton('Schließen')
        close.clicked.connect(self.reject)
        layout.addWidget(close)
        self._done.connect(self.finished_operation)
        self.refresh_local()
        self.tabs.setCurrentIndex(1 if page == 'plan' else 2 if page == 'sync' else 0)

    def build_tasks(self):
        layout = QVBoxLayout(self.task_tab)
        layout.addWidget(QLabel('Änderungen werden lokal vorgemerkt. Erst unter Abgleich bestätigst du die Übernahme ins Backend.'))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['Planen', 'Aufgabe', 'Minuten', 'Frist', 'Status'])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.select_task)
        layout.addWidget(self.table)
        form = QFormLayout()
        self.title, self.due = QLineEdit(), QLineEdit()
        self.title.setMaxLength(160)
        self.due.setPlaceholderText('Optional: 2026-10-08T18:00:00+02:00')
        self.due.setMaxLength(64)
        self.description = QPlainTextEdit()
        self.description.setMaximumHeight(75)
        self.minutes = QSpinBox()
        self.minutes.setRange(5, 1440)
        self.minutes.setValue(30)
        self.state, self.priority, self.depends = QComboBox(), QComboBox(), QComboBox()
        for key, title in STATUSES.items():
            self.state.addItem(title, key)
        for key, title in PRIORITIES.items():
            self.priority.addItem(title, key)
        self.priority.setCurrentIndex(1)
        for label, widget in [('Titel', self.title), ('Beschreibung / Quellen', self.description), ('Dauer in Minuten', self.minutes),
            ('Frist', self.due), ('Status', self.state), ('Priorität', self.priority), ('Voraussetzung', self.depends)]:
            form.addRow(label, widget)
        layout.addLayout(form)
        row = QHBoxLayout()
        for title, callback in [('Neue Aufgabe', self.new_task), ('Änderung lokal vormerken', self.stage), ('In Schritte zerlegen', self.decompose)]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        self.new_task()

    def build_plan(self):
        layout = QVBoxLayout(self.plan_tab)
        note = QLabel('Wähle unter Aufgaben die zu planenden Aufgaben. Gib nur freie Zeitfenster an; feste Termine und bereits belegte Zeiten aussparen. Der Plan berücksichtigt Fristen, Priorität, Voraussetzungen und Pausen. Nicht passende Aufgaben bleiben sichtbar.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        layout.addWidget(self.date)
        self.windows = QPlainTextEdit('09:00-12:00\n14:00-17:00')
        self.windows.setMaximumHeight(75)
        layout.addWidget(QLabel('Freie Zeitfenster, je Zeile HH:MM-HH:MM (Europe/Vienna):'))
        layout.addWidget(self.windows)
        form = QFormLayout()
        self.focus, self.pause = QSpinBox(), QSpinBox()
        self.focus.setRange(5, 120)
        self.focus.setValue(45)
        self.pause.setRange(0, 60)
        self.pause.setValue(10)
        form.addRow('Fokus je Block (Minuten)', self.focus)
        form.addRow('Pause zwischen Blöcken (Minuten)', self.pause)
        layout.addLayout(form)
        preview = QPushButton('Tagesplan vorschlagen')
        preview.clicked.connect(self.preview_plan)
        layout.addWidget(preview)
        self.plan_text = QPlainTextEdit()
        self.plan_text.setReadOnly(True)
        layout.addWidget(self.plan_text)
        self.accept_plan = QPushButton('Geprüften Tagesplan übernehmen')
        self.accept_plan.setEnabled(False)
        self.accept_plan.clicked.connect(self.save_plan)
        layout.addWidget(self.accept_plan)
        try:
            saved = read_json(DATA_DIR / 'day-plan.json', limit=2 * 1024 * 1024)
            self.plan_text.setPlainText('Zuletzt übernommener Plan:\n' + self.format_plan(saved))
        except (OSError, ValueError, TypeError, KeyError):
            pass
        for signal in (self.windows.textChanged, self.date.dateChanged, self.focus.valueChanged, self.pause.valueChanged, self.table.itemChanged):
            signal.connect(self.invalidate_plan)

    def build_sync(self):
        layout = QVBoxLayout(self.sync_tab)
        layout.addWidget(QLabel('Eine Verbindung löst keine Übernahme aus. Prüfe erst jede vorgemerkte Änderung.'))
        refresh = QPushButton('Aktuelle Aufgaben laden (ohne Änderungen zu senden)')
        refresh.clicked.connect(lambda: self.run('refresh', {}))
        layout.addWidget(refresh)
        preview = QPushButton('Vorgemerkte Änderungen mit Backend vergleichen')
        preview.clicked.connect(lambda: self.run('preview', {}))
        layout.addWidget(preview)
        self.review_table = QTableWidget(0, 4)
        self.review_table.setHorizontalHeaderLabels(['Übernehmen', 'Aufgabe', 'Änderung', 'Vergleich'])
        self.review_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.review_table)
        self.review_text = QPlainTextEdit()
        self.review_text.setReadOnly(True)
        layout.addWidget(self.review_text)
        self.review_table.itemSelectionChanged.connect(self.show_review)
        apply = QPushButton('Ausgewählte geprüfte Änderungen übernehmen')
        apply.clicked.connect(self.apply_review)
        layout.addWidget(apply)
        keep = QPushButton('Für ausgewählten Konflikt den Backend-Stand behalten')
        keep.clicked.connect(self.accept_remote)
        layout.addWidget(keep)
        discard = QPushButton('Ungesendete lokale Änderung verwerfen')
        discard.clicked.connect(self.discard)
        layout.addWidget(discard)

    def refresh_local(self):
        data = self.store.read()
        self.tasks = self.store.view()
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.tasks))
        for row, task in enumerate(self.tasks):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Checked if task.get('status') in {'open', 'in_progress'} and not task.get('container') else Qt.CheckState.Unchecked)
            self.table.setItem(row, 0, check)
            values = [task['title'] + (' · lokal' if task.get('pending') else ''), str(task.get('minutes', 30)), task.get('due_at') or '—', STATUSES[task['status']]]
            for column, value in enumerate(values, 1):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.blockSignals(False)
        self.status.setText('Lokaler Stand · zuletzt geladen: ' + (data['fetched_at'] or 'noch nie') + ' · ' + str(len(data['pending'])) + ' vorgemerkte Änderungen. Backend-Verbindung wurde hier nicht geprüft.')
        self.invalidate_plan()
        self.review = []
        self.review_table.setRowCount(0)

    def new_task(self):
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.table.blockSignals(False)
        self.editing_id = None
        self.title.clear()
        self.description.clear()
        self.due.clear()
        self.state.setCurrentIndex(0)
        self.minutes.setValue(30)
        self.fill_dependencies()

    def reject(self):
        if self.busy:
            self.status.setText('Vorgang läuft noch. Danach kannst du das Fenster schließen.')
            return
        super().reject()

    def fill_dependencies(self, selected=None):
        self.depends.clear()
        self.depends.addItem('Keine', None)
        for task in self.tasks:
            if task['id'] != self.editing_id:
                self.depends.addItem(task['title'], task['id'])
        if selected:
            self.depends.setCurrentIndex(max(0, self.depends.findData(selected)))

    def select_task(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.tasks):
            return
        task = self.tasks[row]
        self.editing_id = task['id']
        self.title.setText(task['title'])
        self.description.setPlainText(task.get('description', ''))
        self.due.setText(task.get('due_at') or '')
        self.minutes.setValue(task.get('minutes', 30))
        self.state.setCurrentIndex(self.state.findData(task['status']))
        self.priority.setCurrentIndex(self.priority.findData(task.get('priority', 'normal')))
        self.fill_dependencies(next(iter(task.get('depends_on', [])), None))

    def stage(self):
        task = {'id': self.editing_id or uuid.uuid4().hex, 'title': self.title.text().strip(),
            'description': self.description.toPlainText(), 'due_at': self.due.text().strip() or None,
            'status': self.state.currentData(), 'priority': self.priority.currentData()}
        self.run('stage', {'task': task, 'minutes': self.minutes.value(), 'depends_on': [self.depends.currentData()] if self.depends.currentData() else []})

    def decompose(self):
        if not self.title.text().strip():
            self.status.setText('Zuerst eine Aufgabe auswählen oder einen Titel eingeben.')
            return
        self.decomposition_parent = {'id': self.editing_id, 'title': self.title.text().strip(), 'due_at': self.due.text().strip() or None}
        self.run('decompose', {'title': self.title.text().strip(), 'description': self.description.toPlainText()})

    def run(self, action, payload):
        if self.busy:
            return
        self.busy = True
        self.tabs.setEnabled(False)
        self.status.setText('Vorgang läuft …')
        def worker():
            try:
                result, error = self.operation(action, payload, self.store), ''
            except Exception as exception:
                result, error = None, str(exception)
            self._done.emit(action, result, error)
        threading.Thread(target=worker, name='mica-task-planning', daemon=True).start()

    def finished_operation(self, action, result, error):
        self.busy = False
        self.tabs.setEnabled(True)
        if error:
            self.refresh_local()
            self.status.setText('Vorgang nicht abgeschlossen: ' + error + ' · Lokale Daten bleiben erhalten. Für eine erneute Übernahme zuerst den Abgleich öffnen.')
            return
        if action == 'preview':
            self.review = result
            self.review_table.setRowCount(len(result))
            for row, item in enumerate(result):
                check = QTableWidgetItem()
                check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable if not item['conflict'] else Qt.ItemFlag.ItemIsEnabled)
                check.setCheckState(Qt.CheckState.Unchecked)
                self.review_table.setItem(row, 0, check)
                for column, value in enumerate((item['desired']['title'], 'Neu' if item['kind'] == 'create' else 'Bearbeitet', 'Konflikt' if item['conflict'] else 'Bereits übernommen' if item['applied'] else 'Passt zur Ausgangsfassung'), 1):
                    self.review_table.setItem(row, column, QTableWidgetItem(value))
            self.status.setText('Vergleich geladen. Keine Änderung wurde gesendet. Konflikte werden nicht überschrieben.')
        elif action == 'decompose':
            dialog = StepsDialog(self, result['steps'])
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.run('steps', {'steps': dialog.steps, 'parent': self.decomposition_parent})
        else:
            self.refresh_local()
            self.status.setText('Backend-Stand geladen; lokale Änderungen weiter vorgemerkt.' if action == 'refresh' else 'Vorgang abgeschlossen. Änderungen lokal vorgemerkt.' if action in {'stage', 'steps'} else 'Abgleich abgeschlossen. Prüfe verbleibende lokale Änderungen.')

    def show_review(self):
        import json
        row = self.review_table.currentRow()
        if 0 <= row < len(self.review):
            item = self.review[row]
            self.review_text.setPlainText('Backend:\n' + json.dumps(item['remote'], ensure_ascii=False, indent=2) + '\n\nGewünschter lokaler Stand:\n' + json.dumps(item['desired'], ensure_ascii=False, indent=2))

    def apply_review(self):
        selected = [item for row, item in enumerate(self.review) if self.review_table.item(row, 0).checkState() == Qt.CheckState.Checked and not item['conflict']]
        if selected and QMessageBox.question(self, 'Änderungen übernehmen', f'{len(selected)} geprüfte Änderungen ins Backend übernehmen?') == QMessageBox.StandardButton.Yes:
            self.run('apply', {'preview': selected})

    def accept_remote(self):
        row = self.review_table.currentRow()
        if 0 <= row < len(self.review) and self.review[row]['conflict'] and QMessageBox.question(self, 'Backend-Stand behalten', 'Die lokale Änderung für diese Aufgabe verwerfen und den geprüften Backend-Stand behalten?') == QMessageBox.StandardButton.Yes:
            self.run('accept_remote', {'reviewed': self.review[row]})

    def discard(self):
        row = self.review_table.currentRow()
        if 0 <= row < len(self.review) and QMessageBox.question(self, 'Änderung verwerfen', 'Diese ungesendete lokale Änderung verwerfen?') == QMessageBox.StandardButton.Yes:
            self.run('discard', {'key': self.review[row]['key']})

    def invalidate_plan(self, *args):
        self.plan = None
        self.accept_plan.setEnabled(False)

    def planning_input(self):
        day = self.date.date().toPyDate()
        zone = ZoneInfo('Europe/Vienna')
        windows = []
        for line in self.windows.toPlainText().splitlines():
            if not line.strip():
                continue
            start, end = line.strip().split('-')
            windows.append((datetime.combine(day, datetime.strptime(start.strip(), '%H:%M').time(), zone),
                datetime.combine(day, datetime.strptime(end.strip(), '%H:%M').time(), zone)))
            for moment in windows[-1]:
                if moment.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != moment.replace(tzinfo=None):
                    raise ValueError('Diese Uhrzeit existiert wegen der Zeitumstellung nicht. Bitte ein anderes Zeitfenster wählen.')
                if moment.replace(fold=0).utcoffset() != moment.replace(fold=1).utcoffset():
                    raise ValueError('Diese Uhrzeit kommt bei der Zeitumstellung doppelt vor. Bitte ein eindeutiges Zeitfenster wählen.')
        live = {task['id']: task for task in self.store.view()}
        identifiers = [task['id'] for row, task in enumerate(self.tasks) if self.table.item(row, 0).checkState() == Qt.CheckState.Checked or task.get('status') == 'completed']
        if any(identifier not in live for identifier in identifiers):
            raise ValueError('Eine ausgewählte Aufgabe fehlt inzwischen im lokalen Stand. Bitte die Aufgaben neu laden.')
        selected = [live[identifier] for identifier in identifiers]
        return [{**task, 'minutes': task.get('minutes', 30)} for task in selected], windows

    def preview_plan(self):
        try:
            tasks, windows = self.planning_input()
            self.plan = build_day_plan(tasks, windows, break_minutes=self.pause.value(), focus_minutes=self.focus.value())
            self.plan_text.setPlainText(self.format_plan(self.plan))
            self.accept_plan.setEnabled(True)
        except (ValueError, KeyError) as error:
            self.invalidate_plan()
            self.plan_text.setPlainText('Plan nicht erstellt: ' + str(error))

    @staticmethod
    def format_plan(plan):
        rows = ['Vorschau · keine Aufgabe oder Erinnerung wird gestartet.']
        for block in plan['blocks']:
            rows.append(datetime.fromisoformat(block['start']).strftime('%d.%m. %H:%M') + '–' + datetime.fromisoformat(block['end']).strftime('%H:%M') + ' · ' + block['title'])
        rows += ['', 'Noch nicht eingeplant:'] + [item['title'] + ' · ' + str(item['minutes']) + ' Minuten · ' + item['reason'] for item in plan['unplanned']]
        rows += plan['warnings']
        return '\n'.join(rows)

    def save_plan(self):
        if not self.plan:
            return
        try:
            tasks, windows = self.planning_input()
            current = build_day_plan(tasks, windows, break_minutes=self.pause.value(), focus_minutes=self.focus.value())
            if current['fingerprint'] != self.plan['fingerprint']:
                raise ValueError('Eingaben änderten sich. Bitte erneut einen Plan vorschlagen.')
            write_json(DATA_DIR / 'day-plan.json', self.plan | {'accepted_at': datetime.now().astimezone().isoformat()})
            self.status.setText('Geprüfter Tagesplan lokal übernommen. Es wird keine Aufgabe automatisch ausgeführt.')
        except (ValueError, OSError) as error:
            self.status.setText(str(error))
