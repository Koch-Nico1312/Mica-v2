import json
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend.services.api.app import create_app
from backend.services.common.quality_runner import compare


def test_api_generation_quality_review_observations_and_explicit_promotion(tmp_path, monkeypatch):
    token = 'api-evolution-token-xxxxxxxxxxxxxxxxxxxxxxxx'
    monkeypatch.setenv('MICA_API_TOKEN', token)
    monkeypatch.setenv('MICA_APPROVAL_SECRET', 'local-evolution-secret')
    app = create_app(data_dir=tmp_path, dependencies={
        '_local_completion': lambda *a, **kw: json.dumps({'code': "def main(payload):\n    return payload['n'] * 2"}),
        'configured_cloud_provider': lambda: None,
    })
    runtime = app.state.runtime
    gap = runtime.evolution.record_gap('double', registered=False)
    with TestClient(app, headers={'X-Mica-API-Token': token, 'X-Mica-Approval-Intent': 'confirm'}) as client:
        assert client.post('/v1/auth/approval-session', json={'secret': 'local-evolution-secret'}).status_code == 200
        cases = [{'id': 'positive', 'input': {'n': 2}, 'expected': 4},
                 {'id': 'negative', 'input': {'n': -2}, 'expected': -4},
                 {'id': 'zero', 'input': {'n': 0}, 'expected': 0}]
        response = client.post('/v1/evolution/suites', json={'goal': 'Verdopple n', 'source': 'independent user fixtures', 'cases': cases})
        assert response.status_code == 200, response.text
        suite_id = response.json()['suite']['id']
        response = client.post('/v1/evolution/workshop', json={'name': 'double', 'suite_id': suite_id, 'gap_id': gap['id']})
        assert response.status_code == 200, response.text
        identifier = response.json()['proposal']['id']
        assert runtime.improvements.active('double') is None
        path = runtime.improvements.candidate_path(identifier)
        report = compare(json.loads((path / 'quality.json').read_text()))
        broker = Mock()
        broker.status_code = 200
        broker.json.return_value = {'result': {'tests_passed': report['passed'], 'health_passed': True, 'quality': report}}
        with patch.object(runtime.httpx, 'post', return_value=broker):
            response = client.post(f'/v1/improvements/{identifier}/evaluate', json={'auto_promote': False})
        assert response.status_code == 200, response.text
        assert response.json()['validated'] and not response.json()['promoted']
        assert client.get('/v1/evolution/workshop').json()['jobs'][0]['quality']['candidate']['correct'] == 3
        rejected = client.post(f'/v1/improvements/{identifier}/promote', json={})
        assert rejected.status_code == 403
        approval = rejected.json()['detail']['approval_id']
        assert client.post(f'/v1/approvals/{approval}', json={'approved': True}).status_code == 200
        assert client.post(f'/v1/improvements/{identifier}/promote', json={'approval_id': approval}).json()['promoted']
        assert runtime.workshop.descriptions()[0]['id'] == identifier
        response = client.post(f'/v1/evolution/revisions/{identifier}/observations', json={
            'task_id': 'actual-task-1', 'success': True, 'duration_ms': 45, 'provider_cost': 0.02,
            'user_corrections': 1, 'source': 'confirmed actual measurement',
        })
        assert response.status_code == 200, response.text
        assert response.json()['metrics']['user_corrections'] == 1
        for invalid in (float('inf'), -1):
            # Direct JSON request text proves nonfinite and negative values are rejected.
            body = '{"task_id":"bad","success":true,"duration_ms":' + ('Infinity' if invalid == float('inf') else '-1') + ',"provider_cost":0,"user_corrections":0,"source":"user"}'
            assert client.post(f'/v1/evolution/revisions/{identifier}/observations', content=body, headers={'content-type': 'application/json'}).status_code == 422
        runtime.policy.set_emergency_stop(True)
        assert client.post('/v1/evolution/workshop', json={'name': 'double', 'suite_id': suite_id, 'gap_id': gap['id']}).status_code == 409


def test_requested_unknown_action_records_gap_without_model_generation(tmp_path, monkeypatch):
    token = 'unknown-action-token-xxxxxxxxxxxxxxxxxxxxxxxx'
    monkeypatch.setenv('MICA_API_TOKEN', token)
    app = create_app(data_dir=tmp_path)
    with TestClient(app, headers={'X-Mica-API-Token': token}) as client:
        result = client.post('/v1/turns', json={'message': 'Neue Fähigkeit', 'action': 'unknown.example', 'params': {}})
        assert result.status_code == 422
        gaps = client.get('/v1/evolution/gaps').json()['gaps']
        assert gaps[0]['category'] == 'missing_tool'
        assert client.get('/v1/evolution/workshop').json()['jobs'] == []
