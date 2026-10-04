"""Verify independent applications in one process, without module reloads."""
import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient

from backend.services.api.app import create_app


def test_factory_apps_keep_services_and_voice_sessions_independent(tmp_path, monkeypatch):
    monkeypatch.setenv('MICA_APPROVAL_SECRET', 'factory-test-secret')
    monkeypatch.setenv('MICA_DREAM_RSI_ENABLED', '0')
    first = create_app(data_dir=tmp_path / 'first')
    second = create_app(data_dir=tmp_path / 'second')
    a, b = first.state.runtime, second.state.runtime
    for name in ['brain', 'audit', 'policy', 'orchestrator', 'schedule_store', 'task_store',
                 'execution_history', 'phase4_store', 'improvements', 'connectors', 'approval_sessions',
                 'operations', 'turn_budget', 'profile_store', 'learning_domains', 'vision_engine',
                 'ambient_monitor', 'addressing_detector', 'satellite_registry', 'autonomous_guard',
                 'emergency_service', '_VOICE_LOCK', '_VOICE_SESSIONS']:
        assert getattr(a, name) is not getattr(b, name), name
    a.brain.write('notes', 'FACTORY-PRIVATE', 'Only in the first app')
    a.policy.set_emergency_stop(True)
    a._VOICE_SESSIONS[99] = ('first-loop', 'first-socket')
    with TestClient(first, headers={"X-Mica-API-Token": "mica-test-api-token-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}) as one, TestClient(second, headers={"X-Mica-API-Token": "mica-test-api-token-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}) as two:
        assert 'FACTORY-PRIVATE' in one.get('/v1/brain/explorer').text
        assert 'FACTORY-PRIVATE' not in two.get('/v1/brain/explorer').text
        assert one.get('/health').status_code == two.get('/health').status_code == 200
        assert one.get('/v1/operations/summary').json()['services']['emergency_stop'] == 'active'
        assert two.get('/v1/operations/summary').json()['services']['emergency_stop'] == 'inactive'
        assert one.get('/openapi.json').status_code == two.get('/openapi.json').status_code == 200
    assert not b._VOICE_SESSIONS
    assert a._backup_root() != b._backup_root()
    assert a.dream_engine.store.path != b.dream_engine.store.path


def test_factory_allows_completion_injection_without_affecting_another_app(tmp_path):
    first = create_app(data_dir=tmp_path / 'one', dependencies={'_local_completion': lambda *a, **k: 'First reply'})
    second = create_app(data_dir=tmp_path / 'two', dependencies={'_local_completion': lambda *a, **k: 'Second reply'})
    with TestClient(first, headers={"X-Mica-API-Token": "mica-test-api-token-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}) as one, TestClient(second, headers={"X-Mica-API-Token": "mica-test-api-token-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}) as two:
        body = {'message': 'Hello', 'remember': False}
        assert one.post('/v1/turns', json=body).json()['reply'] == 'First reply'
        assert two.post('/v1/turns', json=body).json()['reply'] == 'Second reply'


def test_importing_factory_creates_no_runtime_files(tmp_path):
    root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    environment['PYTHONPATH'] = str(root)
    for name in ['BRAIN_DIR', 'INDEX_PATH', 'AUDIT_PATH', 'APPROVAL_DB', 'SCHEDULE_DB',
                 'IMPROVEMENT_DB', 'CONNECTOR_DB', 'MICA_STATE_DB', 'OPERATIONS_DB',
                 'TURN_BUDGET_DB', 'MICA_PROFILE_PATH', 'LEARNING_DOMAINS_PATH']:
        environment[name] = str(tmp_path / name.lower())
    result = subprocess.run([sys.executable, '-c', 'from backend.services.api.app import create_app'],
                            cwd=root, env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []
