"""Task editing, ordered step previews, time-box planning and explicit offline reconciliation."""
from datetime import datetime, UTC
import threading
import uuid
from zoneinfo import ZoneInfo
from PyQt6.QtCore import Qt, QDate, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QTabWidget, QWidget, QTableWidget, QTableWidgetItem,
    QSpinBox, QComboBox, QDateEdit, QMessageBox, QCheckBox, QFileDialog)
from desktop.core.offline_tasks import OfflineTasks
from desktop.core.local_state import DATA_DIR, FileLease, read_json, write_json
from desktop.core.planning_extensions import block_id, calendar_busy, extended_plan, fingerprint_plan, parse_adjustment, study_tasks

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

    def __init__(self, parent, operation, *, store=None, page='tasks', adjustment=''):
        super().__init__(parent)
        self.operation, self.store = operation, store or OfflineTasks()
        self.busy, self.tasks, self.plan, self.review = False, [], None, []
        self.previous, self.preview_now = None, None
        self.setWindowTitle('Aufgaben und Tagesplanung · auch offline')
        self.resize(900, 900)
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
        if adjustment:
            self.adjustment.setText(adjustment)

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
        criteria = QPushButton('Erledigt, wenn … · Prüfung für gewählte Aufgabe')
        criteria.clicked.connect(self.open_criteria)
        layout.addWidget(criteria)
        self.new_task()

    def open_criteria(self):
        if not self.editing_id:
            self.status.setText('Zuerst eine lokal gespeicherte Aufgabe auswählen.')
            return
        from desktop.task_criteria_dialog import TaskCriteriaDialog
        try:
            TaskCriteriaDialog(self, self.editing_id, self.operation, self.store).exec()
        except (OSError, ValueError) as error:
            self.status.setText('Aufgabenprüfung nicht lesbar: ' + str(error))
            return
        self.refresh_local()

    def build_plan(self):
        layout = QVBoxLayout(self.plan_tab)
        note = QLabel('Wähle unter Aufgaben die zu planenden Aufgaben und deine verfügbaren Zeiten. Aus einer ausgewählten Kalenderdatei werden belegte Termine abgezogen. Vorschläge und Anpassungen werden erst nach deiner Übernahme gespeichert.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        layout.addWidget(self.date)
        self.windows = QPlainTextEdit('09:00-12:00\n14:00-17:00')
        self.windows.setMaximumHeight(75)
        layout.addWidget(QLabel('Freie Zeitfenster, je Zeile HH:MM-HH:MM (Europe/Vienna):'))
        layout.addWidget(self.windows)
        calendar_row = QHBoxLayout()
        self.calendar_path = QLineEdit()
        self.calendar_path.setPlaceholderText('Optional: lokale Kalenderdatei (.ics), nur lesend')
        calendar_row.addWidget(self.calendar_path)
        choose = QPushButton('Kalender auswählen')
        choose.clicked.connect(self.choose_calendar)
        calendar_row.addWidget(choose)
        layout.addLayout(calendar_row)
        self.include_cards = QCheckBox('Fällige und zuletzt schwierige Lernkarten als kurze Lernblöcke einplanen')
        layout.addWidget(self.include_cards)
        self.adjustment = QLineEdit()
        self.adjustment.setMaxLength(240)
        self.adjustment.setPlaceholderText('Gespeicherten Plan anpassen: Ich habe erst ab 15 Uhr Zeit')
        layout.addWidget(self.adjustment)
        layout.addWidget(QLabel('Auch: Aufgabe Bericht dauert 60 Minuten. Gemeint ist die offene Restdauer.'))
        self.progress_blocks = QComboBox()
        layout.addWidget(self.progress_blocks)
        done = QPushButton('Gewählten Arbeitsblock als abgeschlossen merken')
        done.clicked.connect(self.complete_block)
        layout.addWidget(done)
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
        self.study_blocks = QComboBox()
        layout.addWidget(self.study_blocks)
        learn = QPushButton('Lernkarten des gewählten Blocks wiederholen')
        learn.clicked.connect(self.open_study_block)
        layout.addWidget(learn)
        try:
            saved = read_json(DATA_DIR / 'day-plan.json', limit=2 * 1024 * 1024)
            self.previous = saved
            inputs = saved.get('request', saved.get('inputs', {}))
            if inputs.get('windows'):
                from desktop.core.planning_extensions import ZONE
                self.date.setDate(QDate(datetime.fromisoformat(inputs['windows'][0][0]).astimezone(ZONE).date()))
                self.windows.setPlainText('\n'.join(datetime.fromisoformat(s).astimezone(ZONE).strftime('%H:%M') + '-' + datetime.fromisoformat(e).astimezone(ZONE).strftime('%H:%M') for s, e in inputs['windows']))
                self.focus.setValue(inputs['focus_minutes'])
                self.pause.setValue(inputs['break_minutes'])
                self.calendar_path.setText((saved.get('calendar') or {}).get('path', ''))
                self.include_cards.setChecked(any(t.get('card_ids') for t in inputs.get('tasks', [])))
            self.plan_text.setPlainText('Zuletzt übernommener Plan:\n' + self.format_plan(saved))
            self.fill_progress_blocks()
        except (OSError, ValueError, TypeError, KeyError):
            pass
        for signal in (self.windows.textChanged, self.date.dateChanged, self.focus.valueChanged, self.pause.valueChanged, self.table.itemChanged,
                       self.calendar_path.textChanged, self.include_cards.toggled, self.adjustment.textChanged):
            signal.connect(self.invalidate_plan)

    def choose_calendar(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Kalender lesen', '', 'Kalender (*.ics)')
        if path:
            self.calendar_path.setText(path)

    def fill_progress_blocks(self):
        self.progress_blocks.clear()
        for block in (self.previous or {}).get('blocks', []):
            if block['kind'] == 'task' and block_id(block) not in (self.previous or {}).get('completed_blocks', []):
                self.progress_blocks.addItem(datetime.fromisoformat(block['start']).strftime('%H:%M') + ' · ' + block['title'], block_id(block))

    def complete_block(self):
        identifier = self.progress_blocks.currentData()
        if not identifier or not self.previous:
            return
        try:
            with FileLease(str(DATA_DIR / 'day-plan.json') + '.lock', label='Der Tagesplan'):
                latest = read_json(DATA_DIR / 'day-plan.json', limit=2 * 1024 * 1024)
                if latest['fingerprint'] != self.previous['fingerprint']:
                    raise ValueError('Plan änderte sich. Bitte das Fenster neu öffnen.')
                latest['completed_blocks'] = [*latest.get('completed_blocks', []), identifier]
                latest['fingerprint'] = fingerprint_plan(latest)
                write_json(DATA_DIR / 'day-plan.json', latest)
                self.previous = latest
            self.invalidate_plan()
            self.fill_progress_blocks()
            self.status.setText('Arbeitsblock abgeschlossen. Der Aufgabenstatus wurde nicht verändert.')
        except (OSError, ValueError, KeyError) as error:
            self.status.setText(str(error))

    def open_study_block(self):
        identifiers = self.study_blocks.currentData()
        if identifiers:
            from desktop.flashcards_dialog import FlashcardsDialog
            FlashcardsDialog(self, card_ids=identifiers).exec()
            self.invalidate_plan()

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

    def current_plan(self):
        tasks, windows = self.planning_input()
        day = self.date.date().toPyDate()
        if self.include_cards.isChecked():
            from desktop.core.flashcards import FlashcardStore
            tasks += study_tasks(FlashcardStore().all(), day)
        calendar = calendar_busy(self.calendar_path.text(), day) if self.calendar_path.text().strip() else None
        change = parse_adjustment(self.adjustment.text()) if self.adjustment.text().strip() else None
        previous = self.previous if change else None
        if change:
            if not previous:
                raise ValueError('Zuerst einen Tagesplan übernehmen; danach dessen offene Blöcke anpassen.')
            first = (previous.get('request') or previous['inputs'])['windows'][0][0]
            from desktop.core.planning_extensions import ZONE
            if datetime.fromisoformat(first).astimezone(ZONE).date() != day:
                raise ValueError('Anpassungen gelten für den Tag des gespeicherten Plans.')
            if change['kind'] == 'duration':
                matches = [t for t in tasks if t['title'].casefold() == change['title'].casefold()] if change['title'] else [t for t in tasks if t['id'] == self.editing_id]
                if len(matches) != 1:
                    raise ValueError('Aufgabe eindeutig benennen oder unter Aufgaben auswählen.')
                consumed = sum(b['minutes'] for b in previous['blocks'] if b.get('task_id') == matches[0]['id'] and
                    (block_id(b) in previous.get('completed_blocks', []) or datetime.fromisoformat(b['start']) < self.preview_now < datetime.fromisoformat(b['end'])))
                total = previous.get('duration_overrides', {}).get(matches[0]['id'], matches[0]['minutes'])
                change.update(task_id=matches[0]['id'], minutes=change['minutes'] or max(0, total - consumed) + 15)
        return extended_plan(tasks, windows, busy=(calendar or {}).get('busy', []), calendar=calendar,
            previous=previous, change=change, now=self.preview_now, break_minutes=self.pause.value(), focus_minutes=self.focus.value())

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
            self.preview_now = datetime.now(UTC)
            self.plan = self.current_plan()
            self.plan_text.setPlainText(self.format_plan(self.plan))
            self.study_blocks.clear()
            for task in self.plan['request']['tasks']:
                if task.get('card_ids'):
                    self.study_blocks.addItem(task['title'] + f" · {len(task['card_ids'])} Karten", task['card_ids'])
            self.accept_plan.setEnabled(True)
            self.status.setText('Neue Vorschau. Erst Geprüften Tagesplan übernehmen speichert die Änderungen.')
        except (OSError, ValueError, KeyError, ImportError) as error:
            self.invalidate_plan()
            self.plan_text.setPlainText('Plan nicht erstellt: ' + str(error))

    @staticmethod
    def format_plan(plan):
        rows = ['Vorschau · keine Aufgabe oder Erinnerung wird gestartet.']
        if plan.get('adjustment'):
            rows.append('Anpassung: abgeschlossene und aktuell laufende Blöcke bleiben erhalten. Verpasste Arbeit wird neu geplant.')
            for item in plan.get('changes', []):
                before = ', '.join(datetime.fromisoformat(b['start']).strftime('%H:%M') for b in item['before']) or 'nicht eingeplant'
                after = ', '.join(datetime.fromisoformat(b['start']).strftime('%H:%M') for b in item['after']) or 'nicht eingeplant'
                rows.append(item['title'] + ': vorher ' + before + ' → jetzt ' + after)
        if plan.get('calendar'):
            rows.append('Kalender gelesen: ' + plan['calendar']['path'])
            from desktop.core.planning_extensions import ZONE
            rows += ['Belegt: ' + event['title'] + ' · ' + datetime.fromisoformat(event['start']).astimezone(ZONE).strftime('%H:%M') + '–' +
                datetime.fromisoformat(event['end']).astimezone(ZONE).strftime('%H:%M') for event in plan['calendar']['busy']]
        for block in plan['blocks']:
            rows.append(datetime.fromisoformat(block['start']).strftime('%d.%m. %H:%M') + '–' + datetime.fromisoformat(block['end']).strftime('%H:%M') + ' · ' + block['title'])
        rows += ['', 'Noch nicht eingeplant:'] + [item['title'] + ' · ' + str(item['minutes']) + ' Minuten · ' + item['reason'] for item in plan['unplanned']]
        rows += plan['warnings']
        return '\n'.join(rows)

    def save_plan(self):
        if not self.plan:
            return
        try:
            current = self.current_plan()
            if current['fingerprint'] != self.plan['fingerprint']:
                raise ValueError('Eingaben änderten sich. Bitte erneut einen Plan vorschlagen.')
            with FileLease(str(DATA_DIR / 'day-plan.json') + '.lock', label='Der Tagesplan'):
                try:
                    latest = read_json(DATA_DIR / 'day-plan.json', limit=2 * 1024 * 1024)
                except FileNotFoundError:
                    latest = None
                if (latest or {}).get('fingerprint') != (self.previous or {}).get('fingerprint'):
                    raise ValueError('Gespeicherter Plan änderte sich. Fenster neu öffnen und erneut prüfen.')
                write_json(DATA_DIR / 'day-plan.json', self.plan | {'accepted_at': datetime.now().astimezone().isoformat()})
            self.previous = self.plan
            self.fill_progress_blocks()
            self.adjustment.clear()
            self.status.setText('Geprüfter Tagesplan lokal übernommen. Es wird keine Aufgabe automatisch ausgeführt.')
        except (ValueError, OSError, ImportError) as error:
            self.status.setText(str(error))
