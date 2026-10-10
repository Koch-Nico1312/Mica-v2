"""Check the five assistance features against user-visible outcomes and failure paths."""
import json
import threading
import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from backend.services.api.app import create_app
from backend.services.common.task_automation import TaskAutomationStore, TaskConflict
from desktop.core.day_planner import build_day_plan
from desktop.core.offline_tasks import OfflineTasks
from desktop.core.outcome_verification import file_snapshot, verify_file, verify_window
from desktop.core.project_export import project_markdown, write_export
from desktop.core.local_core_client import LocalCoreError, LocalCoreUnavailable
from desktop.core.workspace import ProjectWorkspaceStore

START = datetime.fromisoformat('2026-10-08T09:00:00+02:00')


def task(identifier='a', title='Prüfung lernen', **fields):
    return {'id': identifier * 32, 'title': title, 'description': '', 'status': 'open', 'priority': 'normal',
        'due_at': None, 'minutes': 30, **fields}


def test_plan_respects_deadline_breaks_free_time_and_reports_overflow():
    tasks = [task('a', minutes=60), task('b', 'Abgabe', due_at=(START + timedelta(minutes=35)).isoformat(), minutes=30)]
    plan = build_day_plan(tasks, [(START, START + timedelta(minutes=90))], focus_minutes=30, break_minutes=10)
    assert plan['blocks'][0]['task_id'] == 'b' * 32
    assert [block['kind'] for block in plan['blocks']] == ['task', 'break', 'task', 'break', 'task']
    assert plan['unplanned'] == [{'task_id': 'a' * 32, 'title': 'Prüfung lernen', 'minutes': 20, 'reason': 'Frist, fehlende Voraussetzung oder zu wenig freie Zeit.'}]
    for block in plan['blocks']:
        assert START <= datetime.fromisoformat(block['start']) < datetime.fromisoformat(block['end']) <= START + timedelta(minutes=90)


def test_dependencies_cannot_be_scheduled_ahead_of_their_prerequisite():
    tasks = [task('a', minutes=20, depends_on=['b' * 32]), task('b', 'Lesen', minutes=20)]
    plan = build_day_plan(tasks, [(START, START + timedelta(minutes=60))], break_minutes=5)
    assert [block['task_id'] for block in plan['blocks'] if block['kind'] == 'task'] == ['b' * 32, 'a' * 32]
    cyclic = build_day_plan([task('a', depends_on=['b' * 32]), task('b', depends_on=['a' * 32])], [(START, START + timedelta(hours=2))])
    assert not cyclic['blocks'] and len(cyclic['unplanned']) == 2


def test_final_short_segment_and_adjacent_windows_keep_work_and_pauses():
    plan = build_day_plan([task(minutes=60)], [(START, START + timedelta(minutes=60)),
        (START + timedelta(minutes=60), START + timedelta(minutes=90))], focus_minutes=28, break_minutes=10)
    work = [block for block in plan['blocks'] if block['kind'] == 'task']
    assert sum(block['minutes'] for block in work) == 60 and not plan['unplanned']
    for previous, current in zip(work, work[1:]):
        assert datetime.fromisoformat(current['start']) - datetime.fromisoformat(previous['end']) >= timedelta(minutes=10)


@pytest.mark.parametrize('windows', [[(START, START)], [(START, START + timedelta(hours=1)), (START, START + timedelta(hours=2))], [(START.replace(tzinfo=None), START + timedelta(hours=1))]])
def test_invalid_windows_are_rejected(windows):
    with pytest.raises(ValueError):
        build_day_plan([task()], windows)


def test_deadline_prevents_late_blocks_and_separate_windows_preserve_appointments():
    tasks = [task('a', minutes=60, due_at=(START + timedelta(minutes=25)).isoformat()), task('b', 'Nachmittag', minutes=90)]
    plan = build_day_plan(tasks, [(START, START + timedelta(minutes=60)), (START + timedelta(hours=3), START + timedelta(hours=4))])
    assert any(item['task_id'] == 'a' * 32 and item['minutes'] == 35 for item in plan['unplanned'])
    assert all(not (START + timedelta(hours=1) <= datetime.fromisoformat(block['start']) < START + timedelta(hours=3)) for block in plan['blocks'])


def test_saved_file_changes_need_evidence_not_merely_a_different_timestamp(tmp_path):
    path = tmp_path / 'saved.md'
    before_missing = file_snapshot(path)
    assert verify_file(path)['status'] == 'not_confirmed'
    path.write_text('Erster Text', encoding='utf-8')
    baseline = file_snapshot(path)
    assert verify_file(path, baseline=baseline, require_changed=True)['status'] == 'not_confirmed'
    assert verify_file(path, require_changed=True)['status'] == 'uncertain'
    path.write_text('Gespeicherte Änderung', encoding='utf-8')
    result = verify_file(path, baseline=baseline, require_changed=True, expected_text='Änderung')
    assert result['status'] == 'confirmed' and result['evidence']['sha256'] != baseline['sha256']
    assert verify_file(path, baseline=before_missing, require_changed=True)['status'] == 'confirmed'
    assert verify_file(path, expected_text='Nicht enthalten')['status'] == 'not_confirmed'
    path.write_bytes(b'\xff\xfe\x00')
    assert verify_file(path, expected_text='Text')['status'] == 'uncertain'


def test_window_check_is_read_only_and_never_claims_persistence():
    target = {'pid': 99, 'hwnd': 123, 'title': 'Testfenster'}
    reader = Mock(return_value={'status': 'read', 'text': 'Text: Einstellung gespeichert', 'truncated': False})
    result = verify_window(target, 'Einstellung gespeichert', reader=reader)
    assert result['status'] == 'confirmed' and 'nicht bewiesen' in result['detail']
    reader.assert_called_once_with(target)
    assert verify_window(target, 'Unbekannt', reader=reader)['status'] == 'uncertain'
    assert verify_window(target, 'Text', reader=lambda _: {'status': 'unsupported'})['status'] == 'uncertain'


def test_window_setting_change_must_be_new_and_belong_to_the_same_window():
    from desktop.core.outcome_verification import window_snapshot
    target = {'pid': 99, 'hwnd': 123, 'title': 'Einstellungen'}
    reader = Mock(return_value={'status': 'read', 'text': 'CheckBox: Speichern (ausgeschaltet)', 'truncated': False})
    baseline = window_snapshot(target, reader=reader)
    reader.return_value['text'] = 'CheckBox: Speichern (eingeschaltet)'
    expected = 'Speichern (eingeschaltet)'
    assert verify_window(target, expected, reader=reader, baseline=baseline, require_changed=True)['status'] == 'confirmed'
    assert verify_window(target, expected, reader=reader, baseline=baseline | {'hwnd': 456}, require_changed=True)['status'] == 'uncertain'
    already = window_snapshot(target, reader=reader)
    assert verify_window(target, expected, reader=reader, baseline=already, require_changed=True)['status'] == 'not_confirmed'
    assert verify_window(target, expected, reader=reader, baseline=baseline | {'truncated': True}, require_changed=True)['status'] == 'uncertain'


class StoreClient:
    def __init__(self, path):
        self.store = TaskAutomationStore(path)
        self.calls = []

    def task_items(self):
        return {'tasks': self.store.list_tasks(limit=500)}

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path))
        body = kwargs.get('json', {})
        if method == 'POST':
            return self.store.create_task(**body)
        if method == 'GET':
            return self.store.get_task(path.rsplit('/', 1)[-1])
        if method == 'PATCH':
            try:
                return self.store.update_task(path.rsplit('/', 1)[-1], body)
            except TaskConflict as error:
                raise LocalCoreError(str(error), status_code=409) from error
        raise AssertionError(method)


def test_offline_edits_survive_restart_and_read_only_reconnection(tmp_path):
    client = StoreClient(tmp_path / 'server.db')
    original = client.store.create_task('Alt')
    local = OfflineTasks(tmp_path / 'local.json')
    local.refresh(client)
    local.stage({**original, 'title': 'Offline geändert'}, minutes=50)
    reopened = OfflineTasks(local.path)
    assert reopened.view()[0]['title'] == 'Offline geändert'
    reopened.refresh(client)
    preview = reopened.preview(client)
    assert client.store.get_task(original['id'])['title'] == 'Alt' and all(method == 'GET' for method, _ in client.calls)
    reopened.apply(client, preview)
    assert client.store.get_task(original['id'])['title'] == 'Offline geändert'
    assert reopened.read()['pending'] == [] and reopened.view()[0]['minutes'] == 50


def test_remote_conflict_is_visible_and_cannot_overwrite_server(tmp_path):
    client = StoreClient(tmp_path / 'server.db')
    original = client.store.create_task('Ursprünglich')
    local = OfflineTasks(tmp_path / 'local.json')
    local.refresh(client)
    local.stage({**original, 'title': 'Lokaler Titel'})
    client.store.update_task(original['id'], {'title': 'Anderer neuer Titel'})
    preview = local.preview(client)
    assert preview[0]['conflict']
    assert local.apply(client, preview) == []
    assert client.store.get_task(original['id'])['title'] == 'Anderer neuer Titel'
    local.accept_remote(client, preview[0])
    assert local.read()['pending'] == [] and local.view()[0]['title'] == 'Anderer neuer Titel'


def test_change_after_preview_is_rejected_atomically(tmp_path):
    client = StoreClient(tmp_path / 'server.db')
    original = client.store.create_task('Original')
    local = OfflineTasks(tmp_path / 'local.json')
    local.refresh(client)
    local.stage({**original, 'title': 'Lokal'})
    preview = local.preview(client)
    client.store.update_task(original['id'], {'description': 'Inzwischen geändert'})
    with pytest.raises(LocalCoreError) as failure:
        local.apply(client, preview)
    assert failure.value.status_code == 409
    assert client.store.get_task(original['id'])['title'] == 'Original'
    assert local.read()['pending'] and not local.read()['pending'][0].get('attempted')


def test_lost_create_response_retry_cannot_duplicate_and_preserves_order(tmp_path):
    client = StoreClient(tmp_path / 'server.db')
    local = OfflineTasks(tmp_path / 'local.json')
    local.stage_steps([{'title': 'Lesen', 'minutes': 20}, {'title': 'Rechnen', 'minutes': 30}], {'title': 'Prüfung', 'id': None})
    preview = local.preview(client)
    request = client._request
    lost = True
    def interrupted(method, path, **kwargs):
        nonlocal lost
        result = request(method, path, **kwargs)
        if method == 'POST' and lost:
            lost = False
            raise LocalCoreUnavailable('Antwort verloren')
        return result
    client._request = interrupted
    with pytest.raises(LocalCoreUnavailable):
        local.apply(client, preview)
    assert len(client.store.list_tasks()) == 1 and len(local.read()['pending']) == 2
    with pytest.raises(ValueError):
        local.stage({**local.view()[0], 'title': 'Verändert'})
    local.apply(client, local.preview(client))
    assert len(client.store.list_tasks()) == 2 and not local.read()['pending']
    tasks = local.view()
    first = next(task for task in tasks if task['title'] == 'Lesen')
    second = next(task for task in tasks if task['title'] == 'Rechnen')
    assert second['depends_on'] == [first['id']]


def test_step_batch_is_atomic_and_does_not_mark_parent_complete(tmp_path):
    local = OfflineTasks(tmp_path / 'local.json')
    with pytest.raises(ValueError):
        local.stage_steps([{'title': 'Lesen', 'minutes': 20}, {'title': '', 'minutes': 30}], {'title': 'Prüfung', 'id': None})
    assert local.view() == []
    local.stage_steps([{'title': 'Lesen', 'minutes': 20}, {'title': 'Rechnen', 'minutes': 30}], {'title': 'Prüfung', 'id': None})
    assert len(local.view()) == 2 and all(task['status'] == 'open' for task in local.view())


def test_sync_fetches_old_tasks_by_id_even_when_the_list_does_not_contain_them(tmp_path):
    client = StoreClient(tmp_path / 'server.db')
    original = client.store.create_task('Ältere Aufgabe')
    local = OfflineTasks(tmp_path / 'local.json')
    local.refresh(client)
    local.stage({**original, 'title': 'Lokale Änderung'})
    client.task_items = lambda: {'tasks': []}  # The bounded list omits this still-existing task.
    reviewed = local.preview(client)[0]
    assert reviewed['remote']['id'] == original['id'] and not reviewed['conflict']
    with pytest.raises(ValueError):
        local.accept_remote(client, reviewed | {'remote': None, 'conflict': True})
    assert local.read()['pending'] and local.view()[0]['title'] == 'Lokale Änderung'
    local.apply(client, [reviewed])
    assert client.store.get_task(original['id'])['title'] == 'Lokale Änderung'


def test_successful_creation_keeps_a_full_cache_readable_and_preserves_pending(tmp_path):
    from desktop.core.local_state import write_json
    client = StoreClient(tmp_path / 'server.db')
    local = OfflineTasks(tmp_path / 'local.json')
    records = [task(f'{index:032x}', title=f'Cache {index}') | {'id': f'{index:032x}'} for index in range(500)]
    write_json(local.path, {'version': 1, 'tasks': records, 'pending': [], 'metadata': {}, 'fetched_at': None})
    queued = task('f', 'Neue Aufgabe')
    local.stage(queued)
    local.apply(client, local.preview(client))
    data = local.read()
    assert len(data['tasks']) == 500 and not data['pending']
    assert any(entry['title'] == 'Neue Aufgabe' for entry in data['tasks'])
    assert len(client.store.list_tasks()) == 1


def test_cache_capacity_is_checked_before_remote_write_if_every_slot_is_protected(tmp_path):
    from desktop.core.local_state import write_json
    client = StoreClient(tmp_path / 'server.db')
    local = OfflineTasks(tmp_path / 'local.json')
    identifiers = [f'{index:032x}' for index in range(500)]
    records = [task('a', title=f'Cache {index}') | {'id': identifier} for index, identifier in enumerate(identifiers)]
    metadata = {identifier: {'minutes': 30, 'depends_on': [identifiers[(index + 1) % 500]]} for index, identifier in enumerate(identifiers)}
    write_json(local.path, {'version': 1, 'tasks': records, 'pending': [], 'metadata': metadata, 'fetched_at': None})
    local.stage(task('f', 'Neue Aufgabe'))
    with pytest.raises(ValueError):
        local.apply(client, local.preview(client))
    assert not client.store.list_tasks() and not client.calls
    assert len(local.read()['tasks']) == 500 and len(local.read()['pending']) == 1


def test_editing_titles_and_minutes_preserves_parent_and_step_structure(tmp_path):
    client = StoreClient(tmp_path / 'server.db')
    original = client.store.create_task('Prüfung')
    local = OfflineTasks(tmp_path / 'local.json')
    local.refresh(client)
    local.stage_steps([{'title': 'Lesen', 'minutes': 20}, {'title': 'Rechnen', 'minutes': 30}], original)
    local.stage({**original, 'title': 'Neue Prüfung'}, minutes=70)
    first = next(entry for entry in local.view() if entry['title'] == 'Lesen')
    local.stage({**first, 'title': 'Unterlagen lesen'}, minutes=25)
    parent = next(entry for entry in local.view() if entry['id'] == original['id'])
    step = next(entry for entry in local.view() if entry['title'] == 'Unterlagen lesen')
    assert parent['container'] and parent['minutes'] == 70
    assert step['parent_id'] == parent['id'] and step['step'] == 1 and step['minutes'] == 25


def test_discarding_a_step_protects_dependencies_and_all_steps_restore_parent_planning(tmp_path):
    client = StoreClient(tmp_path / 'server.db')
    original = client.store.create_task('Prüfung')
    local = OfflineTasks(tmp_path / 'local.json')
    local.refresh(client)
    local.stage_steps([{'title': 'Lesen', 'minutes': 20}, {'title': 'Rechnen', 'minutes': 30}], original)
    pending = local.read()['pending']
    with pytest.raises(ValueError):
        local.discard(pending[0]['key'])
    assert len(local.read()['pending']) == 2
    local.discard(pending[1]['key'])
    local.discard(pending[0]['key'])
    assert not local.read()['pending'] and len(local.view()) == 1
    assert not local.view()[0].get('container')
    assert len(local.read()['metadata']) == 1


def test_lost_normalized_update_response_is_recognized_as_already_applied(tmp_path):
    client = StoreClient(tmp_path / 'server.db')
    original = client.store.create_task('Prüfung')
    local = OfflineTasks(tmp_path / 'local.json')
    local.refresh(client)
    local.stage({**original, 'title': '  Prüfung neu  ', 'description': '  Quelle  ', 'due_at': '2026-10-08T18:00:00+02:00'})
    reviewed = local.preview(client)
    real_request = client._request
    def lost_response(method, path, **kwargs):
        result = real_request(method, path, **kwargs)
        if method == 'PATCH':
            raise LocalCoreUnavailable('Antwort verloren')
        return result
    client._request = lost_response
    with pytest.raises(LocalCoreUnavailable):
        local.apply(client, reviewed)
    client._request = real_request
    before_count = sum(method == 'PATCH' for method, _ in client.calls)
    preview = local.preview(client)
    assert preview[0]['applied'] and not preview[0]['conflict']
    local.apply(client, preview)
    assert not local.read()['pending']
    assert sum(method == 'PATCH' for method, _ in client.calls) == before_count
    assert client.store.get_task(original['id'])['due_at'] == '2026-10-08T16:00:00+00:00'


def test_refresh_retains_completed_prerequisites_and_old_step_metadata_outside_the_list(tmp_path):
    client = StoreClient(tmp_path / 'server.db')
    prerequisite = client.store.create_task('Unterlagen gelesen')
    prerequisite = client.store.update_task(prerequisite['id'], {'status': 'completed'})
    parent = client.store.create_task('Prüfung')
    local = OfflineTasks(tmp_path / 'local.json')
    local.refresh(client)
    local.stage_steps([{'title': 'Üben', 'minutes': 20}, {'title': 'Kontrollieren', 'minutes': 20}], parent)
    local.apply(client, local.preview(client))
    step_before = next(entry for entry in local.view() if entry['title'] == 'Üben')
    queued = task('f', 'Folgeschritt')
    local.stage(queued, depends_on=[prerequisite['id']])
    client.task_items = lambda: {'tasks': []}  # All cached tasks fell out of the bounded list.
    local.refresh(client)
    after = local.view()
    assert next(entry for entry in after if entry['id'] == prerequisite['id'])['status'] == 'completed'
    step_after = next(entry for entry in after if entry['id'] == step_before['id'])
    assert step_after['parent_id'] == parent['id'] and step_after['step'] == 1
    assert next(entry for entry in after if entry['id'] == parent['id'])['container']
    plan = build_day_plan([entry for entry in after if entry['id'] in {prerequisite['id'], queued['id']}],
        [(START, START + timedelta(hours=1))])
    assert not plan['unplanned'] and plan['blocks'][0]['task_id'] == queued['id']


def test_refresh_connection_failure_and_concurrent_local_edit_preserve_the_snapshot(tmp_path):
    client = StoreClient(tmp_path / 'server.db')
    original = client.store.create_task('Aufgabe')
    local = OfflineTasks(tmp_path / 'local.json')
    local.refresh(client)
    before = local.path.read_bytes()
    client.task_items = lambda: {'tasks': []}
    request = client._request
    client._request = Mock(side_effect=LocalCoreUnavailable('Verbindung unterbrochen'))
    with pytest.raises(LocalCoreUnavailable):
        local.refresh(client)
    assert local.path.read_bytes() == before
    def edit_during_read(method, path, **kwargs):
        local.stage({**original, 'title': 'Währenddessen bearbeitet'})
        return request(method, path, **kwargs)
    client._request = edit_during_read
    with pytest.raises(ValueError):
        local.refresh(client)
    assert local.view()[0]['title'] == 'Währenddessen bearbeitet' and local.read()['pending']


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv('MICA_API_TOKEN', 'planning-test-token-xxxxxxxxxxxxxxxxxxx')
    monkeypatch.setenv('MICA_PHASE3_ENABLED', '1')
    monkeypatch.setenv('MICA_LAYA_ENABLED', '0')
    monkeypatch.setenv('MICA_HINDSIGHT_ENABLED', '0')
    app = create_app(data_dir=tmp_path)
    runtime = app.state.runtime
    runtime._local_completion = Mock(return_value=json.dumps({'steps': [{'title': 'Unterlagen lesen', 'description': 'Themen sammeln', 'minutes': 20}, {'title': 'Aufgaben rechnen', 'minutes': 45}]}))
    with TestClient(app, headers={'X-Mica-API-Token': 'planning-test-token-xxxxxxxxxxxxxxxxxxx'}) as client:
        yield client, runtime


def test_real_api_step_preview_requires_explicit_create_and_checks_auth(api):
    client, runtime = api
    response = client.post('/v1/task-items/decompose', json={'title': 'Für die Prüfung lernen'})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['preview'] and not result['stored'] and result['steps'][1]['after'] == 0
    assert client.get('/v1/task-items').json()['tasks'] == []
    assert client.post('/v1/task-items/decompose', json={'title': 'Probe'}, headers={'X-Mica-API-Token': 'invalid'}).status_code == 401
    runtime._local_completion.return_value = '{"steps":[{"title":"Nur einer","minutes":20}]}'
    assert client.post('/v1/task-items/decompose', json={'title': 'Probe'}).status_code == 422


def test_api_concurrency_guard_and_step_emergency_gate(api):
    client, runtime = api
    task = client.post('/v1/task-items', json={'title': 'Probe'}).json()
    assert client.patch('/v1/task-items/' + task['id'], json={'title': 'Neu', 'expected_updated_at': task['updated_at']}).status_code == 200
    assert client.patch('/v1/task-items/' + task['id'], json={'title': 'Veraltet', 'expected_updated_at': task['updated_at']}).status_code == 409
    runtime.policy.set_emergency_stop(True)
    assert client.post('/v1/task-items/decompose', json={'title': 'Probe'}).status_code == 409


def test_markdown_export_contains_only_selected_tasks_and_literal_source_content(tmp_path):
    store = ProjectWorkspaceStore(tmp_path / 'projects.json', tmp_path / 'absent')
    document = {'id': 'd' * 32, 'title': 'Quelle.md', 'body': 'Wörtliche Quelle\n![[anderes-projekt]]\n<script>alert(1)</script>', 'source': 'text'}
    checkpoint = store.save([document], None, 'Kontrollieren', name='schule', last_step='Gelesen')
    markdown = project_markdown('schule', checkpoint, [task(description='Quelle: Quelle.md · Zeile 1\nWörtliche Quelle')])
    assert 'Gelesen' in markdown and 'Kontrollieren' in markdown and 'Wörtliche Quelle' in markdown
    assert '![[anderes-projekt]]' not in markdown and '<script>' not in markdown
    path = tmp_path / 'schule.md'
    write_export(path, markdown)
    assert path.read_text(encoding='utf-8') == markdown
    with pytest.raises(ValueError):
        write_export(tmp_path / 'script.html', markdown)


def test_offline_project_load_and_explicit_sync_keep_saved_task_identity(tmp_path):
    from desktop.local_main import LocalMica
    store = ProjectWorkspaceStore(tmp_path / 'projects.json', tmp_path / 'absent')
    checkpoint = store.save([], 'a' * 32, 'Weiterlernen', name='schule', last_step='Lesen')
    mica = LocalMica.__new__(LocalMica)
    mica._request_lock, mica._restoring = threading.RLock(), False
    mica.ui = SimpleNamespace(remember_conversations=True)
    mica.client = Mock()
    mica.client.resume_workspace.side_effect = LocalCoreUnavailable('Verbindung aus')
    result = mica._workspace_operation('load', checkpoint | {'project': 'schule'}, store)
    assert result['offline'] and mica._offline_workspace
    assert store.load('schule')['task_id'] == 'a' * 32
    with pytest.raises(LocalCoreUnavailable):
        mica._workspace_operation('sync', checkpoint | {'project': 'schule'}, store)
    mica.client.resume_workspace.side_effect = None
    assert not mica._workspace_operation('sync', checkpoint | {'project': 'schule'}, store)['offline']
    assert not mica._offline_workspace
    mica.client.resume_workspace.side_effect = LocalCoreError('Aufgabe gelöscht', status_code=404)
    with pytest.raises(LocalCoreError):
        mica._workspace_operation('load', checkpoint | {'project': 'schule'}, store)


def test_saving_offline_without_loading_preserves_the_saved_project_task(tmp_path):
    from desktop.local_main import LocalMica
    store = ProjectWorkspaceStore(tmp_path / 'projects.json', tmp_path / 'absent')
    store.save([], 'a' * 32, 'Alter Schritt', name='schule', task_title='Prüfung')
    mica = LocalMica.__new__(LocalMica)
    mica._request_lock, mica._restoring = threading.RLock(), False
    mica.ui = SimpleNamespace(remember_conversations=True)
    mica.client = Mock()
    mica.client.workspace_context.side_effect = LocalCoreError('Gateway offline', status_code=503)
    result = mica._workspace_operation('save', {'documents': [], 'next_step': 'Neuer Schritt', 'project': 'schule'}, store)
    assert result['offline'] and result['task_id'] == 'a' * 32 and result['task_title'] == 'Prüfung'
    assert store.load('schule')['next_step'] == 'Neuer Schritt'
    assert mica._offline_workspace


def test_offline_launcher_opens_the_canonical_ui_without_starting_services(monkeypatch):
    import desktop.start_mica as launcher
    start = Mock(side_effect=AssertionError('Must not start services'))
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(launcher, 'start_core', start)
    monkeypatch.setattr(launcher.subprocess, 'run', run)
    assert launcher.main(offline=True) == 0
    start.assert_not_called()
    assert run.call_args.args[0][1] == str(launcher.ROOT / 'desktop/local_main.py')
    assert run.call_args.kwargs['env']['MICA_START_OFFLINE'] == '1'


def test_offline_start_window_continues_only_after_finished_failure(qt):
    from pathlib import Path
    from desktop.startup_window import StartupWindow
    window = StartupWindow(lambda progress: (_ for _ in ()).throw(RuntimeError('Controlled offline')), Path.cwd())
    window.begin()
    until(qt, lambda: window.worker and not window.worker.isRunning() and window.outcome == 'failed')
    qt.processEvents()
    assert not window.offline_button.isHidden()
    window.offline_button.click()
    assert window.outcome == 'offline' and window.result() == window.DialogCode.Accepted
    window.close()


def test_explicit_offline_start_performs_no_backend_or_microphone_request():
    from desktop.local_main import LocalMica
    mica = LocalMica.__new__(LocalMica)
    mica._offline_start, mica.client, mica.ui = True, Mock(), Mock()
    mica.wake_word = Mock()
    mica.start()
    mica.client.health.assert_not_called()
    mica.wake_word.start.assert_not_called()
    mica.ui.set_state.assert_called_once_with('OFFLINE')


def test_explicit_offline_project_save_load_stay_local_until_confirmed_sync(tmp_path):
    from desktop.local_main import LocalMica
    store = ProjectWorkspaceStore(tmp_path / 'projects.json', tmp_path / 'absent')
    checkpoint = store.save([], 'a' * 32, 'Weiter', name='schule')
    mica = LocalMica.__new__(LocalMica)
    mica._request_lock, mica._restoring, mica._offline_start = threading.RLock(), False, True
    mica.ui, mica.client = SimpleNamespace(remember_conversations=True), Mock()
    assert mica._workspace_operation('load', checkpoint | {'project': 'schule'}, store)['offline']
    mica._workspace_operation('save', {'documents': [], 'next_step': 'Neuer Schritt', 'project': 'schule'}, store)
    mica.client.resume_workspace.assert_not_called()
    mica.client.workspace_context.assert_not_called()
    saved = store.load('schule')
    assert saved['task_id'] == 'a' * 32
    result = mica._workspace_operation('sync', saved | {'project': 'schule'}, store)
    assert not result['offline'] and not mica._offline_start
    mica.client.resume_workspace.assert_called_once()


@pytest.fixture
def qt(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def until(qt, condition):
    limit = time.monotonic() + 5
    while not condition() and time.monotonic() < limit:
        qt.processEvents()
        time.sleep(.01)
    assert condition()


def test_day_plan_requires_preview_and_explicit_acceptance(qt, tmp_path, monkeypatch):
    import desktop.task_planning_dialog as module
    monkeypatch.setattr(module, 'DATA_DIR', tmp_path)
    store = OfflineTasks(tmp_path / 'tasks.json')
    store.stage(task(), minutes=30)
    dialog = module.TaskPlanningDialog(None, Mock(), store=store, page='plan')
    assert not (tmp_path / 'day-plan.json').exists() and not dialog.accept_plan.isEnabled()
    dialog.preview_plan()
    assert dialog.accept_plan.isEnabled() and 'Prüfung lernen' in dialog.plan_text.toPlainText()
    assert not (tmp_path / 'day-plan.json').exists()
    dialog.save_plan()
    assert json.loads((tmp_path / 'day-plan.json').read_text(encoding='utf-8'))['accepted_at']
    dialog.pause.setValue(15)
    assert not dialog.accept_plan.isEnabled() and dialog.plan is None
    dialog.table.setCurrentCell(0, 1)
    dialog.new_task()
    assert dialog.editing_id is None and not dialog.title.text()
    dialog.preview_plan()
    store.stage({**store.view()[0], 'title': 'Inzwischen anders'}, minutes=50)
    previous = (tmp_path / 'day-plan.json').read_bytes()
    dialog.save_plan()
    assert (tmp_path / 'day-plan.json').read_bytes() == previous and 'erneut' in dialog.status.text()
    dialog.close()


def test_file_check_dialog_uses_real_file_and_read_only_controls(qt, tmp_path):
    from desktop.outcome_dialog import OutcomeDialog
    path = tmp_path / 'note.md'
    path.write_text('Alt', encoding='utf-8')
    dialog = OutcomeDialog(None)
    dialog.path.setText(str(path))
    dialog.run('baseline')
    until(qt, lambda: not dialog.busy)
    path.write_text('Neu gespeichert', encoding='utf-8')
    dialog.expected.setText('Neu gespeichert')
    dialog.changed.setChecked(True)
    dialog.run('file')
    until(qt, lambda: not dialog.busy)
    assert dialog.result.toPlainText().startswith('Bestätigt')
    assert path.read_text(encoding='utf-8') == 'Neu gespeichert'
    dialog.close()


def test_markdown_dialog_task_selection_and_source_cards_are_explicit(qt, tmp_path, monkeypatch):
    from PyQt6.QtCore import Qt
    import desktop.project_export_dialog as module
    client = StoreClient(tmp_path / 'server.db')
    included = client.store.create_task('Projektaufgabe')
    client.store.create_task('Anderes Projekt privat')
    local = OfflineTasks(tmp_path / 'offline.json')
    local.refresh(client)
    projects = ProjectWorkspaceStore(tmp_path / 'projects.json', tmp_path / 'absent')
    checkpoint = projects.save([{'id': 'd' * 32, 'title': 'Quelle.md', 'body': 'Exakte Originaltextstelle', 'source': 'text'}], included['id'], 'Nächster Schritt', name='schule')
    monkeypatch.setattr(module, 'OfflineTasks', lambda: local)
    monkeypatch.setattr(module, 'FlashcardStore', lambda: SimpleNamespace(all=lambda: [
        {'question': 'Frage zum Projekt', 'answer': 'Exakte Originaltextstelle', 'source': {'document_id': 'd' * 32, 'title': 'Quelle.md', 'line': 1}},
        {'question': 'Andere private Karte', 'answer': 'Andere Quelle', 'source': {'document_id': 'e' * 32, 'title': 'Andere.md', 'line': 1}}]))
    dialog = module.ProjectExportDialog(None, 'schule', checkpoint)
    assert 'Projektaufgabe' in dialog.preview.toPlainText() and 'Anderes Projekt privat' not in dialog.preview.toPlainText()
    assert 'Frage zum Projekt' not in dialog.preview.toPlainText()
    dialog.cards.setChecked(True)
    assert 'Frage zum Projekt' in dialog.preview.toPlainText() and 'Andere private Karte' not in dialog.preview.toPlainText()
    row = next(row for row, task in enumerate(dialog.tasks) if task['id'] == included['id'])
    dialog.list.item(row).setCheckState(Qt.CheckState.Unchecked)
    assert 'Projektaufgabe' not in dialog.preview.toPlainText()
    dialog.close()


def test_syncing_another_project_replaces_ui_context_and_only_records_its_progress(qt, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QWidget, QLineEdit
    from desktop.attachment_overlay import AttachmentOverlay
    from desktop.workspace_dialog import WorkspaceDialog
    from desktop.local_main import LocalMica
    import desktop.core.workspace as workspace
    monkeypatch.setattr(workspace, 'DATA_DIR', tmp_path)
    store = workspace.ProjectWorkspaceStore()
    doc_a = {'id': 'a' * 32, 'title': 'A.md', 'body': 'Inhalt von Projekt A', 'source': 'text'}
    doc_b = {'id': 'b' * 32, 'title': 'B.md', 'body': 'Inhalt von Projekt B', 'source': 'text'}
    store.save([doc_a], None, 'Schritt A', name='a', last_step='Unverändert A', remember_progress=True)
    store.save([doc_b], None, 'Schritt B', name='b', remember_progress=True)
    parent = QWidget()
    parent._attachment_overlay, parent._input, parent._open_attachments = AttachmentOverlay(), QLineEdit(), Mock()
    parent.selected_documents = parent._attachment_overlay.snapshot
    mica = LocalMica.__new__(LocalMica)
    mica._request_lock, mica._restoring, mica._offline_start = threading.RLock(), False, True
    mica.ui = SimpleNamespace(_win=parent, remember_conversations=True, muted=True, write_log=Mock(), set_state=Mock(), show_content=Mock())
    mica.client, mica.conversation_mode = Mock(), 'personal'
    dialog = WorkspaceDialog(parent, mica._workspace_operation, [], store=store, prefer_load=True, project='a')
    dialog.run('load')
    until(qt, lambda: parent._input.text() == 'Schritt A')
    assert parent.selected_documents()[0]['id'] == doc_a['id']
    dialog.name.setCurrentText('b')
    dialog.run('sync')
    until(qt, lambda: parent._input.text() == 'Schritt B')
    assert parent.selected_documents() == [doc_b] and mica._active_project == 'b'
    assert not mica._offline_workspace and not mica._offline_start
    mica.client.turn.return_value = {'state': 'completed', 'reply': 'Erklärung zu B'}
    mica.handle_text('Erkläre den Inhalt')
    mica.client.select_documents.assert_called_once_with([doc_b])
    assert 'Erkläre den Inhalt' in store.load('b')['last_step']
    assert store.load('a')['last_step'] == 'Unverändert A'
    dialog.close()
    parent._attachment_overlay.close()
    parent.close()


def test_project_dialog_cannot_close_mid_save_and_resume_ui_before_completion(qt, tmp_path):
    from desktop.workspace_dialog import WorkspaceDialog
    store = ProjectWorkspaceStore(tmp_path / 'projects.json', tmp_path / 'absent')
    released = threading.Event()
    def operation(action, payload, store):
        assert released.wait(3)
        return store.save(payload['documents'], None, payload['next_step'], name=payload['project'])
    dialog = WorkspaceDialog(None, operation, [], store=store)
    dialog.show()
    dialog.run('save')
    assert dialog.busy
    dialog.reject()
    dialog.close()
    qt.processEvents()
    assert dialog.isVisible() and dialog.busy
    released.set()
    until(qt, lambda: not dialog.busy)
    dialog.close()
    assert not dialog.isVisible() and store.load()['next_step'] == ''
