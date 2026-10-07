"""End-to-end boundaries for the six follow-on assistance workflows."""
import json
import threading
import time
from datetime import datetime, UTC, timedelta
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from backend.services.api.app import create_app
from desktop.core.dictation import DictationDraft
from desktop.core.flashcards import FlashcardStore
from desktop.core.native_commands import LocalTimers, NativeCommands
from desktop.core.workspace import ProjectWorkspaceStore
from mica_shared.quick_commands import parse_quick_command

DOCUMENT = {'id': 'a' * 32, 'title': 'Arbeitsblatt.md', 'body': 'Aufgabe: Berechne den Flächeninhalt des Rechtecks.\nAbgabe am 9. Oktober 2026 um 16 Uhr.', 'source': 'text'}
SOURCE = {'document_id': DOCUMENT['id'], 'title': DOCUMENT['title'], 'quote': 'Berechne den Flächeninhalt des Rechtecks.', 'start': 9, 'end': 50, 'line': 1}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv('MICA_API_TOKEN', 'extension-test-token-xxxxxxxxxxxxxxxxx')
    monkeypatch.setenv('MICA_PHASE3_ENABLED', '1')
    monkeypatch.setenv('MICA_LAYA_ENABLED', '0')
    monkeypatch.setenv('MICA_HINDSIGHT_ENABLED', '0')
    app = create_app(data_dir=tmp_path)
    runtime = app.state.runtime
    runtime._local_completion = Mock(return_value=json.dumps({'items': [{'title': 'Flächeninhalt berechnen', 'document_id': DOCUMENT['id'], 'quote': SOURCE['quote'], 'due_at': None}]}))
    with TestClient(app, headers={'X-Mica-API-Token': 'extension-test-token-xxxxxxxxxxxxxxxxx'}) as client:
        yield client, runtime


def test_document_tasks_preview_has_exact_source_and_only_confirmed_create_persists(api):
    client, runtime = api
    payload = {'session_id': 'b' * 32, 'documents': [DOCUMENT], 'operation': 'tasks', 'instruction': 'Aufgaben für diese Woche'}
    response = client.post('/v1/documents/draft', json=payload)
    assert response.status_code == 200, response.text
    item = response.json()['items'][0]
    source = item['source']
    assert source['quote'] == DOCUMENT['body'][source['start']:source['end']]
    assert client.get('/v1/task-items').json()['tasks'] == []
    saved = client.post('/v1/task-items', json={'title': item['title'], 'description': source['quote'], 'due_at': '2026-10-09T16:00:00+02:00'})
    assert saved.status_code == 200
    assert client.get('/v1/task-items').json()['tasks'][0]['due_at'] == '2026-10-09T14:00:00+00:00'
    with runtime.dialog_sessions.session('b' * 32) as state:
        assert state.documents == []


def test_task_confirmation_retry_cannot_duplicate_or_change_an_already_saved_request(api):
    client, runtime = api
    draft = {'title': 'Prüfaufgabe', 'description': SOURCE['quote'], 'idempotency_key': 'd' * 32}
    first = client.post('/v1/task-items', json=draft)
    second = client.post('/v1/task-items', json=draft)
    assert first.status_code == second.status_code == 200
    assert first.json()['id'] == second.json()['id']
    assert len(client.get('/v1/task-items').json()['tasks']) == 1
    assert client.post('/v1/task-items', json={**draft, 'title': 'Andere Aufgabe'}).status_code == 422


def test_task_reminder_is_not_cancelled_or_corrected_by_plain_timer_commands(tmp_path):
    timer = LocalTimers(Mock(), path=tmp_path / 'timers.json')
    timer.start(300, followup_seconds=60)
    timer.start(86400 * 7, task_id='a' * 32, label='Abgabe')
    assert 'ab jetzt' in timer.correct_latest(600, 300)
    assert any(item['task_id'] == 'a' * 32 for item in timer._items.values())
    assert next(item for item in timer._items.values() if not item['task_id'])['followup_seconds'] == 60
    timer.cancel_latest()
    assert len(timer._items) == 1 and next(iter(timer._items.values()))['task_id'] == 'a' * 32
    timer.shutdown()
    reopened = LocalTimers(Mock(), path=timer.path)
    reopened.restore()
    assert len(reopened._items) == 1
    reopened.cancel_all()
    reopened.shutdown()


def test_legacy_message_snooze_keeps_full_ten_minutes_and_new_script_actions(tmp_path, monkeypatch):
    from desktop.actions import reminder as reminders
    class FixedTime(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 10, 7, 12, 1, 45, 500000)
    monkeypatch.setattr(reminders, 'datetime', FixedTime)
    monkeypatch.setattr(reminders, '_scripts_dir', lambda: tmp_path)
    register = Mock(return_value='test-reminder-job')
    monkeypatch.setattr(reminders, '_schedule_windows', register)
    monkeypatch.setattr(reminders, '_record_reminder', Mock())
    assert reminders.snooze_reminder('Erinnere mich an die Abgabe') == 'test-reminder-job'
    target, name, path, text = register.call_args.args
    assert 600 <= (target - FixedTime.now()).total_seconds() <= 601
    source = path.read_text(encoding='utf-8')
    assert 'show_standalone' in source and '/Delete' in source and name in source
    compile(source, str(path), 'exec')


def test_legacy_windows_reminder_xml_escapes_user_paths(tmp_path, monkeypatch):
    from desktop.actions import reminder as reminders
    from xml.etree import ElementTree as ET
    scripts = tmp_path / 'a & b'
    scripts.mkdir()
    monkeypatch.setattr(reminders, '_scripts_dir', lambda: scripts)
    captured = []
    def run(args, **kwargs):
        captured.append(ET.parse(args[args.index('/XML') + 1]))
        return Mock(returncode=0)
    monkeypatch.setattr(reminders.subprocess, 'run', run)
    target = datetime(2026, 10, 7, 12, 1, 46)
    assert reminders._schedule_windows(target, 'JARVISReminder_test', scripts / 'test.py', 'message')
    ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
    assert 'a & b' in captured[0].find('.//t:Arguments', ns).text
    assert captured[0].find('.//t:StartBoundary', ns).text.endswith('12:01:46')


def test_invalid_flashcard_edit_keeps_saved_cards_unchanged(tmp_path):
    store = FlashcardStore(tmp_path / 'cards.json')
    card = {'question': 'Was berechnen?', 'answer': SOURCE['quote'], 'source': SOURCE}
    store.add([card])
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.add([{**card, 'question': 'x' * 501}])
    assert store.path.read_bytes() == before


@pytest.mark.parametrize('quote,due', [('Inventierte Quelle', None), (SOURCE['quote'], 'Freitag'), (SOURCE['quote'], '2026-10-09T16:00:00')])
def test_invalid_source_or_due_draft_is_rejected_without_writes(api, quote, due):
    client, runtime = api
    runtime._local_completion.return_value = json.dumps({'items': [{'title': 'Rechnen', 'document_id': DOCUMENT['id'], 'quote': quote, 'due_at': due}]})
    response = client.post('/v1/documents/draft', json={'session_id': 'b' * 32, 'documents': [DOCUMENT], 'operation': 'tasks'})
    assert response.status_code == 422
    assert client.get('/v1/task-items').json()['tasks'] == []


def test_cards_only_use_verified_answer_and_persist_review_dates(api, tmp_path):
    client, runtime = api
    runtime._local_completion.return_value = json.dumps({'items': [{'question': 'Was sollst du berechnen?', 'document_id': DOCUMENT['id'], 'quote': SOURCE['quote'], 'answer': 'unsupported model claim'}]})
    response = client.post('/v1/documents/draft', json={'session_id': 'b' * 32, 'documents': [DOCUMENT], 'operation': 'cards'})
    item = response.json()['items'][0]
    assert item['answer'] == SOURCE['quote']
    store = FlashcardStore(tmp_path / 'cards.json')
    now = datetime(2026, 10, 7, tzinfo=UTC)
    store.add([item, item], now=now)
    assert len(store.due(now=now)) == 1
    card = store.due(now=now)[0]
    store.rate(card['id'], 'easy', now=now)
    assert not store.due(now=now + timedelta(days=3))
    assert FlashcardStore(store.path).due(now=now + timedelta(days=4))
    store.rate(card['id'], 'again', now=now + timedelta(days=4))
    assert not store.due(now=now + timedelta(days=4, minutes=9))
    assert store.due(now=now + timedelta(days=4, minutes=10))
    store.delete(card['id'])
    assert store.all() == []


def test_project_progress_requires_opt_in_retains_baselines_and_is_shown_on_restart(tmp_path):
    store = ProjectWorkspaceStore(tmp_path / 'projects.json', tmp_path / 'absent')
    store.save([], None, 'Aufgabe 2 rechnen', name='schule', last_step='Aufgabe 1 geprüft')
    assert not store.record_progress('schule', 'Erkläre die Formel')
    store.save([], None, 'Aufgabe 2 rechnen', name='schule', last_step='Aufgabe 1 geprüft', remember_progress=True)
    assert store.record_progress('schule', 'Erkläre die Formel')
    restarted = ProjectWorkspaceStore(store.path, tmp_path / 'absent')
    assert restarted.load('schule')['last_step'] == 'Zuletzt besprochen: Erkläre die Formel'
    assert restarted.load('schule')['next_step'] == 'Aufgabe 2 rechnen'
    assert restarted.all()['schule'][0]['last_step'] == 'Aufgabe 1 geprüft'


def test_document_task_controller_saves_quote_and_schedules_exact_task(api):
    from desktop.local_main import LocalMica
    from desktop.core.local_core_client import LocalCoreClient
    from types import SimpleNamespace
    client, runtime = api
    mica = LocalMica.__new__(LocalMica)
    mica._request_lock = threading.RLock()
    mica._restoring = False
    mica.ui = SimpleNamespace(remember_conversations=True)
    core = LocalCoreClient('https://localhost', api_token='test')
    def request(method, path, **kwargs):
        response = client.request(method, path, json=kwargs.get('json'))
        assert response.status_code == 200, response.text
        return response.json()
    core._request = request
    mica.client = core
    mica.timers = Mock(wall_clock=Mock(return_value=datetime(2026, 10, 7, tzinfo=UTC).timestamp()))
    item = {'title': 'Rechteck berechnen', 'source': SOURCE, 'due_at': '2026-10-09T16:00:00+02:00', 'idempotency_key': 'e' * 32}
    result = mica._document_drafts_operation('save', {'kind': 'tasks', 'items': [(0, item)]})
    assert result == {'saved': [0]}
    task = client.get('/v1/task-items').json()['tasks'][0]
    assert SOURCE['quote'] in task['description'] and DOCUMENT['title'] in task['description']
    assert mica.timers.start.call_args.kwargs == {'task_id': task['id'], 'label': task['title']}
    assert mica.timers.start.call_args.args[0] == 223200
    core.session.close()


def test_actionable_notifications_wait_for_quiet_end_without_losing_records():
    from desktop.local_main import LocalMica
    from desktop.core.work_routine import QuietPeriod
    from types import SimpleNamespace
    mica = LocalMica.__new__(LocalMica)
    clock = [0]
    mica.quiet = QuietPeriod(clock=lambda: clock[0])
    mica.quiet.begin(1)
    mica._quiet_was_active = True
    mica._quiet_reminders, mica._quiet_reminders_lock = [], threading.Lock()
    signal = Mock()
    mica.ui = SimpleNamespace(write_log=Mock(), _win=SimpleNamespace(_reminder_sig=signal, _routine_button=Mock()))
    mica.voice = SimpleNamespace(active=True)
    for index in range(8):
        mica._reminder_due({'label': str(index)})
    signal.emit.assert_not_called()
    clock[0] = 61
    mica._quiet_tick()
    assert signal.emit.call_count == 8 and not mica._quiet_reminders
    mica._reminder_due({'label': 'Nach Ruhezeit'})
    assert signal.emit.call_count == 9


def test_dictation_replacement_spoken_commands_and_undo_never_execute():
    draft = DictationDraft()
    draft.accept('Erster Satz. Zweiter Satz.')
    draft.accept('Ersetze den letzten Satz durch Ein anderer Satz.')
    assert draft.text == 'Erster Satz. Ein anderer Satz.'
    draft.accept('Rückgängig')
    assert draft.text == 'Erster Satz. Zweiter Satz.'
    assert draft.accept('Ersetze den letzten Satz') == 'replacement_pending'
    draft.accept('Neuer Satz.')
    assert draft.text == 'Erster Satz. Neuer Satz.'
    assert draft.accept('Mach daraus Stichpunkte') == 'bullets'
    assert draft.text == 'Erster Satz. Neuer Satz.'
    draft.accept('Öffne Chrome')
    assert draft.text.endswith('Öffne Chrome')


@pytest.mark.parametrize('text,kind', [('Erstelle einen Schulmodus: Unterlagen öffnen, 45 Minuten Fokus und danach Pause.', 'routine_draft'),
    ('Mach aus diesem Arbeitsblatt meine Aufgaben für diese Woche.', 'document_tasks'), ('Lernkarten erstellen', 'document_cards'),
    ('Lernkarten wiederholen', 'review_cards'), ('Diktiermodus starten', 'dictation')])
def test_commands_are_exact_on_backend_and_desktop(api, text, kind):
    client, runtime = api
    response = client.post('/v1/turns', json={'message': text, 'native_commands': True}).json()
    assert response['command'] == parse_quick_command(text)
    assert response['command']['kind'] == kind
    runtime._local_completion.assert_not_called()
    commands = NativeCommands(Mock(), Mock())
    assert 'nicht ausgeführt' in commands.execute({**response['command'], 'extra': 'unsafe'}, text)


def test_routine_pause_survives_timer_restart_and_starts_after_focus(tmp_path):
    path = tmp_path / 'timers.json'
    clock = [1000]
    timer = LocalTimers(Mock(), path=path, wall_clock=lambda: clock[0])
    timer.start(60, followup_seconds=300)
    timer.shutdown()
    clock[0] = 1061
    pause = threading.Event()
    reopened = LocalTimers(lambda text: pause.set() if 'Pause läuft' in text else None, path=path, wall_clock=lambda: clock[0])
    reopened.restore()
    assert pause.wait(2)
    assert [item['seconds'] for item in reopened._items.values()] == [300]
    reopened.cancel_all()
    reopened.shutdown()


@pytest.fixture
def qt(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def until(qt, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        qt.processEvents()
        time.sleep(.01)
    assert predicate()


def test_routine_conversation_preview_edit_save_no_start(qt, tmp_path):
    from desktop.work_routine_dialog import WorkRoutineDialog
    from desktop.core.work_routine import WorkRoutineStore
    store = WorkRoutineStore(tmp_path / 'routine.json')
    draft = parse_quick_command('Erstelle einen Schulmodus: Unterlagen öffnen, 45 Minuten Fokus und danach 10 Minuten Pause.')
    doc = {**DOCUMENT, 'local_path': str(tmp_path / 'worksheet.md')}
    dialog = WorkRoutineDialog(store=store, draft=draft, documents=[doc])
    assert dialog.focus.value() == 45 and dialog.pause.value() == 10
    assert not store.path.exists()
    dialog.pause.setValue(15)
    dialog.save()
    current = store.load('schulmodus')
    assert current.pause_minutes == 15 and current.documents == [doc['local_path']]
    assert current.enabled


def test_project_preview_displays_last_and_next_steps(qt, tmp_path):
    from desktop.workspace_dialog import WorkspaceDialog
    store = ProjectWorkspaceStore(tmp_path / 'projects.json', tmp_path / 'absent')
    store.save([], None, 'Aufgabe 2 rechnen', name='schule', last_step='Aufgabe 1 fertig', remember_progress=True)
    dialog = WorkspaceDialog(None, Mock(), [], store=store, project='schule', prefer_load=True)
    assert 'Hier warst du: Aufgabe 1 fertig' in dialog.preview.text()
    assert 'Nächster Schritt: Aufgabe 2 rechnen' in dialog.preview.text()
    assert dialog.remember_progress.isChecked()
    dialog.close()


def test_flashcard_review_reveals_source_then_stores_rating(qt, tmp_path):
    from desktop.flashcards_dialog import FlashcardsDialog
    store = FlashcardStore(tmp_path / 'cards.json')
    store.add([{'question': 'Was berechnen?', 'answer': SOURCE['quote'], 'source': SOURCE}])
    dialog = FlashcardsDialog(store=store)
    assert not dialog.answer.toPlainText()
    assert not any(button.isEnabled() for button in dialog.ratings)
    dialog.show_answer()
    assert SOURCE['quote'] in dialog.answer.toPlainText() and DOCUMENT['title'] in dialog.answer.toPlainText()
    dialog.rate('hard')
    assert not dialog.current
    assert store.all()[0]['reviews'] == 1 and store.all()[0]['interval'] == 1
    dialog.close()


def test_reminder_buttons_open_complete_and_snooze(qt):
    from desktop.reminder_notification import ReminderNotification
    client, snooze = Mock(), Mock()
    client._request.return_value = {'title': 'Aufgabe', 'status': 'open', 'description': 'Quelle: Arbeitsblatt', 'due_at': None}
    popup = ReminderNotification({'task_id': 'a' * 32, 'label': 'Aufgabe'}, snooze, client=client)
    popup.show_task()
    until(qt, lambda: popup.open_task.isEnabled())
    assert 'Arbeitsblatt' in popup.details.toPlainText()
    popup.later.click()
    until(qt, lambda: snooze.called)
    snooze.assert_called_once_with(popup.record, 600)
    popup2 = ReminderNotification(popup.record, snooze, client=client)
    popup2.finish_reminder()
    until(qt, lambda: client.update_task.called)
    client.update_task.assert_called_once_with('a' * 32, 'completed')
    popup.close()
    popup2.close()


def test_document_preview_save_failure_only_retries_unsaved_rows(qt):
    from desktop.document_drafts_dialog import DocumentDraftsDialog
    operation = Mock()
    items = [{'title': 'Aufgabe 1', 'due_at': None, 'source': SOURCE}, {'title': 'Aufgabe 2', 'due_at': None, 'source': SOURCE}]
    operation.return_value = {'items': items}
    dialog = DocumentDraftsDialog(None, [DOCUMENT], operation)
    dialog.draft()
    until(qt, lambda: dialog.save.isEnabled())
    assert operation.call_count == 1
    operation.return_value = {'saved': [0], 'error': 'Testfehler'}
    dialog.persist()
    until(qt, lambda: 0 in dialog.saved)
    operation.return_value = {'saved': [1]}
    dialog.persist()
    until(qt, lambda: len(dialog.saved) == 2)
    assert [row for row, item in operation.call_args.args[1]['items']] == [1]
    assert not dialog.save.isEnabled()
    dialog.close()


def test_dictation_preview_receives_only_transcription_and_ignores_cancelled_clip(qt):
    from desktop.dictation_dialog import DictationDialog
    transcribe = Mock(return_value={'text': 'Ein Satz.'})
    dialog = DictationDialog(None, transcribe, Mock(), recording=lambda stop, cancel: b'\0\0' * 100)
    dialog.toggle_record()
    until(qt, lambda: not dialog.busy)
    assert dialog.editor.toPlainText() == 'Ein Satz.'
    assert not dialog.capture
    dialog.done(0)
    dialog.finished_work('Nicht übernehmen', '', 0)
    assert dialog.editor.toPlainText() == 'Ein Satz.'
