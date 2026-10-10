"""Disposable real desktop dialogs and files for the five productivity extensions."""
from datetime import datetime, timedelta, UTC
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    if os.name != 'nt':
        raise RuntimeError('Diese Prüfung benötigt Windows.')
    from PyQt6.QtCore import QDate
    from PyQt6.QtWidgets import QApplication, QWidget, QLineEdit
    from desktop.core.local_state import write_json
    from desktop.core.offline_tasks import OfflineTasks
    from desktop.core.task_criteria import TaskCriteriaStore
    from desktop.core.workspace import ProjectWorkspaceStore
    from desktop.core.planning_extensions import ZONE
    from desktop.local_main import LocalMica
    import desktop.task_planning_dialog as planning
    import desktop.core.flashcards as flashcards
    from desktop.task_criteria_dialog import TaskCriteriaDialog
    from desktop.workspace_dialog import WorkspaceDialog
    app = QApplication.instance() or QApplication([])
    output = ROOT / 'artifacts' / 'planning-extensions'
    output.mkdir(parents=True, exist_ok=True)
    def wait(dialog):
        stop = time.monotonic() + 10
        while dialog.busy and time.monotonic() < stop:
            app.processEvents()
            time.sleep(.01)
        assert not dialog.busy
    with tempfile.TemporaryDirectory(prefix='mica-planning-extensions-') as folder:
        root = Path(folder)
        planning.DATA_DIR = root
        task = {'id': 'a' * 32, 'title': 'Bericht schreiben', 'description': '', 'status': 'open', 'priority': 'normal', 'due_at': None}
        tasks = OfflineTasks(root / 'tasks.json')
        write_json(tasks.path, {'version': 1, 'tasks': [task], 'metadata': {'a' * 32: {'minutes': 60}}, 'pending': [], 'fetched_at': None})
        cards = flashcards.FlashcardStore(root / 'cards.json')
        now = datetime.now(ZONE)
        day = (now + timedelta(days=1)).date()
        cards.add([{'question': 'Was ist eine Zelle?', 'answer': 'Eine Zelle ist die kleinste lebende Einheit.', 'source': {
            'document_id': 'b' * 32, 'title': 'Biologie', 'start': 0, 'end': len('Eine Zelle ist die kleinste lebende Einheit.'), 'line': 1,
            'quote': 'Eine Zelle ist die kleinste lebende Einheit.'}}], now=now)
        # Keep every operation in the disposable local store, including the real UI callbacks.
        original_cards = flashcards.FlashcardStore
        flashcards.FlashcardStore = lambda: cards
        core = LocalMica.__new__(LocalMica)
        core._request_lock = threading.RLock()
        core._restoring = False
        core._offline_start = True
        core.ui = SimpleNamespace(remember_conversations=True)
        dialog = planning.TaskPlanningDialog(None, core._task_planning_operation, store=tasks, page='plan')
        dialog.date.setDate(QDate(day))
        calendar = root / 'calendar.ics'
        calendar.write_text('BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:test-calendar\nDTSTART;TZID=Europe/Vienna:' +
            day.strftime('%Y%m%d') + 'T100000\nDTEND;TZID=Europe/Vienna:' + day.strftime('%Y%m%d') +
            'T110000\nSUMMARY:Belegter Termin\nEND:VEVENT\nEND:VCALENDAR\n', encoding='utf-8')
        original_calendar = calendar.read_bytes()
        dialog.calendar_path.setText(str(calendar))
        dialog.include_cards.setChecked(True)
        dialog.preview_plan()
        assert dialog.plan and dialog.plan['calendar']['busy'] and any(t.get('card_ids') for t in dialog.plan['request']['tasks'])
        assert not (root / 'day-plan.json').exists()
        dialog.save_plan()
        baseline = (root / 'day-plan.json').read_bytes()
        dialog.adjustment.setText('Ich habe erst ab 15 Uhr Zeit')
        dialog.preview_plan()
        assert dialog.plan and dialog.plan['adjustment'] and (root / 'day-plan.json').read_bytes() == baseline
        assert all(datetime.fromisoformat(b['start']).astimezone(ZONE).hour >= 15 for b in dialog.plan['blocks'])
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(output / 'planning.png'))
        dialog.save_plan()
        assert calendar.read_bytes() == original_calendar
        criteria = TaskCriteriaStore(root / 'criteria.json')
        file = root / 'result.md'
        file.write_text('Vorbereitung', encoding='utf-8')
        check = TaskCriteriaDialog(None, 'a' * 32, core._task_planning_operation, tasks, criteria=criteria)
        check.path.setText(str(file))
        check.text.setText('Bericht gespeichert')
        check.changed.setChecked(True)
        check.run('criteria_set')
        wait(check)
        file.write_text('Bericht gespeichert', encoding='utf-8')
        check.run('criteria_check')
        wait(check)
        assert not tasks.read()['pending'] and criteria.read()['a' * 32]['last_result']['status'] == 'confirmed'
        check.show()
        app.processEvents()
        check.grab().save(str(output / 'criteria.png'))
        check.run('criteria_complete')
        wait(check)
        assert tasks.read()['pending'][0]['desired']['status'] == 'completed'
        project_store = ProjectWorkspaceStore(root / 'projects.json', legacy_path=root / 'legacy.json')
        doc = {'id': 'b' * 32, 'title': 'Projekt', 'source': 'text', 'body': 'Lokaler Projektinhalt'}
        saved = project_store.save([doc], None, 'Bericht prüfen', name='test', last_step='Vorbereitung abgeschlossen')
        class Parent(QWidget):
            def _open_attachments(self):
                pass
        parent = Parent()
        parent._input = QLineEdit()
        selected = []
        parent._attachment_overlay = SimpleNamespace(replace_documents=lambda docs: selected.extend(docs))
        workspace = WorkspaceDialog(parent, core._workspace_operation, [], store=project_store, project='test', prefer_load=True)
        workspace.run('load')
        wait(workspace)
        assert selected == [doc] and parent._input.text() == saved['next_step'] and core._local_workspace['last_step'] == saved['last_step']
        workspace.show()
        app.processEvents()
        workspace.grab().save(str(output / 'project.png'))
        for window in (workspace, check, dialog, parent):
            window.close()
        flashcards.FlashcardStore = original_cards
        evidence = {'checked_at': datetime.now(UTC).isoformat(), 'canonical_python': sys.executable,
            'calendar_read_only': True, 'adjustment_preview_before_save': True, 'real_dialogs_rendered': True,
            'study_cards_in_plan': True, 'file_criterion_real_content_verified': True,
            'completion_only_after_explicit_click': True, 'project_documents_next_and_last_loaded_offline': True,
            'user_data_modified': False}
        (output / 'runtime.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(evidence))


if __name__ == '__main__':
    main()
