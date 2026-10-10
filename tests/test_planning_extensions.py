"""Requirement checks for adaptive plans, project resume, calendars, criteria and study."""
from datetime import datetime, date, timedelta, UTC
import json
import time
from unittest.mock import Mock
import pytest
from desktop.core.day_planner import build_day_plan
from desktop.core.planning_extensions import block_id, calendar_busy, subtract_busy, extended_plan, parse_adjustment, study_tasks
from desktop.core.task_criteria import TaskCriteriaStore
from desktop.core.offline_tasks import OfflineTasks
from desktop.core.local_state import write_json
from desktop.core.flashcards import FlashcardStore
from mica_shared.quick_commands import parse_quick_command

START = datetime.fromisoformat('2026-10-08T09:00:00+02:00')
DAY = START.date()


def task(identifier='a', **fields):
    return {'id': identifier * 32, 'title': 'Bericht', 'description': '', 'status': 'open',
        'priority': 'normal', 'minutes': 30, 'due_at': None, 'depends_on': [], **fields}


def ics(tmp_path, events):
    path = tmp_path / 'calendar.ics'
    path.write_text('BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//MICA//Test//DE\n' + events + '\nEND:VCALENDAR\n', encoding='utf-8')
    return path


def event(identifier='meeting', **values):
    fields = {'UID': identifier, 'DTSTAMP': '20261001T000000Z', 'DTSTART;TZID=Europe/Vienna': '20261008T100000',
              'DTEND;TZID=Europe/Vienna': '20261008T110000', **values}
    return 'BEGIN:VEVENT\n' + '\n'.join(key + ':' + value for key, value in fields.items()) + '\nEND:VEVENT'


def test_calendar_subtracts_recurring_overlap_exceptions_and_transparent_events(tmp_path):
    path = ics(tmp_path, event(RRULE='FREQ=DAILY;COUNT=3', **{'DTSTART;TZID=Europe/Vienna': '20261007T100000', 'DTEND;TZID=Europe/Vienna': '20261007T110000'}) + '\n' +
        event('overlap', **{'DTSTART;TZID=Europe/Vienna': '20261008T103000', 'DTEND;TZID=Europe/Vienna': '20261008T113000'}) + '\n' +
        event('free', TRANSP='TRANSPARENT') + '\n' + event('cancelled', STATUS='CANCELLED'))
    before = path.read_bytes()
    snapshot = calendar_busy(path, DAY)
    assert len(snapshot['busy']) == 2
    available = subtract_busy([(START, START + timedelta(hours=3))], snapshot['busy'])
    assert [(s.astimezone(START.tzinfo).hour, e.astimezone(START.tzinfo).strftime('%H:%M')) for s, e in available] == [(9, '10:00'), (11, '12:00')]
    assert available[1][0].astimezone(START.tzinfo).minute == 30 and path.read_bytes() == before


def test_recurrence_exdate_and_changed_instance(tmp_path):
    path = ics(tmp_path, event(RRULE='FREQ=DAILY;COUNT=3', EXDATE='20261008T080000Z') )
    assert not calendar_busy(path, DAY)['busy']
    path = ics(tmp_path, event(RRULE='FREQ=DAILY;COUNT=2') + '\n' + event(**{
        'RECURRENCE-ID;TZID=Europe/Vienna': '20261008T100000', 'DTSTART;TZID=Europe/Vienna': '20261008T140000', 'DTEND;TZID=Europe/Vienna': '20261008T150000'}))
    busy = calendar_busy(path, DAY)['busy']
    assert len(busy) == 1 and datetime.fromisoformat(busy[0]['start']).astimezone(START.tzinfo).hour == 14


def test_all_day_event_blocks_day_and_zero_duration_does_not(tmp_path):
    path = ics(tmp_path, 'BEGIN:VEVENT\nUID:all-day\nDTSTART;VALUE=DATE:20261008\nDTEND;VALUE=DATE:20261009\nEND:VEVENT')
    snapshot = calendar_busy(path, DAY)
    assert not subtract_busy([(START, START + timedelta(hours=3))], snapshot['busy'])
    plan = extended_plan([task()], [(START, START + timedelta(hours=3))], busy=snapshot['busy'], calendar=snapshot)
    assert not plan['blocks'] and plan['unplanned'][0]['minutes'] == 30


@pytest.mark.parametrize('body', ['not a calendar', event(RRULE='FREQ=SECONDLY'), 'BEGIN:VEVENT\nUID:bad\nEND:VEVENT'])
def test_invalid_calendar_is_not_silently_treated_as_free(tmp_path, body):
    with pytest.raises(ValueError):
        calendar_busy(ics(tmp_path, body), DAY)


def test_calendar_floating_times_use_vienna_and_dst(tmp_path):
    path = ics(tmp_path, 'BEGIN:VEVENT\nUID:floating\nDTSTART:20261026T100000\nDTEND:20261026T110000\nEND:VEVENT')
    busy = calendar_busy(path, date(2026, 10, 26))['busy']
    assert datetime.fromisoformat(busy[0]['start']).hour == 9


def test_adaptation_preserves_started_blocks_and_moves_only_open_work():
    tasks = [task(minutes=60), task('b', title='Abgabe', minutes=30, depends_on=['a' * 32])]
    windows = [(START, START + timedelta(hours=8))]
    previous = build_day_plan(tasks, windows, focus_minutes=30, break_minutes=10)
    now = START + timedelta(minutes=20)
    plan = extended_plan(tasks, windows, previous=previous, now=now,
        change={'kind': 'available_from', 'time': '15:00'}, focus_minutes=30, break_minutes=10)
    assert plan['blocks'][0] == previous['blocks'][0]
    future = [b for b in plan['blocks'][1:] if b['kind'] == 'task']
    assert future[0]['task_id'] == 'a' * 32 and future[1]['task_id'] == 'b' * 32
    assert all(datetime.fromisoformat(b['start']).hour >= 15 for b in future)
    assert sum(b['minutes'] for b in plan['blocks'] if b.get('task_id') == 'a' * 32) == 60
    assert plan['changes'] and plan['previous_fingerprint'] == previous['fingerprint']


def test_duration_change_survives_another_replan_and_reports_overflow():
    tasks = [task(minutes=60)]
    windows = [(START, START + timedelta(hours=2))]
    previous = build_day_plan(tasks, windows, focus_minutes=30, break_minutes=10)
    changed = extended_plan(tasks, windows, previous=previous, now=START + timedelta(minutes=20),
        change={'kind': 'duration', 'task_id': 'a' * 32, 'minutes': 90}, focus_minutes=30, break_minutes=10)
    assert changed['duration_overrides']['a' * 32] == 120
    assert sum(b['minutes'] for b in changed['blocks'] if b['kind'] == 'task') + changed['unplanned'][0]['minutes'] == 120
    again = extended_plan(tasks, windows, previous=changed, now=START + timedelta(minutes=20),
        change={'kind': 'available_from', 'time': '10:00'}, focus_minutes=30, break_minutes=10)
    assert sum(b['minutes'] for b in again['blocks'] if b['kind'] == 'task') + again['unplanned'][0]['minutes'] == 120


def test_replan_keeps_short_tail_exact_and_completed_dependencies():
    tasks = [task(minutes=30), task('b', title='Nacharbeit', minutes=30, depends_on=['a' * 32])]
    windows = [(START, START + timedelta(hours=3))]
    previous = build_day_plan(tasks, windows, focus_minutes=28, break_minutes=0)
    plan = extended_plan(tasks, windows, previous=previous, now=START + timedelta(minutes=10),
        change={'kind': 'available_from', 'time': '10:00'}, focus_minutes=28, break_minutes=0)
    assert sum(b['minutes'] for b in plan['blocks'] if b.get('task_id') == 'a' * 32) == 30
    previous['completed_blocks'] = [block_id(b) for b in previous['blocks'] if b.get('task_id') == 'a' * 32]
    later = extended_plan(tasks, windows, previous=previous, now=START + timedelta(minutes=31),
        change={'kind': 'available_from', 'time': '10:00'}, focus_minutes=28, break_minutes=0)
    assert not later['unplanned']


def test_missed_blocks_remain_open_and_are_rescheduled():
    windows = [(START, START + timedelta(hours=8))]
    tasks = [task(minutes=60)]
    previous = build_day_plan(tasks, windows, focus_minutes=30, break_minutes=10)
    plan = extended_plan(tasks, windows, previous=previous, now=START + timedelta(hours=3),
        change={'kind': 'available_from', 'time': '15:00'}, focus_minutes=30, break_minutes=10)
    assert not plan['fixed_blocks'] and sum(b['minutes'] for b in plan['blocks'] if b['kind'] == 'task') == 60
    assert all(datetime.fromisoformat(b['start']).hour >= 15 for b in plan['blocks'])


def test_current_pause_is_preserved_without_overlapping_new_work():
    windows = [(START, START + timedelta(hours=3))]
    tasks = [task(minutes=60)]
    previous = build_day_plan(tasks, windows, focus_minutes=30, break_minutes=10)
    previous['completed_blocks'] = [block_id(previous['blocks'][0])]
    plan = extended_plan(tasks, windows, previous=previous, now=START + timedelta(minutes=35),
        change={'kind': 'available_from', 'time': '09:00'}, focus_minutes=30, break_minutes=10)
    assert plan['blocks'][:2] == previous['blocks'][:2]
    assert datetime.fromisoformat(plan['blocks'][2]['start']) >= datetime.fromisoformat(previous['blocks'][1]['end'])


def test_criterion_rejects_oversized_write_without_corrupting_previous_file(tmp_path):
    criteria = TaskCriteriaStore(tmp_path / 'criteria.json')
    criteria.set('a' * 32, str(tmp_path / 'file.md'), 'OK')
    before = criteria.path.read_bytes()
    entry = criteria.read()['a' * 32]
    with pytest.raises(ValueError, match='zu groß'):
        criteria.write({str(i): {**entry, 'path': '漢' * 4096, 'expected_text': '漢' * 2000} for i in range(500)})
    assert criteria.path.read_bytes() == before


@pytest.mark.parametrize('text,kind', [('Ich habe erst ab 15 Uhr Zeit', 'available_from'),
    ('Die Aufgabe dauert länger', 'duration'), ('Aufgabe Bericht dauert 60 Minuten', 'duration')])
def test_natural_adjustments_route_to_preview(text, kind):
    parsed = parse_quick_command(text)
    assert parsed == {'kind': 'task_planning', 'page': 'adjust', 'title': text}
    assert parse_adjustment(text)['kind'] == kind


def card(identifier='c', **fields):
    return {'id': identifier * 32, 'question': 'Was?', 'answer': 'Antwort', 'source': {'document_id': 'd' * 32,
        'title': 'Biologie', 'quote': 'Antwort', 'start': 0, 'end': 7, 'line': 1},
        'due_at': START.isoformat(), 'interval': 1, 'reviews': 1, **fields}


def test_study_blocks_prioritize_difficulty_and_remain_local(tmp_path):
    cards = [card('a'), card('b', due_at=(START + timedelta(days=4)).isoformat(), last_rating='hard'),
        card('c', due_at=(START + timedelta(days=4)).isoformat(), last_rating='good')]
    tasks = study_tasks(cards, DAY)
    assert len(tasks) == 1 and tasks[0]['card_ids'] == ['b' * 32, 'a' * 32] and tasks[0]['priority'] == 'high'
    plan = extended_plan(tasks, [(START, START + timedelta(hours=1))])
    assert plan['blocks'][0]['task_id'] == tasks[0]['id']
    store = FlashcardStore(tmp_path / 'cards.json')
    write_json(store.path, {'version': 1, 'cards': cards})
    store.rate('a' * 32, 'hard', now=START)
    assert FlashcardStore(store.path).all()[0]['last_rating'] == 'hard'
    assert study_tasks(cards, DAY) == tasks


def test_saved_criterion_rechecks_real_file_before_staging_completion(tmp_path):
    path = tmp_path / 'result.md'
    path.write_text('Alt', encoding='utf-8')
    tasks = OfflineTasks(tmp_path / 'tasks.json')
    write_json(tasks.path, {'version': 1, 'tasks': [task()], 'pending': [], 'metadata': {}, 'fetched_at': None})
    criteria = TaskCriteriaStore(tmp_path / 'criteria.json')
    criteria.set('a' * 32, str(path), 'Gespeichert', True)
    assert criteria.check('a' * 32)['status'] == 'not_confirmed' and not tasks.read()['pending']
    path.write_text('Gespeichert', encoding='utf-8')
    assert criteria.check('a' * 32)['status'] == 'confirmed' and not tasks.read()['pending']
    path.write_text('Falsche neue Fassung', encoding='utf-8')
    with pytest.raises(ValueError):
        criteria.complete('a' * 32, tasks)
    assert not tasks.read()['pending']
    path.write_text('Gespeichert', encoding='utf-8')
    criteria.complete('a' * 32, tasks)
    assert tasks.read()['pending'][0]['desired']['status'] == 'completed'
    assert TaskCriteriaStore(criteria.path).read()['a' * 32]['last_result']['evidence']['sha256']


def test_check_does_not_overwrite_a_concurrent_task_edit(tmp_path, monkeypatch):
    tasks = OfflineTasks(tmp_path / 'tasks.json')
    write_json(tasks.path, {'version': 1, 'tasks': [task()], 'pending': [], 'metadata': {}, 'fetched_at': None})
    criteria = TaskCriteriaStore(tmp_path / 'criteria.json')
    path = tmp_path / 'result.md'
    path.write_text('OK', encoding='utf-8')
    criteria.set('a' * 32, str(path), 'OK')
    original = criteria.check
    def edited(identifier):
        result = original(identifier)
        tasks.stage(task(title='Währenddessen geändert'))
        return result
    monkeypatch.setattr(criteria, 'check', edited)
    with pytest.raises(ValueError, match='änderte'):
        criteria.complete('a' * 32, tasks)
    assert tasks.view()[0]['title'] == 'Währenddessen geändert' and tasks.view()[0]['status'] == 'open'


@pytest.fixture
def qt(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def until(qt, condition):
    stop = time.monotonic() + 5
    while not condition() and time.monotonic() < stop:
        qt.processEvents()
        time.sleep(.01)
    assert condition()


def test_dialog_calendar_snapshot_change_blocks_save_and_replan_needs_acceptance(qt, tmp_path, monkeypatch):
    import desktop.task_planning_dialog as module
    monkeypatch.setattr(module, 'DATA_DIR', tmp_path)
    store = OfflineTasks(tmp_path / 'tasks.json')
    store.stage(task(), minutes=30)
    dialog = module.TaskPlanningDialog(None, Mock(), store=store, page='plan')
    from PyQt6.QtCore import QDate
    dialog.date.setDate(QDate(DAY))
    path = ics(tmp_path, event())
    dialog.calendar_path.setText(str(path))
    dialog.preview_plan()
    assert dialog.plan and dialog.accept_plan.isEnabled() and not (tmp_path / 'day-plan.json').exists()
    path.write_text(path.read_text(encoding='utf-8').replace('100000', '120000').replace('110000', '130000'), encoding='utf-8')
    dialog.save_plan()
    assert not (tmp_path / 'day-plan.json').exists() and 'erneut' in dialog.status.text()
    dialog.preview_plan()
    dialog.save_plan()
    saved = (tmp_path / 'day-plan.json').read_bytes()
    dialog.adjustment.setText('Ich habe erst ab 15 Uhr Zeit')
    dialog.preview_plan()
    assert dialog.plan and dialog.plan['adjustment'] and (tmp_path / 'day-plan.json').read_bytes() == saved
    dialog.save_plan()
    assert json.loads((tmp_path / 'day-plan.json').read_text(encoding='utf-8'))['adjustment']
    dialog.close()


def test_project_resume_loads_documents_next_and_last_step_in_one_operation(qt, tmp_path, monkeypatch):
    import desktop.ui as ui
    import desktop.workspace_dialog as workspace
    from desktop.core.workspace import ProjectWorkspaceStore
    from PyQt6.QtWidgets import QWidget, QLineEdit
    store = ProjectWorkspaceStore(tmp_path / 'projects.json', legacy_path=tmp_path / 'legacy.json')
    doc = {'id': 'd' * 32, 'title': 'Notizen', 'body': 'Projektinhalt', 'source': 'text'}
    saved = store.save([doc], None, 'Konfiguration prüfen', name='alpha', last_step='Vorbereitung erledigt')
    class Parent(QWidget):
        _resume_project = ui.MainWindow._resume_project
        _open_workspace = ui.MainWindow._open_workspace
        def _open_attachments(self):
            pass
    parent = Parent()
    parent._log = Mock()
    parent.remember_conversations = True
    parent._attachment_overlay = Mock()
    parent._attachment_overlay.checkpoint_documents.return_value = []
    parent._input = QLineEdit()
    parent.on_workspace_operation = Mock(return_value=saved)
    monkeypatch.setattr(workspace, 'ProjectWorkspaceStore', lambda: store)
    monkeypatch.setattr('desktop.core.workspace.ProjectWorkspaceStore', lambda: store)
    parent._resume_project('')
    assert parent.on_workspace_operation.call_count == 1 and parent.on_workspace_operation.call_args.args[0] == 'load'
    parent._attachment_overlay.replace_documents.assert_called_once_with([doc])
    assert parent._input.text() == 'Konfiguration prüfen'
    assert 'Vorbereitung erledigt' in parent._log.append_log.call_args.args[0]
    assert parse_quick_command('Projekt alpha fortsetzen') == {'kind': 'workspace_continue', 'name': 'alpha'}
    parent.close()


def test_selected_study_block_reviews_only_its_cards_even_before_due(qt, tmp_path):
    from desktop.flashcards_dialog import FlashcardsDialog
    store = FlashcardStore(tmp_path / 'cards.json')
    write_json(store.path, {'version': 1, 'cards': [card('a', due_at=(datetime.now(UTC) + timedelta(days=3)).isoformat(), last_rating='hard'), card('b')]})
    dialog = FlashcardsDialog(store=store, card_ids=['a' * 32])
    assert dialog.current['id'] == 'a' * 32 and not dialog.answer.toPlainText()
    dialog.show_answer()
    dialog.rate('good')
    assert dialog.current is None and next(c for c in store.all() if c['id'] == 'b' * 32)['reviews'] == 1
    dialog.close()


def test_criteria_dialog_saves_checks_and_explicitly_completes_with_real_callback(qt, tmp_path):
    import threading
    from types import SimpleNamespace
    from desktop.local_main import LocalMica
    from desktop.task_criteria_dialog import TaskCriteriaDialog
    core = LocalMica.__new__(LocalMica)
    core._request_lock = threading.RLock()
    core._restoring = False
    core.ui = SimpleNamespace(remember_conversations=True)
    tasks = OfflineTasks(tmp_path / 'tasks.json')
    write_json(tasks.path, {'version': 1, 'tasks': [task()], 'pending': [], 'metadata': {}, 'fetched_at': None})
    criteria = TaskCriteriaStore(tmp_path / 'criteria.json')
    path = tmp_path / 'result.md'
    path.write_text('Alt', encoding='utf-8')
    dialog = TaskCriteriaDialog(None, 'a' * 32, core._task_planning_operation, tasks, criteria=criteria)
    dialog.path.setText(str(path))
    dialog.text.setText('Neu')
    dialog.changed.setChecked(True)
    dialog.run('criteria_set')
    until(qt, lambda: not dialog.busy)
    path.write_text('Neu', encoding='utf-8')
    dialog.run('criteria_check')
    until(qt, lambda: not dialog.busy)
    assert 'Bestätigt' in dialog.status.text() and not tasks.read()['pending']
    dialog.text.setText('Ungespeicherte Erwartung')
    dialog.run('criteria_complete')
    assert not dialog.busy and 'Zuerst' in dialog.status.text() and not tasks.read()['pending']
    dialog.text.setText('Neu')
    dialog.run('criteria_complete')
    until(qt, lambda: not dialog.busy)
    assert tasks.view()[0]['status'] == 'completed'
    dialog.close()
