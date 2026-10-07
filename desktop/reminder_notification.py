"""Actionable reminder window, also usable by an independent scheduled worker."""
import threading
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QPushButton, QPlainTextEdit


class ReminderNotification(QDialog):
    _done = pyqtSignal(str, object, str)

    def __init__(self, record, snooze, *, client=None, parent=None):
        super().__init__(parent)
        self.record, self.snooze, self.client = record, snooze, client
        self.setWindowTitle('MICA · Erinnerung' if record.get('task_id') or record.get('kind') == 'reminder' else 'MICA · Timer')
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(440, 220)
        layout = QVBoxLayout(self)
        label = QLabel(record.get('label', 'Dein MICA-Timer ist abgelaufen.'))
        label.setWordWrap(True)
        layout.addWidget(label)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.hide()
        layout.addWidget(self.details)
        self.complete = QPushButton('Erledigt')
        self.complete.clicked.connect(self.finish_reminder)
        layout.addWidget(self.complete)
        self.later = QPushButton('10 Minuten später')
        self.later.clicked.connect(lambda: self.work('snooze', lambda: self.snooze(self.record, 600)))
        layout.addWidget(self.later)
        self.open_task = QPushButton('Aufgabe öffnen' if record.get('task_id') else 'Erinnerung öffnen')
        self.open_task.clicked.connect(self.show_task)
        layout.addWidget(self.open_task)
        self._done.connect(self.finished_work)

    def work(self, action, call):
        for button in (self.complete, self.later, self.open_task):
            button.setEnabled(False)
        self.status.setText('Wird verarbeitet …')
        def worker():
            try:
                result, error = call(), ''
            except Exception as exc:
                result, error = None, str(exc)
            self._done.emit(action, result, error)
        threading.Thread(target=worker, name='mica-reminder-action', daemon=True).start()

    def finish_reminder(self):
        if self.record.get('task_id') and self.client:
            self.work('complete', lambda: self.client.update_task(self.record['task_id'], 'completed'))
        else:
            self.accept()

    def show_task(self):
        if self.record.get('task_id') and self.client:
            self.work('open', lambda: self.client._request('GET', '/v1/task-items/' + self.record['task_id']))
        else:
            self.details.setPlainText(self.record.get('label', 'Timer abgelaufen.'))
            self.details.show()

    def finished_work(self, action, result, error):
        for button in (self.complete, self.later, self.open_task):
            button.setEnabled(True)
        if error:
            self.status.setText('Aktion nicht abgeschlossen: ' + error)
        elif action == 'open':
            self.details.setPlainText(result['title'] + '\nStatus: ' + result['status'] + '\nTermin: ' + (result.get('due_at') or 'keiner') + '\n\n' + result.get('description', ''))
            self.details.show()
            self.status.setText('Aktuelle Aufgabe aus MICA geöffnet.')
        else:
            self.accept()


def worker_client():
    import os
    from pathlib import Path
    from desktop.core.settings_store import _read_env
    for key, value in _read_env(Path(__file__).resolve().parents[1] / '.env').items():
        if key in {'MICA_CORE_URL', 'MICA_CORE_CA_FILE'}:
            os.environ[key] = value
    from desktop.core.local_core_client import LocalCoreClient
    return LocalCoreClient()


def show_standalone(record, *, path=None):
    _app = QApplication.instance() or QApplication([])  # Keep Qt alive through exec().
    client = worker_client() if record.get('task_id') else None
    if record.get('task_id'):
        try:
            task = client._request('GET', '/v1/task-items/' + record['task_id'])
            if task.get('status') in {'completed', 'cancelled'}:
                return False
        except Exception:
            pass  # Still show the reminder; action failures remain visible.
    def snooze(item, seconds):
        if path:
            from desktop.core.native_commands import LocalTimers
            from desktop.core.timer_delivery import WindowsTimerDelivery
            timers = LocalTimers(lambda _: None, path=path, delivery=WindowsTimerDelivery(path))
            try:
                answer = timers.start(seconds, task_id=item.get('task_id'), label=item.get('label', 'Timer abgelaufen.'))
                if 'gestartet' not in answer:
                    raise ValueError(answer)
            finally:
                timers.shutdown()
        else:
            from desktop.actions.reminder import snooze_reminder
            snooze_reminder(item['label'], seconds)
    window = ReminderNotification(record, snooze, client=client)
    try:
        import winsound
        winsound.MessageBeep()
    except (ImportError, RuntimeError):
        pass
    window.exec()
    return True
