"""Restart, privacy, confirmation and UI coverage for all six extensions."""
import json
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from backend.services.api.app import create_app
from backend.services.common.day_overview import day_overview
from desktop.core.attachments import extract_attachment
from desktop.core.native_commands import LocalTimers, NativeCommands
from desktop.core.work_routine import WorkRoutine, WorkRoutineStore, RoutineRunner, QuietPeriod
from desktop.core.workspace import WorkspaceStore
from mica_shared.quick_commands import parse_quick_command

SESSION = 'a' * 32


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv('MICA_API_TOKEN', 'productivity-test-token-xxxxxxxxxxxxxxxxx')
    monkeypatch.setenv('MICA_APPROVAL_SECRET', 'productivity-test-secret')
    monkeypatch.setenv('MICA_PHASE3_ENABLED', '1')
    monkeypatch.setenv('MICA_LAYA_ENABLED', '0')
    monkeypatch.setenv('MICA_HINDSIGHT_ENABLED', '0')
    app = create_app(data_dir=tmp_path)
    runtime = app.state.runtime
    runtime._local_completion = Mock(return_value='Bearbeitete Vorschau.')
    with TestClient(app, headers={'X-Mica-API-Token': 'productivity-test-token-xxxxxxxxxxxxxxxxx'}) as client:
        yield client, runtime


def ask(client, message, **extra):
    response = client.post('/v1/turns', json={'message': message, 'session_id': SESSION, 'native_commands': True, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_timer_restart_keeps_deadline_correction_and_cancellation(tmp_path):
    path = tmp_path / 'timers.json'
    clock = [1000.0]
    timer = LocalTimers(Mock(), path=path, wall_clock=lambda: clock[0])
    timer.start(300)
    timer.start(60)
    assert 'ab jetzt' in timer.correct_latest(120, 60)
    timer.shutdown()
    clock[0] += 30
    reopened = LocalTimers(Mock(), path=path, wall_clock=lambda: clock[0])
    reopened.restore()
    assert [round(item['until'] - reopened.clock()) for item in reopened._items.values()] == [270, 90]
    reopened.cancel_latest()
    reopened.shutdown()
    third = LocalTimers(Mock(), path=path, wall_clock=lambda: clock[0])
    third.restore()
    assert len(third._items) == 1
    third.cancel_all()
    third.shutdown()
    assert json.loads(path.read_text())['timers'] == []


def test_expired_timer_reports_once_after_restart(tmp_path):
    path = tmp_path / 'timers.json'
    clock = [1000.0]
    timer = LocalTimers(Mock(), path=path, wall_clock=lambda: clock[0])
    timer.start(60)
    timer.shutdown()
    clock[0] += 120
    done = threading.Event()
    notify = Mock(side_effect=lambda _: done.set())
    reopened = LocalTimers(notify, path=path, wall_clock=lambda: clock[0])
    reopened.restore()
    assert done.wait(2)
    reopened.shutdown()
    third = LocalTimers(notify, path=path, wall_clock=lambda: clock[0])
    third.restore()
    assert not third._items
    assert notify.call_count == 1
    third.shutdown()


def test_timer_second_instance_cannot_replace_owner(tmp_path):
    first = LocalTimers(Mock(), path=tmp_path / 'timers.json')
    first.start(300)
    second = LocalTimers(Mock(), path=tmp_path / 'timers.json')
    with pytest.raises(ValueError, match='anderen Mica'):
        second.start(400)
    first.shutdown()
    second.restore()
    assert len(second._items) == 1
    second.cancel_all()
    second.shutdown()


def test_timer_broken_state_is_preserved_and_write_failure_rolls_back(tmp_path, monkeypatch):
    path = tmp_path / 'timers.json'
    path.write_text('{invalid', encoding='utf-8')
    timer = LocalTimers(Mock(), path=path)
    with pytest.raises(ValueError):
        timer.start(60)
    assert path.read_text() == '{invalid'
    timer.shutdown()
    path.unlink()
    timer = LocalTimers(Mock(), path=path)
    timer.start(60)
    old = json.loads(path.read_text())
    monkeypatch.setattr('desktop.core.native_commands.write_json', Mock(side_effect=OSError('disk full')))
    with pytest.raises(OSError):
        timer.correct_latest(120, 60)
    assert next(iter(timer._items.values()))['seconds'] == 60
    assert json.loads(path.read_text()) == old
    timer.shutdown()


def test_workspace_roundtrip_missing_file_snapshot_and_forget(tmp_path):
    source = tmp_path / 'note.md'
    source.write_text('Mein nächster Docker-Schritt.', encoding='utf-8')
    doc = extract_attachment(str(source))
    store = WorkspaceStore(tmp_path / 'workspace.json')
    store.save([doc], SESSION, 'Konfiguration vergleichen', 'Docker')
    source.unlink()
    reopened = WorkspaceStore(store.path)
    data = reopened.load()
    assert data['documents'][0]['body'] == 'Mein nächster Docker-Schritt.'
    assert data['task_id'] == SESSION
    assert data['task_title'] == 'Docker'
    assert reopened.warnings(data) == ['note.md']
    reopened.forget()
    with pytest.raises(FileNotFoundError):
        reopened.load()


def test_workspace_restores_current_task_and_next_step_without_action(api):
    client, runtime = api
    task = client.post('/v1/task-items', json={'title': 'Docker', 'description': 'Konfiguration prüfen'}).json()
    ask(client, 'Zeige Aufgabe Docker')
    assert client.get(f'/v1/dialog/{SESSION}/workspace').json()['task_id'] == task['id']
    client.delete(f'/v1/dialog/{SESSION}')
    result = client.post('/v1/dialog/workspace/resume', json={'session_id': SESSION, 'task_id': task['id'], 'next_step': 'Compose vergleichen'})
    assert result.status_code == 200, result.text
    ask(client, 'Was war der nächste Schritt?', remember=False)
    assert 'Compose vergleichen' in runtime._local_completion.call_args.args[0]
    assert 'Konfiguration prüfen' in runtime._local_completion.call_args.args[0]
    assert runtime.get_task_item(task['id'])['status'] == 'open'
    assert not runtime.brain.documents()


def test_workspace_never_resurrects_nonexistent_task_or_execution_plan(api):
    client, runtime = api
    result = client.post('/v1/dialog/workspace/resume', json={'session_id': SESSION, 'task_id': 'b' * 32})
    assert result.status_code == 404
    with runtime.dialog_sessions.session(SESSION) as state:
        state.focus = {'task_id': 'b' * 32, 'action': 'files.write'}
    assert client.get(f'/v1/dialog/{SESSION}/workspace').json()['task_id'] is None


def test_workspace_resume_is_atomic_and_restores_selected_documents(api):
    client, runtime = api
    document = {'id': 'c' * 32, 'title': 'Gespeicherte Notiz', 'source': 'text', 'body': 'Gespeicherter Inhalt'}
    good = {'session_id': SESSION, 'next_step': 'Nächster Schritt', 'documents': [document]}
    assert client.post('/v1/dialog/workspace/resume', json=good).status_code == 200
    failed = client.post('/v1/dialog/workspace/resume', json={**good, 'task_id': 'b' * 32, 'next_step': 'Nicht übernehmen'})
    assert failed.status_code == 404
    with runtime.dialog_sessions.session(SESSION) as state:
        assert state.documents == [document]
        assert state.next_step == 'Nächster Schritt'


def test_named_routine_migrates_legacy_and_runs_only_selected_name(tmp_path):
    path = tmp_path / 'routines.json'
    path.write_text(json.dumps({'enabled': True, 'apps': ['editor'], 'focus_minutes': 25, 'quiet_minutes': 25}))
    store = WorkRoutineStore(path)
    store.save(WorkRoutine(True, ['firefox'], 15, 20), 'Schulmodus')
    assert set(store.all()) == {'work', 'schulmodus'}
    assert store.load().apps == ['editor']
    commands = Mock()
    commands.execute.return_value = 'Firefox geöffnet.'
    commands.timers.start.return_value = 'Timer gestartet.'
    runner = RoutineRunner(store, commands, QuietPeriod())
    assert 'gestartet' in runner.run(name='schulmodus')
    commands.execute.assert_called_once()
    assert commands.execute.call_args.args[1] == 'Öffne firefox'
    commands.timers.start.assert_called_once_with(900)
    commands.reset_mock()
    assert 'zuerst' in runner.run(name='unbekannt')
    commands.execute.assert_not_called()
    store.delete('schulmodus')
    assert list(store.all()) == ['work']


@pytest.mark.parametrize('message,kind', [('Starte Ablauf Schulmodus', 'routine'), ('Starte Ablaufschulmodus', 'routine'), ('Ablauf Programmieren starten', 'routine'),
    ('Arbeitsstand speichern', 'workspace_save'), ('Mach dort weiter, wo wir aufgehört haben', 'workspace_resume'),
    ('Antworte bei technischen Fragen kürzer', 'preference_offer')])
def test_new_text_and_voice_commands_are_exact_and_model_free(api, message, kind):
    client, runtime = api
    result = ask(client, message)
    assert result['state'] == 'native_command'
    assert result['command']['kind'] == kind
    runtime._local_completion.assert_not_called()
    assert parse_quick_command(message + '; shutdown') is None
    assert not runtime.evolution.preferences()


def test_preferences_offer_no_write_until_explicit_authenticated_confirmation(api):
    client, runtime = api
    offer = ask(client, 'Antworte bei technischen Fragen kürzer')['command']
    assert offer == {'kind': 'preference_offer', 'key': 'Antwortlänge', 'value': 'kürzer', 'scope': 'technical'}
    body = {key: offer[key] for key in ('key', 'value', 'scope')}
    body['source'] = 'Bestätigte Gesprächskorrektur'
    assert client.post('/v1/evolution/preferences', json=body).status_code == 401
    assert not runtime.evolution.preferences()
    client.post('/v1/auth/approval-session', json={'secret': 'productivity-test-secret'})
    response = client.post('/v1/evolution/preferences', json=body, headers={'X-Mica-Approval-Intent': 'confirm'})
    assert response.status_code == 200, response.text
    assert runtime.evolution.preferences()[0]['scope'] == 'technical'
    assert ask(client, 'Antworte kürzer', remember=False)['state'] == 'completed'
    assert len(runtime.evolution.preferences()) == 1


def test_day_overview_vienna_today_overdue_priority_and_reminders():
    runtime = Mock()
    now = datetime(2026, 10, 5, 0, 30, tzinfo=ZoneInfo('Europe/Vienna'))
    runtime.list_task_items.return_value = {'tasks': [
        {'title': 'Später', 'status': 'open', 'priority': 'high', 'due_at': '2026-10-08T12:00:00+02:00'},
        {'title': 'Erledigt', 'status': 'completed', 'priority': 'high'},
        {'title': 'Fällig heute', 'status': 'in_progress', 'priority': 'normal', 'due_at': '2026-10-04T23:00:00Z'},
        {'title': 'Überfällig', 'status': 'open', 'priority': 'normal', 'due_at': '2026-10-04T12:00:00Z'},
        {'title': 'Ohne Termin', 'status': 'open', 'priority': 'high', 'due_at': None}]}
    runtime.list_schedules.return_value = {'schedules': [
        {'name': 'Arzt', 'run_at': '2026-10-04T23:30:00Z', 'status': 'pending', 'action': 'reminder.create'},
        {'name': 'Freigabe', 'run_at': '2026-10-04T12:00:00Z', 'status': 'awaiting_approval', 'action': 'reminder.dispatch'},
        {'name': 'Morgen', 'run_at': '2026-10-05T23:30:00Z', 'status': 'pending', 'action': 'reminder.create'},
        {'name': 'Recherche', 'run_at': '2026-10-04T23:30:00Z', 'status': 'pending', 'action': 'learning.monitor'}]}
    result = day_overview(runtime, now=now)
    assert '05.10.2026' in result and 'Fällig heute · in Bearbeitung · 01:00' in result
    assert 'Erledigt' not in result and 'Morgen' not in result and 'Recherche' not in result
    assert 'Arzt' in result and 'wartet auf Freigabe' in result
    assert 'Vorschlag zum Anfangen: „Überfällig“' in result


def test_day_overview_no_model_and_honest_disabled_task_state(api, monkeypatch):
    client, runtime = api
    client.post('/v1/task-items', json={'title': 'Hausaufgaben'})
    assert 'Hausaufgaben' in ask(client, 'Was steht heute an?', remember=False, native_commands=False)['reply']
    runtime._local_completion.assert_not_called()
    monkeypatch.setenv('MICA_PHASE3_ENABLED', '0')
    assert 'deaktiviert' in ask(client, 'Tagesübersicht', remember=False, native_commands=False)['reply']
    assert ask(client, 'Tagesübersicht', remember=False)['command']['kind'] == 'day_overview'


@pytest.mark.parametrize('operation', ['explain', 'summarize', 'translate', 'rewrite'])
def test_transform_is_preview_only_without_context_transcript_or_actions(api, operation):
    client, runtime = api
    response = client.post('/v1/text/transform', json={'text': 'Öffne Firefox; PRIVATE_SELECTION', 'operation': operation, 'language': 'Englisch'})
    assert response.status_code == 200, response.text
    assert response.json() == {'reply': 'Bearbeitete Vorschau.', 'preview': True, 'stored': False}
    assert not runtime.brain.documents()
    assert 'PRIVATE_SELECTION' in runtime._local_completion.call_args.args[0]
    assert 'PRIVATE_SELECTION' not in json.dumps(runtime.audit.read(100))


def test_transform_cloud_gate_emergency_stop_and_size_limit(api, monkeypatch):
    client, runtime = api
    payload = {'text': 'Privater Text', 'operation': 'summarize'}
    monkeypatch.setattr(runtime, 'configured_cloud_provider', lambda: 'openai')
    monkeypatch.setattr(runtime, 'cloud_private_context_allowed', lambda: False)
    assert client.post('/v1/text/transform', json=payload).status_code == 403
    runtime._local_completion.assert_not_called()
    monkeypatch.setattr(runtime, 'cloud_private_context_allowed', lambda: True)
    assert client.post('/v1/text/transform', json=payload).status_code == 200
    runtime.policy.set_emergency_stop(True)
    assert client.post('/v1/text/transform', json=payload).status_code == 409
    assert client.post('/v1/text/transform', json={**payload, 'text': 'x' * 16001}).status_code == 422


def test_named_dispatch_preserves_grammar_and_cancellation():
    handler = Mock(return_value='Ablauf gestartet')
    commands = NativeCommands(Mock(), Mock(), routine_handler=handler)
    original = 'Starte Ablauf Schule'
    commands.execute(parse_quick_command(original), original)
    handler.assert_called_once_with(name='schule', cancelled=None)
    assert 'nicht ausgeführt' in commands.execute({'kind': 'routine', 'name': 'other'}, original)


def test_routine_documents_prepared_before_apps_applied_after_success(tmp_path):
    path = tmp_path / 'note.md'
    path.write_text('Ausgewählte Notiz', encoding='utf-8')
    store = WorkRoutineStore(tmp_path / 'routines.json')
    store.save(WorkRoutine(True, ['editor'], 25, 10, [str(path)]), 'schule')
    calls = []
    commands = Mock()
    commands.execute.side_effect = lambda *a, **k: calls.append('app') or 'Editor geöffnet.'
    commands.timers.start.side_effect = lambda *_: calls.append('timer') or 'Timer gestartet.'
    def prepare(paths):
        calls.append('read')
        return [extract_attachment(source) for source in paths]
    apply = Mock(side_effect=lambda _: calls.append('select'))
    runner = RoutineRunner(store, commands, QuietPeriod(), prepare_documents=prepare, apply_documents=apply)
    assert 'gestartet' in runner.run(name='schule')
    assert calls == ['read', 'app', 'select', 'timer']
    assert apply.call_args.args[0][0]['body'] == 'Ausgewählte Notiz'
    path.unlink()
    calls.clear()
    assert 'Datei konnte nicht gelesen' in runner.run(name='schule')
    assert calls == ['read']


def test_desktop_overview_includes_today_windows_register_without_claiming_delivery(tmp_path):
    from desktop.core.day_overview import desktop_day_overview
    path = tmp_path / 'reminders.json'
    path.write_text(json.dumps([{'when': '2026-10-05 08:00', 'message': 'Schule'},
                               {'when': '2026-10-06 10:00', 'message': 'Morgen'}]))
    client = Mock()
    client.day_overview.return_value = {'reply': 'Core-Aufgaben'}
    result = desktop_day_overview(client, path=path, now=datetime(2026, 10, 5, 9, tzinfo=ZoneInfo('Europe/Vienna')))
    assert 'Core-Aufgaben' in result and 'Schule' in result and 'Morgen' not in result
    assert 'Zustellstatus' in result and 'bereits erreicht' in result


@pytest.fixture
def qt(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])


def process_until(qt, predicate):
    until = time.monotonic() + 3
    while not predicate() and time.monotonic() < until:
        qt.processEvents()
        time.sleep(.01)
    assert predicate()


def test_text_preview_requires_button_and_copy_is_explicit(qt):
    from desktop.text_selection_dialog import TextSelectionDialog
    operation = Mock(return_value={'reply': 'Zusammenfassung'})
    dialog = TextSelectionDialog(None, 'Ausgewählter Text', operation)
    operation.assert_not_called()
    dialog.choice.setCurrentIndex(1)
    dialog.run()
    process_until(qt, lambda: dialog.create.isEnabled())
    assert dialog.result.toPlainText() == 'Zusammenfassung'
    operation.assert_called_once_with('Ausgewählter Text', 'summarize', 'Deutsch')
    dialog.copy.click()
    from PyQt6.QtWidgets import QApplication
    assert QApplication.clipboard().text() == 'Zusammenfassung'
    dialog.close()


def test_selection_empty_password_large_and_changed_window_never_transform(qt):
    from desktop.core.text_selection import SelectionCapture
    capture = SelectionCapture()
    capture.observer = Mock()
    target = {'hwnd': 123, 'pid': 99}
    capture.observer.foreground.return_value = target
    selected, errors = Mock(), Mock()
    capture.selected.connect(selected)
    capture.failed.connect(errors)
    for status in ('password', 'empty', 'too_large'):
        capture._after_read(target, {'status': status})
    selected.assert_not_called()
    assert errors.call_count == 3
    capture.observer.foreground.return_value = {'hwnd': 456, 'pid': 99}
    capture._after_read(target, {'status': 'selected', 'text': 'falsches Fenster'})
    selected.assert_not_called()
    capture._finish(text='x' * 16001)
    selected.assert_not_called()


def test_routine_ui_switches_profiles_and_saves_selected_name(tmp_path, qt):
    from desktop.work_routine_dialog import WorkRoutineDialog
    store = WorkRoutineStore(tmp_path / 'routine.json')
    store.save(WorkRoutine(True, ['editor'], 30, 30))
    store.save(WorkRoutine(True, ['firefox'], 10, 15), 'schulmodus')
    dialog = WorkRoutineDialog(store=store)
    dialog.name.setCurrentText('schulmodus')
    assert dialog.apps['firefox'].isChecked() and not dialog.apps['editor'].isChecked()
    assert dialog.focus.value() == 10
    dialog.focus.setValue(20)
    dialog.save()
    assert store.load('schulmodus').focus_minutes == 20
    assert store.load().focus_minutes == 30
    dialog.close()


def test_attachment_restore_uses_only_saved_selection_and_keeps_provenance(tmp_path, qt):
    from desktop.attachment_overlay import AttachmentOverlay
    path = tmp_path / 'note.md'
    path.write_text('alter Inhalt', encoding='utf-8')
    doc = extract_attachment(str(path))
    overlay = AttachmentOverlay()
    overlay.replace_documents([doc])
    assert overlay.checkpoint_documents()[0]['local_path'] == str(path)
    assert 'local_path' not in overlay.snapshot()[0]
    path.write_text('neuer Inhalt', encoding='utf-8')
    assert overlay.snapshot()[0]['body'] == 'alter Inhalt'
    overlay.clear()
    assert not overlay.snapshot()
    overlay.close()
