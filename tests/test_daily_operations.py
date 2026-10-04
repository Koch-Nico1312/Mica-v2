from __future__ import annotations

import importlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.services.common.execution_history import ExecutionHistory
from backend.services.common.idempotency import IdempotencyConflict
from backend.services.common.diagnostics import _probe, SERVICES


def test_host_file_undo_survives_real_runner_processes_and_rejects_later_edits(tmp_path, monkeypatch):
    import json
    import subprocess
    import sys
    from backend.windows_host_agent.history import list_receipts
    monkeypatch.setenv('MICA_WINDOWS_ENABLED_ACTIONS', 'file_controller')
    monkeypatch.setenv('MICA_WINDOWS_ALLOWED_ROOTS', str(tmp_path))
    target = tmp_path / 'note.txt'
    target.write_bytes(b'original')
    def run(params):
        response = subprocess.run([sys.executable, '-m', 'backend.windows_host_agent.runner'],
                                  input=json.dumps({'action': 'file_controller', 'params': params}),
                                  text=True, encoding='utf-8', capture_output=True, timeout=15)
        return json.loads(response.stdout)
    written = run({'action': 'write', 'path': str(target), 'content': 'changed'})
    assert written['ok'], written
    identifier = written['result']['change_id']
    assert list_receipts()[0]['undo_available']
    target.write_text('later user edit')
    rejected = run({'action': 'undo_change', 'change_id': identifier})
    assert not rejected['ok'] and target.read_text() == 'later user edit'
    target.write_text('changed')
    restored = run({'action': 'undo_change', 'change_id': identifier})
    assert restored['ok'] and target.read_bytes() == b'original'
    assert not run({'action': 'undo_change', 'change_id': identifier})['ok']


def test_host_undo_preserves_move_copy_and_does_not_delete_new_folder_contents(tmp_path, monkeypatch):
    from backend.windows_host_agent import history
    monkeypatch.setenv('MICA_WINDOWS_ALLOWED_ROOTS', str(tmp_path))
    source, destination = tmp_path / 'source', tmp_path / 'dest'
    source.write_bytes(b'exact bytes')
    receipt = history.prepare('file_controller', {'action': 'move', 'path': str(source), 'destination': str(destination)})
    source.rename(destination)
    identifier = history.finish(receipt, True)
    history.undo(identifier)
    assert source.read_bytes() == b'exact bytes' and not destination.exists()
    receipt = history.prepare('file_controller', {'action': 'create_folder', 'path': str(destination)})
    destination.mkdir()
    identifier = history.finish(receipt, True)
    (destination / 'user-file').write_text('keep')
    with pytest.raises(ValueError, match='inzwischen'):
        history.undo(identifier)
    assert (destination / 'user-file').read_text() == 'keep'


def test_host_undo_rechecks_current_path_allowlist(tmp_path, monkeypatch):
    from backend.windows_host_agent import history
    monkeypatch.setenv('MICA_WINDOWS_ALLOWED_ROOTS', str(tmp_path))
    path = tmp_path / 'created'
    receipt = history.prepare('file_controller', {'action': 'create_file', 'path': str(path)})
    path.write_text('new')
    identifier = history.finish(receipt, True)
    monkeypatch.setenv('MICA_WINDOWS_ALLOWED_ROOTS', str(tmp_path / 'other'))
    with pytest.raises(ValueError, match='außerhalb'):
        history.undo(identifier)
    assert path.read_text() == 'new'


def test_host_move_undo_never_removes_destination_when_original_cannot_restore(tmp_path, monkeypatch):
    from backend.windows_host_agent import history
    monkeypatch.setenv('MICA_WINDOWS_ALLOWED_ROOTS', str(tmp_path))
    directory = tmp_path / 'original'
    directory.mkdir()
    source, destination = directory / 'file', tmp_path / 'moved'
    source.write_bytes(b'only copy')
    receipt = history.prepare('file_controller', {'action': 'move', 'path': str(source), 'destination': str(destination)})
    source.rename(destination)
    identifier = history.finish(receipt, True)
    directory.rmdir()
    with pytest.raises(ValueError, match='Verzeichnis fehlt'):
        history.undo(identifier)
    assert destination.read_bytes() == b'only copy'
    directory.mkdir()
    with patch.object(history, '_restore_file', side_effect=OSError('disk full')), pytest.raises(OSError):
        history.undo(identifier)
    assert destination.read_bytes() == b'only copy'


def test_host_write_undo_uses_atomic_replacement_on_io_failure(tmp_path, monkeypatch):
    from backend.windows_host_agent import history
    monkeypatch.setenv('MICA_WINDOWS_ALLOWED_ROOTS', str(tmp_path))
    path = tmp_path / 'edited'
    path.write_bytes(b'old')
    receipt = history.prepare('file_controller', {'action': 'write', 'path': str(path)})
    path.write_bytes(b'new')
    identifier = history.finish(receipt, True)
    with patch.object(history.os, 'replace', side_effect=OSError('cannot replace')), pytest.raises(OSError):
        history.undo(identifier)
    assert path.read_bytes() == b'new'
    assert not list(tmp_path.glob('.mica-undo-*.tmp'))


def test_host_history_closes_database_and_reports_adapter_failure(tmp_path, monkeypatch):
    import json
    import subprocess
    import sys
    from backend.windows_host_agent import history
    monkeypatch.setenv('MICA_WINDOWS_ALLOWED_ROOTS', str(tmp_path))
    monkeypatch.setenv('MICA_WINDOWS_ENABLED_ACTIONS', 'file_controller')
    result = subprocess.run([sys.executable, '-m', 'backend.windows_host_agent.runner'],
                            input=json.dumps({'action': 'file_controller', 'params': {
                                'action': 'move', 'path': str(tmp_path / 'missing'), 'destination': str(tmp_path / 'dst')}}),
                            encoding='utf-8', capture_output=True, timeout=15)
    assert not json.loads(result.stdout)['ok'] and result.returncode != 0
    item = history.list_receipts()[0]
    assert item['status'] == 'uncertain' and not item['undo_available']
    database = history._path()
    database.unlink()  # Windows rejects this if any history connection is open.
    assert not database.exists()


def test_host_undo_guard_excludes_another_runner_file_change(tmp_path, monkeypatch):
    import json
    import subprocess
    import sys
    from backend.windows_host_agent import history
    monkeypatch.setenv('MICA_WINDOWS_ALLOWED_ROOTS', str(tmp_path))
    monkeypatch.setenv('MICA_WINDOWS_ENABLED_ACTIONS', 'file_controller')
    target = tmp_path / 'file'
    target.write_bytes(b'old')
    receipt = history.prepare('file_controller', {'action': 'write', 'path': str(target)})
    target.write_bytes(b'new')
    identifier = history.finish(receipt, True)
    pending = []
    original_restore = history._restore_file
    def restore_with_competing_process(*args):
        process = subprocess.Popen([sys.executable, '-m', 'backend.windows_host_agent.runner'],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   encoding='utf-8')
        process.stdin.write(json.dumps({'action': 'file_controller', 'params': {
            'action': 'write', 'path': str(target), 'content': 'later edit'}}))
        process.stdin.close()
        pending.append(process)
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=.3)
        original_restore(*args)
    with patch.object(history, '_restore_file', side_effect=restore_with_competing_process):
        history.undo(identifier)
    for process in pending:
        assert process.wait(timeout=10) == 0, process.stderr.read()
        process.stdout.close()
        process.stderr.close()
    assert target.read_bytes() == b'later edit'


def test_concurrent_execution_journal_initialization_migrates_once(tmp_path):
    path = tmp_path / 'parallel.sqlite3'
    with ThreadPoolExecutor(max_workers=8) as pool:
        stores = list(pool.map(lambda _: ExecutionHistory(path), range(16)))
    assert len(stores) == 16
    stores[0].begin('parallel-migration', 'task', 'file_controller', {'action': 'info'})
    assert stores[-1].list()[0]['params'] == {'action': 'info'}


def test_backup_audit_snapshot_stays_valid_when_emergency_appends_during_archive(daily_api):
    import tempfile
    from backend import backup_restore
    module, _ = daily_api
    module.audit.append('before.snapshot', {})
    export = backup_restore._state_export
    def append_during_export(root):
        module.audit.append('emergency.concurrent', {})
        return export(root)
    with tempfile.TemporaryDirectory() as target, patch.object(backup_restore, '_state_export', side_effect=append_during_export):
        archive, _ = backup_restore.create_backup(module.brain.root.parent, Path(target))
        assert backup_restore.verify_restore(archive)['passed']
    assert module.audit.verify()


def test_live_restore_preserves_existing_plan_children_as_one_revision(daily_api, monkeypatch):
    import tempfile
    from backend import backup_restore
    module, _ = daily_api
    monkeypatch.setenv('MICA_SERVER_AGENT_TARGETS', 'first,removed')
    steps = [{'action': 'system.status', 'params': {'target_id': 'first'}},
             {'action': 'system.status', 'params': {'target_id': 'removed'}}]
    plan = module.phase4_store.create_plan('Plan korrigieren', steps)
    module.audit.append('test.fixture', {})
    with tempfile.TemporaryDirectory() as target:
        archive, _ = backup_restore.create_backup(module.brain.root.parent, Path(target))
        corrected = module.phase4_store.patch_plan(plan['id'], {'steps': [steps[0]]})
        original_ids = [step['id'] for step in corrected['steps']]
        backup_restore.restore_live(archive, module.brain.root.parent)
    restored = module.phase4_store.get_plan(plan['id'])
    assert restored['revision'] == corrected['revision'] and restored['plan_hash'] == corrected['plan_hash']
    assert [step['id'] for step in restored['steps']] == original_ids
    assert all(step['params']['target_id'] != 'removed' for step in restored['steps'])


@pytest.mark.parametrize('legacy_status', ['blocked', 'pending', 'running'])
def test_legacy_backup_keeps_unknown_dispatches_blocked(daily_api, tmp_path, monkeypatch, legacy_status):
    import json
    import sqlite3
    from backend import backup_restore
    from backend.services.common.phase4 import Phase4Store
    module, _ = daily_api
    monkeypatch.setenv('MICA_SERVER_AGENT_TARGETS', 'test')
    plan = module.phase4_store.create_plan('Legacy uncertainty', [{'action': 'system.status', 'params': {'target_id': 'test'}}])
    with sqlite3.connect(module.phase4_store.path) as conn:
        conn.execute("UPDATE agent_plans SET status='paused',tool_calls=1,last_error='uncertain_outcome' WHERE id=?", (plan['id'],))
        conn.execute('UPDATE agent_plan_steps SET status=? WHERE plan_id=?', (legacy_status, plan['id']))
    payload = json.loads(backup_restore._state_export(module.brain.root.parent))
    for row in payload['tables']['agent_plan_steps']:
        row.pop('dispatch_started_at', None)
    staged = tmp_path / 'staged'
    (staged / 'state').mkdir(parents=True)
    (staged / 'state' / 'phase4.json').write_text(json.dumps(payload), encoding='utf-8')
    backup_restore._rebuild_state_export(staged)
    live = tmp_path / 'live'
    live.mkdir()
    backup_restore._apply_live_state(staged, live)
    for database in [staged / 'state' / 'scheduler.sqlite3', live / 'scheduler.sqlite3']:
        store = Phase4Store(database)
        step = store.get_plan(plan['id'])['steps'][0]
        assert step['dispatch_started_at']
        assert step['status'] in {'blocked', 'running'}
        with pytest.raises(ValueError, match='reconcile'):
            store.patch_plan(plan['id'], {'budget': plan['budget']})


def test_legacy_journal_migration_blocks_uncertain_pending_steps(tmp_path, monkeypatch):
    import sqlite3
    from backend.services.common.phase4 import Phase4Store
    monkeypatch.setenv('MICA_SERVER_AGENT_TARGETS', 'test')
    database = tmp_path / 'old.sqlite3'
    store = Phase4Store(database)
    plan = store.create_plan('Upgrade uncertainty', [{'action': 'system.status', 'params': {'target_id': 'test'}}])
    with sqlite3.connect(database) as conn:
        conn.execute('ALTER TABLE agent_plan_steps DROP COLUMN dispatch_started_at')
        conn.execute("UPDATE agent_plans SET status='paused',tool_calls=1,last_error='uncertain_outcome'")
    upgraded = Phase4Store(database)
    step = upgraded.get_plan(plan['id'])['steps'][0]
    assert step['status'] == 'blocked' and step['dispatch_started_at']
    with pytest.raises(ValueError, match='reconcile'):
        upgraded.patch_plan(plan['id'], {'budget': plan['budget']})


def test_voice_presence_does_not_write_during_exclusive_maintenance(daily_api):
    from backend.services.common.storage_lock import StorageLease
    module, _ = daily_api
    before = module.phase4_store.presence()['state']
    with StorageLease(module.brain.root.parent, exclusive=True):
        module._voice_presence('speaking')
    assert module.phase4_store.presence()['state'] == before


def test_emergency_stop_cannot_clear_under_restore_lock_or_incomplete_marker(daily_api):
    from backend.services.common.storage_lock import StorageLease
    module, client = daily_api
    module.policy.set_emergency_stop(True)
    client.post('/v1/auth/approval-session', json={'secret': 'daily-test-secret'})
    headers = {'X-Mica-Approval-Intent': 'confirm'}
    with patch.object(module.httpx, 'post') as remote:
        with StorageLease(module.brain.root.parent, exclusive=True):
            assert client.post('/v1/emergency-stop', json={'active': False}, headers=headers).status_code == 409
        marker = module.brain.root.parent / '.restore-incomplete'
        marker.write_text('a' * 32)
        assert client.post('/v1/emergency-stop', json={'active': False}, headers=headers).status_code == 409
        remote.assert_not_called()
    assert module.policy.is_emergency_stopped()


def test_default_file_path_and_name_use_identical_scope_and_undo_target(tmp_path, monkeypatch):
    import importlib
    from desktop.core.action_adapters import execute, execution_availability
    from backend.windows_host_agent import history
    module = importlib.import_module('desktop.actions.file_controller')
    desktop = tmp_path / 'Desktop'
    desktop.mkdir()
    monkeypatch.setattr(module, '_get_desktop', lambda: desktop)
    from mica_shared import file_paths
    original_directory = file_paths.user_directory
    monkeypatch.setattr(file_paths, 'user_directory', lambda name: desktop if name == 'Desktop' else original_directory(name))
    monkeypatch.setenv('MICA_WINDOWS_ENABLED_ACTIONS', 'file_controller')
    monkeypatch.setenv('MICA_WINDOWS_ALLOWED_ROOTS', str(desktop))
    params = {'action': 'create_file', 'name': 'note.txt', 'content': 'actual content'}
    assert execution_availability('file_controller', params) == (True, 'available')
    receipt = history.prepare('file_controller', params)
    execute('file_controller', params)
    identifier = history.finish(receipt, True)
    item = history.list_receipts()[0]
    assert item['paths'] == [str(desktop / 'note.txt')] and item['undo_available']
    history.undo(identifier)
    assert not (desktop / 'note.txt').exists()
    monkeypatch.setenv('MICA_WINDOWS_ALLOWED_ROOTS', str(tmp_path / 'other'))
    assert execution_availability('file_controller', params) == (False, 'local_path_not_allowlisted')


def test_restart_keeps_completed_result_and_unknown_execution_claimed(tmp_path):
    store = ExecutionHistory(tmp_path / 'state.sqlite3')
    store.begin('done-key', 'task', 'file_controller', {'path': 'a'})
    store.finish('done-key', 'succeeded', {'status': 'succeeded', 'output': 'created'})
    store.begin('lost-key', 'other', 'file_controller', {'path': 'b'})
    restarted = ExecutionHistory(store.path)
    assert restarted.begin('done-key', 'task', 'file_controller', {'path': 'a'})['output'] == 'created'
    with pytest.raises(IdempotencyConflict):
        restarted.begin('lost-key', 'other', 'file_controller', {'path': 'b'})
    assert any(item['needs_reconciliation'] for item in restarted.list())


def test_parallel_requests_have_one_dispatch_claim(tmp_path):
    store = ExecutionHistory(tmp_path / 'state.sqlite3')
    barrier = threading.Barrier(6)
    def claim(_):
        barrier.wait()
        try:
            store.begin('same-key', 'task', 'file_controller', {})
            return True
        except IdempotencyConflict:
            return False
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert sum(pool.map(claim, range(6))) == 1


def test_only_known_rejections_retry_and_changed_parameters_never_do(tmp_path):
    store = ExecutionHistory(tmp_path / 'state.sqlite3')
    store.begin('retry-key', 'task', 'file_controller', {'path': 'a'})
    store.finish('retry-key', 'approval_required')
    with pytest.raises(IdempotencyConflict):
        store.begin('retry-key', 'task', 'file_controller', {'path': 'b'})
    assert store.begin('retry-key', 'task', 'file_controller', {'path': 'a'}) is None
    store.finish('retry-key', 'uncertain')
    with pytest.raises(IdempotencyConflict):
        store.begin('retry-key', 'task', 'file_controller', {'path': 'a'})


@pytest.fixture
def daily_api(tmp_path, monkeypatch):
    names = {'BRAIN_DIR': 'brain', 'INDEX_PATH': 'index/brain.sqlite3', 'AUDIT_PATH': 'audit/events.jsonl',
             'APPROVAL_DB': 'approvals.sqlite3', 'SCHEDULE_DB': 'scheduler.sqlite3',
             'MICA_STATE_DB': 'scheduler.sqlite3', 'IMPROVEMENT_DB': 'improvements.sqlite3',
             'CONNECTOR_DB': 'connectors.sqlite3', 'MICA_DREAM_DB': 'dream.sqlite3',
             'PROFILE_PATH': 'profile.json', 'LEARNING_DOMAINS_PATH': 'learning/domains.json'}
    for key, path in names.items():
        monkeypatch.setenv(key, str(tmp_path / path))
    monkeypatch.setenv('MICA_DREAM_RSI_ENABLED', '0')
    monkeypatch.setenv('MICA_APPROVAL_SECRET', 'daily-test-secret')
    monkeypatch.setenv('MICA_PROFILE_PATH', str(tmp_path / 'profile.json'))
    module = importlib.import_module('backend.services.api.app').create_app().state.runtime
    yield module, TestClient(module.app, headers={"X-Mica-API-Token": "mica-test-api-token-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"})


def test_api_cached_success_and_timeout_do_not_dispatch_twice(daily_api):
    module, client = daily_api
    payload = {'task_id': 'a' * 32, 'action': 'file_controller', 'params': {}}
    result = {'task_id': 'a' * 32, 'action': 'file_controller', 'status': 'succeeded', 'output': 'done'}
    with patch.object(module, '_dispatch_task', return_value=result) as dispatch:
        assert client.post('/v1/tasks/execute', json=payload).status_code == 200
        assert client.post('/v1/tasks/execute', json=payload).json() == result
        assert dispatch.call_count == 1
    payload['task_id'] = 'b' * 32
    with patch.object(module, '_dispatch_task', side_effect=HTTPException(503, 'timeout')) as dispatch:
        assert client.post('/v1/tasks/execute', json=payload).status_code == 503
        assert client.post('/v1/tasks/execute', json=payload).status_code == 409
        assert dispatch.call_count == 1
    activity = client.get('/v1/tasks/activity').json()
    assert activity['executions'][0]['status'] == 'uncertain'
    assert 'plans' in activity and 'tasks' in activity


def test_api_stable_execution_key_alone_keeps_generated_task_identity(daily_api):
    module, client = daily_api
    payload = {'idempotency_key': 'client-provided-key', 'action': 'file_controller', 'params': {'action': 'info'}}
    def result(request):
        return {'task_id': request.task_id, 'action': request.action, 'status': 'succeeded', 'output': 'done'}
    with patch.object(module, '_dispatch_task', side_effect=result) as dispatch:
        first = client.post('/v1/tasks/execute', json=payload)
        second = client.post('/v1/tasks/execute', json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() and dispatch.call_count == 1
    payload['task_id'] = 'a' * 32
    assert client.post('/v1/tasks/execute', json=payload).status_code == 409


def test_resume_after_restart_uses_saved_exact_identity_and_never_replays_uncertain(daily_api):
    module, client = daily_api
    key, task = 'restart-retry', 'a' * 32
    original = ExecutionHistory(module.execution_history.path)
    original.begin(key, task, 'file_controller', {'action': 'create_file', 'path': 'original'})
    original.finish(key, 'not_dispatched')
    module.execution_history = ExecutionHistory(original.path)
    assert client.post(f'/v1/tasks/executions/{key}/resume', json={}).status_code == 401
    client.post('/v1/auth/approval-session', json={'secret': 'daily-test-secret'})
    result = {'task_id': task, 'action': 'file_controller', 'status': 'succeeded', 'output': 'done'}
    with patch.object(module, '_dispatch_task', return_value=result) as dispatch:
        response = client.post(f'/v1/tasks/executions/{key}/resume', json={}, headers={'X-Mica-Approval-Intent': 'confirm'})
        assert response.status_code == 200, response.text
        request = dispatch.call_args.args[0]
        assert request.task_id == task and request.idempotency_key == key and request.params['path'] == 'original'
        assert client.post(f'/v1/tasks/executions/{key}/resume', json={}, headers={'X-Mica-Approval-Intent': 'confirm'}).status_code == 409
        assert dispatch.call_count == 1
    module.execution_history.begin('unknown-retry', 'b' * 32, 'file_controller', {})
    module.execution_history.finish('unknown-retry', 'uncertain')
    with patch.object(module, '_dispatch_task') as dispatch:
        assert client.post('/v1/tasks/executions/unknown-retry/resume', json={}, headers={'X-Mica-Approval-Intent': 'confirm'}).status_code == 409
        dispatch.assert_not_called()


def test_diagnostics_never_probe_cloud_addresses(monkeypatch):
    monkeypatch.setenv('STT_URL', 'https://example.com')
    with patch('backend.services.common.diagnostics.httpx.Client') as transport:
        result = _probe(SERVICES[1])
    assert result['status'] == 'blocked'
    transport.assert_not_called()


def test_diagnostics_model_missing_has_recovery_instruction():
    response = Mock()
    response.json.return_value = {'status': 'model-missing'}
    with patch('backend.services.common.diagnostics.httpx.Client') as transport:
        transport.return_value.__enter__.return_value.get.return_value = response
        result = _probe(SERVICES[1])
    assert result['status'] == 'blocked'
    assert 'Modell' in result['remedy']


def test_control_center_renders_backend_tasks_and_keeps_unknown_execution_blocked():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication
    from desktop.control_center import ControlCenter
    app = QApplication.instance() or QApplication([])
    view = ControlCenter()
    view._received('activity', {'plans': [], 'tasks': [], 'executions': [{
        'key': 'lost-key', 'action': 'file_controller', 'status': 'uncertain',
        'needs_reconciliation': True, 'detail': 'Verbindung unterbrochen'}]}, '')
    view.table.selectRow(0)
    assert 'tatsächliches Ergebnis' in view.detail.toPlainText()
    with patch.object(view, '_run') as run:
        view.resume()
    run.assert_not_called()
    view.deleteLater()
    app.processEvents()


def test_control_center_backup_flow_suspends_and_releases_ui(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from desktop.control_center import ControlCenter
    app = QApplication.instance() or QApplication([])
    view = ControlCenter()
    archive = tmp_path / 'recovery.tar.gz'
    archive.write_bytes(b'test-archive')
    events = []
    view.restore_busy.connect(events.append)
    client = Mock()
    client.restore_backup.return_value = {'recovery_id': 'a' * 32}
    def perform(kind, operation):
        view._received(kind, operation(client), '')
    with (patch('desktop.control_center.QFileDialog.getOpenFileName', return_value=(str(archive), '')),
         patch('desktop.control_center.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes),
         patch('desktop.core.update_recovery.inspect_backup', return_value={'passed': True}),
         patch.object(view, '_run', side_effect=perform)):
        view.restore_backup()
    assert events == [True, False]
    client.restore_backup.assert_called_once_with(b'test-archive')
    assert 'Not-Aus' in view.backup_report.toPlainText()
    view._received('backup_restored', None, 'test failure')
    assert events[-1] is False and not view._busy
    view.deleteLater()
    app.processEvents()


def test_control_center_host_undo_uses_bound_approval_and_stable_dispatch_key():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from desktop.control_center import ControlCenter
    app = QApplication.instance() or QApplication([])
    view = ControlCenter()
    identifier = 'b' * 32
    view.host_change.addItem('file', {'id': identifier, 'operation': 'write', 'paths': ['file'], 'undo_available': True})
    client = Mock()
    client.plan.return_value = {'plan': {'task_id': 'c' * 32, 'permission': {'allowed': False, 'approval_id': 'd' * 32}}}
    with patch('desktop.control_center.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), patch.object(view, '_run') as run:
        view.undo_host_change()
        run.call_args.args[1](client)
    client.approve.assert_called_once_with('d' * 32)
    client.execute.assert_called_once_with(identifier, 'file_controller', {'action': 'undo_change', 'change_id': identifier},
                                          approval_id='d' * 32, idempotency_key='undo:' + identifier)
    view.deleteLater()
    app.processEvents()


def test_memory_edits_require_login_and_use_backend_truth(daily_api):
    module, client = daily_api
    payload = {'title': 'Lieblingsfarbe', 'body': 'Blau'}
    assert client.post('/v1/memory/items', json=payload).status_code == 401
    assert client.post('/v1/auth/approval-session', json={'secret': 'daily-test-secret'}).status_code == 200
    headers = {'X-Mica-Approval-Intent': 'confirm'}
    response = client.post('/v1/memory/items', json=payload, headers=headers)
    assert response.status_code == 200
    doc_id = response.json()['document']['id']
    assert client.get('/v1/memory/items').json()['items'][0]['source'] == 'desktop_user'
    assert client.patch(f'/v1/brain/documents/{doc_id}', json={'body': 'Grün'}, headers=headers).status_code == 200
    assert module.brain.documents()[0]['body'] == 'Grün'
    assert client.delete(f'/v1/brain/documents/{doc_id}', headers=headers).status_code == 200
    assert module.brain.documents() == []


def test_private_text_does_not_write_conversations_or_twin(daily_api):
    module, client = daily_api
    with patch.object(module, '_local_completion', return_value='Antwort'), \
         patch.object(module, 'configured_cloud_provider', return_value=None), \
         patch.object(module.phase4_store, 'observe_twin') as twin:
        response = client.post('/v1/turns', json={'message': 'Nur für dieses Gespräch', 'remember': False})
    assert response.status_code == 200
    assert not any(doc['kind'] == 'conversations' for doc in module.brain.documents())
    twin.assert_not_called()
    with patch.object(module, '_local_completion', return_value='Antwort'), \
         patch.object(module, 'configured_cloud_provider', return_value=None):
        assert client.post('/v1/turns', json={'message': 'Darf gespeichert werden'}).status_code == 200
    assert any(doc['kind'] == 'conversations' for doc in module.brain.documents())


def test_action_history_survives_session_but_does_not_promise_stale_undo():
    from desktop.core import undo
    undo.clear()
    changes = []
    undo.push_undo('Datei A erstellt', lambda: changes.append('A') or 'restored')
    first = undo.history_entries()[0]
    undo.push_undo('Einstellung B geändert', lambda: changes.append('B') or 'restored')
    assert 'Review' in undo.undo_last(expected_id=first['id'])
    assert not changes
    second = undo.history_entries()[0]
    assert 'Undone' in undo.undo_last(expected_id=second['id'])
    assert changes == ['B']
    undo.clear()
    history = undo.history_entries()
    assert len(history) == 2
    assert not any(item['undo_available'] for item in history)
    assert history[0]['status'] == 'undone'


def test_backend_backup_restore_roundtrip_preserves_newer_dispatch_claim(daily_api):
    module, client = daily_api
    from backend.services.common.profile import PersonalProfileUpdate
    document = module.brain.write('memory', 'Lieblingsfarbe', 'Blau')
    task = module.task_store.create_task('Aufgabe vor Backup')
    module.profile_store.update(PersonalProfileUpdate(preferred_address='Testperson'))
    headers = {'X-Mica-Approval-Intent': 'confirm'}
    assert client.get('/v1/backups/export', headers=headers).status_code == 401
    assert client.post('/v1/auth/approval-session', json={'secret': 'daily-test-secret'}).status_code == 200
    archive = client.get('/v1/backups/export', headers=headers)
    assert archive.status_code == 200
    module.brain.update_document(document['id'], 'Grün')
    module.task_store.update_task(task['id'], {'title': 'Änderung nach Backup'})
    module.execution_history.begin('sticky-key', 'execution-task', 'file_controller', {})
    module.execution_history.finish('sticky-key', 'succeeded', {'status': 'succeeded', 'output': 'already changed'})
    response = client.post('/v1/backups/restore', headers=headers, content=archive.content)
    assert response.status_code == 200, response.text
    assert response.json()['restored']
    assert module.brain.documents()[0]['body'] == 'Blau'
    assert module.task_store.get_task(task['id'])['title'] == 'Aufgabe vor Backup'
    assert module.profile_store.read().preferred_address == 'Testperson'
    assert module.policy.is_emergency_stopped()
    assert module.execution_history.begin('sticky-key', 'execution-task', 'file_controller', {})['output'] == 'already changed'
    recovery = client.get('/v1/backups/recovery/' + response.json()['recovery_id'], headers=headers)
    assert recovery.status_code == 200
    assert module.audit.verify()


def test_failed_restore_leaves_writer_gate_and_recovery_then_can_recover(daily_api):
    module, client = daily_api
    module.brain.write('memory', 'Information', 'Vorher')
    headers = {'X-Mica-Approval-Intent': 'confirm'}
    client.post('/v1/auth/approval-session', json={'secret': 'daily-test-secret'})
    archive = client.get('/v1/backups/export', headers=headers).content
    with patch('backend.backup_restore._apply_live_state', side_effect=OSError('write failure')):
        response = client.post('/v1/backups/restore', headers=headers, content=archive)
    assert response.status_code == 409
    status = client.get('/v1/backups/status').json()
    assert status['maintenance']
    assert client.get('/v1/memory/items').status_code == 503
    recovery = client.get('/v1/backups/recovery/' + status['recovery_id'], headers=headers).content
    assert client.post('/v1/backups/restore', headers=headers, content=recovery).status_code == 200
    assert not client.get('/v1/backups/status').json()['maintenance']
    assert client.get('/v1/memory/items').status_code == 200


def test_corrupt_restore_does_not_touch_live_truth(daily_api):
    module, client = daily_api
    module.brain.write('memory', 'Information', 'Unverändert')
    client.post('/v1/auth/approval-session', json={'secret': 'daily-test-secret'})
    response = client.post('/v1/backups/restore', content=b'not a gzip archive',
                           headers={'X-Mica-Approval-Intent': 'confirm'})
    assert response.status_code == 409
    assert module.brain.documents()[0]['body'] == 'Unverändert'
    assert not (module.brain.root.parent / '.restore-incomplete').exists()


def test_desktop_bundle_roundtrip_keeps_credentials_out_and_preserves_local_keys(tmp_path):
    import json
    from desktop.core.desktop_backup import save_bundle, read_bundle, restore_desktop
    root = tmp_path / 'project'
    config = root / 'desktop/config/api_keys.json'
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({'assistant_name': 'Mica', 'api_key': 'test-local-key'}))
    memory = root / 'desktop/memory/long_term.json'
    memory.parent.mkdir(parents=True)
    memory.write_text(json.dumps({'notes': {'color': 'Blau'}}))
    (root / '.env').write_text('MICA_WAKE_WORD_ENABLED=0\nSECRET=private\n')
    bundle = tmp_path / 'backup.zip'
    save_bundle(bundle, root, b'backend archive')
    desktop, archive = read_bundle(bundle)
    assert archive == b'backend archive'
    assert 'test-local-key' not in json.dumps(desktop)
    assert 'private' not in json.dumps(desktop)
    memory.write_text('{}')
    config.write_text(json.dumps({'assistant_name': 'Changed', 'api_key': 'current-key'}))
    result = restore_desktop(root, desktop)
    assert json.loads(memory.read_text())['notes']['color'] == 'Blau'
    assert json.loads(config.read_text())['api_key'] == 'current-key'
    assert json.loads(config.read_text())['assistant_name'] == 'Mica'
    assert Path(result['recovery']).is_file()


def test_desktop_partial_write_rolls_back(tmp_path):
    import json
    from desktop.core import desktop_backup
    root = tmp_path / 'project'
    target = root / 'desktop/memory/long_term.json'
    target.parent.mkdir(parents=True)
    target.write_text('{"original":true}')
    backup = {'schema': 1, 'files': {'desktop/memory/long_term.json': {'restored': True}},
              'ui': {}, 'features': {}}
    original = desktop_backup._write_json
    def fail_config(path, value):
        if path.name == 'api_keys.json':
            raise OSError('disk full')
        original(path, value)
    with patch.object(desktop_backup, '_write_json', side_effect=fail_config), pytest.raises(OSError):
        desktop_backup.restore_desktop(root, backup)
    assert json.loads(target.read_text()) == {'original': True}


def test_storage_lock_allows_readers_but_blocks_restore_across_processes(tmp_path):
    import subprocess
    import sys
    from backend.services.common.storage_lock import StorageLease, StorageBusy
    with StorageLease(tmp_path):
        with StorageLease(tmp_path):
            with pytest.raises(StorageBusy):
                StorageLease(tmp_path, exclusive=True, timeout=0.1)
        code = "from backend.services.common.storage_lock import StorageLease,StorageBusy;import sys\ntry:\n StorageLease(__import__('pathlib').Path(sys.argv[1]),exclusive=True,timeout=.1)\nexcept StorageBusy:\n print('blocked')"
        env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'backend')}
        result = subprocess.run([sys.executable, '-c', code, str(tmp_path)], env=env, text=True, capture_output=True, timeout=5)
        assert result.returncode == 0 and result.stdout.strip() == 'blocked', result.stderr
    with StorageLease(tmp_path, exclusive=True, timeout=0.1):
        pass


def test_reconciliation_uses_exact_broker_result_and_never_redispatches(daily_api):
    module, client = daily_api
    key, task = 'uncertain-key', 'a' * 32
    module.execution_history.begin(key, task, 'file_controller', {'path': 'a'})
    module.execution_history.finish(key, 'uncertain')
    client.post('/v1/auth/approval-session', json={'secret': 'daily-test-secret'})
    headers = {'X-Mica-Approval-Intent': 'confirm'}
    result = {'status': 'completed', 'result': {'dispatched': True, 'result': {'output': 'done'}},
              'fingerprint': 'wrong'}
    with patch.object(module, '_broker_execution', return_value=result), patch.object(module, '_dispatch_task') as dispatch:
        response = client.post(f'/v1/tasks/executions/{key}/reconcile', headers=headers)
        assert not response.json()['resolved']
        result['fingerprint'] = module.IdempotencyStore.fingerprint('file_controller', {'path': 'a'})
        response = client.post(f'/v1/tasks/executions/{key}/reconcile', headers=headers)
        assert response.json()['resolved']
        dispatch.assert_not_called()
    assert module.execution_history.begin(key, task, 'file_controller', {'path': 'a'})['output'] == 'done'


def test_plan_recovery_skips_confirmed_completed_step_then_resumes_remaining(daily_api, monkeypatch):
    import sqlite3
    module, client = daily_api
    monkeypatch.setenv('MICA_PHASE4_ENABLED', '1')
    monkeypatch.setenv('MICA_SELF_PLANNING_ENABLED', '1')
    monkeypatch.setenv('MICA_SERVER_AGENT_TARGETS', 'first,second')
    plan = module.phase4_store.create_plan('Zwei Leseaktionen', [
        {'action': 'system.status', 'params': {'target_id': 'first'}},
        {'action': 'system.status', 'params': {'target_id': 'second'}},
    ])
    module.phase4_store.dry_run(plan['id'], module.policy)
    first = plan['steps'][0]
    with sqlite3.connect(module.phase4_store.path) as connection:
        connection.execute("UPDATE agent_plans SET status='paused' WHERE id=?", (plan['id'],))
        connection.execute("UPDATE agent_plan_steps SET status='failed' WHERE id=?", (first['id'],))
    client.post('/v1/auth/approval-session', json={'secret': 'daily-test-secret'})
    confirmed = {'status': 'completed', 'result': {'dispatched': True, 'result': {'output': 'first done'}},
                 'fingerprint': module.IdempotencyStore.fingerprint(first['action'], first['params'])}
    with patch.object(module, '_broker_execution', return_value=confirmed):
        response = client.post(f"/v1/agent-plans/{plan['id']}/reconcile", headers={'X-Mica-Approval-Intent': 'confirm'})
    assert response.json()['resolved_steps'] == 1
    assert client.post(f"/v1/agent-plans/{plan['id']}/activate", json={}).json()['status'] == 'active'
    calls = []
    def dispatch(action, params, key, approval):
        calls.append(params['target_id'])
        return {'dispatched': True}
    module.phase4_store.run_one_step(module.policy, dispatch, module.task_store, module.audit)
    assert calls == ['second']
    assert module.phase4_store.get_plan(plan['id'])['status'] == 'completed'


def test_plan_resume_excludes_pause_time_without_resetting_consumed_budget(daily_api, monkeypatch):
    import sqlite3
    from datetime import UTC, datetime, timedelta
    module, client = daily_api
    monkeypatch.setenv('MICA_PHASE4_ENABLED', '1')
    monkeypatch.setenv('MICA_SELF_PLANNING_ENABLED', '1')
    monkeypatch.setenv('MICA_SERVER_AGENT_TARGETS', 'test')
    plan = module.phase4_store.create_plan('Nach Pause fortsetzen', [{'action': 'system.status', 'params': {'target_id': 'test'}}])
    module.phase4_store.dry_run(plan['id'], module.policy)
    yesterday = datetime.now(UTC) - timedelta(days=1)
    with sqlite3.connect(module.phase4_store.path) as conn:
        conn.execute("UPDATE agent_plans SET status='paused',started_at=?,updated_at=?,tool_calls=1 WHERE id=?",
                     ((yesterday - timedelta(seconds=20)).isoformat(), yesterday.isoformat(), plan['id']))
    resumed, decision = module.phase4_store.activate(plan['id'], module.policy)
    assert decision.allowed and resumed['tool_calls'] == 1
    consumed = datetime.now(UTC) - datetime.fromisoformat(resumed['started_at'])
    assert 19 < consumed.total_seconds() < 25
    result = module.phase4_store.run_one_step(module.policy, lambda *_: {'dispatched': True}, module.task_store, module.audit)
    assert result['status'] == 'completed'


@pytest.mark.parametrize('correct', [False, True])
def test_preview_and_correction_preserve_pause_budget(daily_api, monkeypatch, correct):
    import sqlite3
    from datetime import UTC, datetime, timedelta
    module, _ = daily_api
    monkeypatch.setenv('MICA_PHASE4_ENABLED', '1')
    monkeypatch.setenv('MICA_SELF_PLANNING_ENABLED', '1')
    monkeypatch.setenv('MICA_SERVER_AGENT_TARGETS', 'test')
    plan = module.phase4_store.create_plan('Resume preview', [{'action': 'system.status', 'params': {'target_id': 'test'}}])
    module.phase4_store.dry_run(plan['id'], module.policy)
    yesterday = datetime.now(UTC) - timedelta(days=1)
    with sqlite3.connect(module.phase4_store.path) as conn:
        conn.execute("UPDATE agent_plans SET status='paused',started_at=?,updated_at=?,pause_started_at=?,tool_calls=1 WHERE id=?",
                     ((yesterday - timedelta(seconds=10)).isoformat(), yesterday.isoformat(), yesterday.isoformat(), plan['id']))
    if correct:
        module.phase4_store.patch_plan(plan['id'], {'budget': plan['budget']})
    module.phase4_store.dry_run(plan['id'], module.policy)
    resumed, decision = module.phase4_store.activate(plan['id'], module.policy)
    assert decision.allowed and resumed['tool_calls'] == 1
    assert resumed['corrections'] == int(correct)
    assert resumed['pause_started_at'] is None
    assert 9 < (datetime.now(UTC) - datetime.fromisoformat(resumed['started_at'])).total_seconds() < 15
    result = module.phase4_store.run_one_step(module.policy, lambda *_: {'dispatched': True}, module.task_store, module.audit)
    assert result['status'] == 'completed'


def test_uncertain_plan_steps_require_reconciliation_before_edit_or_resume(daily_api, monkeypatch):
    import sqlite3
    module, _ = daily_api
    monkeypatch.setenv('MICA_PHASE4_ENABLED', '1')
    monkeypatch.setenv('MICA_SELF_PLANNING_ENABLED', '1')
    monkeypatch.setenv('MICA_SERVER_AGENT_TARGETS', 'test')
    store = module.phase4_store
    plan = store.create_plan('Dependent steps', [{'action': 'system.status', 'params': {'target_id': 'test'}}] * 2)
    store.dry_run(plan['id'], module.policy)
    store.activate(plan['id'], module.policy)
    calls = []
    def lost_response(*args):
        calls.append(args[2])
        raise TimeoutError('effect happened but response was lost')
    assert store.run_one_step(module.policy, lost_response, module.task_store, module.audit)['status'] == 'failed'
    original = store.get_plan(plan['id'])['steps'][0]
    assert original['dispatch_started_at']
    with pytest.raises(ValueError, match='reconcile'):
        store.patch_plan(plan['id'], {'budget': plan['budget']})
    store.dry_run(plan['id'], module.policy)
    with pytest.raises(ValueError, match='reconcile'):
        store.activate(plan['id'], module.policy)
    # Even inconsistent restored state cannot skip an unresolved predecessor.
    with sqlite3.connect(store.path) as conn:
        conn.execute("UPDATE agent_plans SET status='active' WHERE id=?", (plan['id'],))
    assert store.run_one_step(module.policy, lost_response, module.task_store, module.audit)['status'] == 'idle'
    assert len(calls) == 1
    assert store.reconcile_step(plan['id'], original['id'], original['idempotency_key'], {'dispatched': True}) == 1
    store.patch_plan(plan['id'], {'budget': plan['budget']})
    store.dry_run(plan['id'], module.policy)
    store.activate(plan['id'], module.policy)
    assert store.run_one_step(module.policy, lambda *args: calls.append(args[2]) or {'dispatched': True}, module.task_store, module.audit)['status'] == 'completed'
    assert len(calls) == 2 and calls[0] == original['idempotency_key']


def test_paused_inflight_step_cannot_be_corrected(daily_api, monkeypatch):
    import threading
    module, _ = daily_api
    monkeypatch.setenv('MICA_PHASE4_ENABLED', '1')
    monkeypatch.setenv('MICA_SELF_PLANNING_ENABLED', '1')
    monkeypatch.setenv('MICA_SERVER_AGENT_TARGETS', 'test')
    store = module.phase4_store
    plan = store.create_plan('In flight', [{'action': 'system.status', 'params': {'target_id': 'test'}}])
    store.dry_run(plan['id'], module.policy)
    store.activate(plan['id'], module.policy)
    entered, release = threading.Event(), threading.Event()
    def dispatch(*_):
        entered.set()
        assert release.wait(5)
        return {'dispatched': True}
    results = []
    worker = threading.Thread(target=lambda: results.append(store.run_one_step(module.policy, dispatch, module.task_store, module.audit)))
    worker.start()
    try:
        assert entered.wait(3)
        store.patch_plan(plan['id'], {'status': 'paused'})
        with pytest.raises(ValueError, match='still executing'):
            store.patch_plan(plan['id'], {'budget': plan['budget']})
        assert store.get_plan(plan['id'])['steps'][0]['id'] == plan['steps'][0]['id']
    finally:
        release.set()
        worker.join(5)
    assert results[0]['status'] == 'completed'


def test_host_history_requires_authenticated_read(daily_api):
    module, client = daily_api
    with patch.object(module.httpx, 'get') as request:
        assert client.get('/v1/actions/history').status_code == 401
        request.assert_not_called()
        client.post('/v1/auth/approval-session', json={'secret': 'daily-test-secret'})
        request.return_value.json.return_value = {'items': [], 'configured': False}
        assert client.get('/v1/actions/history').json() == {'items': [], 'configured': False}


def test_privacy_preference_persists_and_non_secret_connection_loads(tmp_path, monkeypatch):
    from desktop.core.preferences import set_remember_conversations, remember_conversations
    from desktop.core.settings_store import load_desktop_feature_environment
    set_remember_conversations(False)
    assert not remember_conversations()
    set_remember_conversations(True)
    assert remember_conversations()
    (tmp_path / '.env').write_text('MICA_CORE_URL=https://localhost:8443\nMICA_CORE_CA_FILE=C:/cert.crt\nOPENAI_API_KEY=private\n')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setenv('MICA_CORE_URL', 'https://mica.local')
    monkeypatch.setenv('MICA_CORE_CA_FILE', '')
    load_desktop_feature_environment(tmp_path)
    assert os.environ['MICA_CORE_URL'] == 'https://localhost:8443'
    assert 'OPENAI_API_KEY' not in os.environ


def test_local_client_backup_and_memory_over_real_verified_https(daily_api, tmp_path):
    import ipaddress
    import socket
    import time
    from datetime import UTC, datetime, timedelta
    import uvicorn
    crypto = pytest.importorskip('cryptography')
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from desktop.core.local_core_client import LocalCoreClient
    module, _ = daily_api
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
            .not_valid_after(datetime.now(UTC) + timedelta(hours=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),
                           x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_file, key_file = tmp_path / 'test.crt', tmp_path / 'test.key'
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    server = uvicorn.Server(uvicorn.Config(module.app, log_level='error', access_log=False,
                                          ssl_certfile=str(cert_file), ssl_keyfile=str(key_file)))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.02)
    client = LocalCoreClient(f'https://127.0.0.1:{sock.getsockname()[1]}', ca_file=cert_file)
    try:
        assert server.started
        assert client.login('daily-test-secret')['authenticated']
        item = client.remember_item('HTTPS-Test', 'Gespeichert über echten HTTPS-Transport')['document']['id']
        archive = client.download_backup()
        assert archive[:2] == b'\x1f\x8b'
        client.correct_memory(item, 'Geändert')
        result = client.restore_backup(archive)
        assert result['restored']
        assert client.memory_items()['items'][0]['body'] == 'Gespeichert über echten HTTPS-Transport'
        assert client.download_backup(result['recovery_id'])[:2] == b'\x1f\x8b'
        assert not client.backup_status()['maintenance']
    finally:
        client.session.close()
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
    assert not thread.is_alive()


def test_live_plan_worker_cannot_be_mistaken_for_interruption(daily_api, monkeypatch):
    module, _ = daily_api
    monkeypatch.setenv('MICA_PHASE4_ENABLED', '1')
    monkeypatch.setenv('MICA_SELF_PLANNING_ENABLED', '1')
    plan = module.phase4_store.create_plan('Ein Lesen', [{'action': 'system.status', 'params': {}}])
    module.phase4_store.dry_run(plan['id'], module.policy)
    module.phase4_store.activate(plan['id'], module.policy)
    started, release = threading.Event(), threading.Event()
    calls = []
    def dispatch(*_args):
        calls.append(1)
        started.set()
        release.wait(3)
        return {'dispatched': True}
    def run():
        return module.phase4_store.run_one_step(module.policy, dispatch, module.task_store, module.audit)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run)
        assert started.wait(2)
        second = pool.submit(run)
        assert second.result(timeout=2)['status'] == 'busy'
        release.set()
        assert first.result(timeout=2)['status'] == 'completed'
    assert calls == [1]
