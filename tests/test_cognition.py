from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from backend.services.api.app import create_app
from backend.services.common.cognition import CognitiveController, CognitiveState, PROFILES
from backend.services.common.dialog_sessions import DialogSessions


SESSION = 'a' * 32


def test_attention_prefers_relevant_memory_and_bounds_context_without_mutating_input():
    controller, state = CognitiveController(), CognitiveState(profile='low_vram')
    evidence = [{'id': str(i), 'title': title, 'snippet': snippet}
                for i, (title, snippet) in enumerate([
                    ('Rezept', 'Kartoffeln ' * 300), ('Mikrofon', 'Mikrofon Rauschen ' * 300),
                    ('Mikrofon USB', 'USB ' * 300), ('Audio', 'Audio ' * 300)])]
    result, prompt = controller.prepare(state, 'Mikrofon Rauschen', evidence)
    assert result[0]['title'] == 'Mikrofon'
    assert len(result) <= 3
    assert sum(len(item['title']) + len(item['snippet']) for item in result) <= 1800
    assert len(evidence[1]['snippet']) > 1000
    assert len(prompt) <= PROFILES['low_vram']['controller_chars']


def test_state_continuity_corrections_support_and_time_decay():
    now = [0.0]
    controller, state = CognitiveController(clock=lambda: now[0]), CognitiveState(updated=0)
    controller.prepare(state, 'Docker Container', [])
    controller.prepare(state, 'Wie mache ich damit weiter?', [], history=[{}])
    assert state.stance == 'focused'
    controller.prepare(state, 'Nein, das stimmt nicht', [])
    assert state.stance == 'careful'
    controller.prepare(state, 'Ich bin überfordert', [])
    assert state.stance == 'supportive'
    now[0] = 1800
    controller.prepare(state, 'Erkläre Photosynthese', [])
    assert state.stance == 'neutral'
    assert 'docker' not in state.focus_terms


def test_self_observation_is_measured_bounded_and_affects_next_prompt():
    controller, state = CognitiveController(), CognitiveState()
    controller.observe(state, error=True)
    _, prompt = controller.prepare(state, 'Weiter bitte', [])
    assert 'fehlgeschlagen' in prompt
    for _ in range(10):
        controller.observe(state, reply='Private Antwort', invalid_citations=True)
    assert len(state.observations) == 4
    assert 'Private Antwort' not in str(state.snapshot())
    _, prompt = controller.prepare(state, 'Weiter bitte', [])
    assert 'Quellenmarkierungen' in prompt


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv('MICA_API_TOKEN', 'x' * 40)
    monkeypatch.setenv('MICA_LAYA_ENABLED', '0')
    monkeypatch.setenv('MICA_HINDSIGHT_ENABLED', '0')
    monkeypatch.setenv('MICA_LLM_PROVIDER', 'ollama')
    app = create_app(data_dir=tmp_path)
    runtime = app.state.runtime
    runtime._local_completion = Mock(return_value='Eine Antwort.')
    return TestClient(app, headers={'X-Mica-API-Token': 'x' * 40}), runtime


def test_real_turn_path_uses_controller_once_and_reuses_session(api):
    client, runtime = api
    payload = {'message': 'Ich bin frustriert', 'session_id': SESSION, 'remember': False}
    result = client.post('/v1/turns', json=payload)
    assert result.status_code == 200, result.text
    assert result.json()['cognition']['stance'] == 'supportive'
    assert 'ruhig und zugewandt' in runtime._local_completion.call_args.kwargs['system_prompt']
    assert runtime._local_completion.call_count == 1
    status = client.get(f'/v1/dialog/{SESSION}/cognition').json()
    assert status['turns'] == 1
    assert status['additional_gpu_memory_bytes'] == 0
    assert not runtime.brain.documents()
    assert client.get(f'/v1/dialog/{"b" * 32}/cognition').json()['turns'] == 0


def test_model_failure_observed_and_recovery_has_no_false_success(api):
    client, runtime = api
    runtime._local_completion.side_effect = ValueError('offline')
    payload = {'message': 'Erkläre den Himmel', 'session_id': SESSION, 'remember': False}
    assert client.post('/v1/turns', json=payload).status_code == 503
    status = client.get(f'/v1/dialog/{SESSION}/cognition').json()
    assert status['observations'][-1]['kind'] == 'model_error'
    runtime._local_completion.side_effect = None
    assert client.post('/v1/turns', json=payload).status_code == 200
    assert 'fehlgeschlagen' in runtime._local_completion.call_args.kwargs['system_prompt']


def test_toggle_reset_and_validation_keep_state_local(api):
    client, runtime = api
    path = f'/v1/dialog/{SESSION}/cognition'
    assert client.patch(path, json={'enabled': True, 'profile': 'low_vram'}).status_code == 200
    payload = {'message': 'Nein, falsch', 'session_id': SESSION, 'remember': False}
    client.post('/v1/turns', json=payload)
    assert client.delete(path).json()['turns'] == 0
    assert client.get(path).json()['profile'] == 'low_vram'
    client.patch(path, json={'enabled': False})
    client.post('/v1/turns', json=payload)
    assert 'Antwortsteuerung' not in runtime._local_completion.call_args.kwargs['system_prompt']
    assert client.get(path).json()['turns'] == 0
    assert client.patch(path, json={'enabled': True, 'profile': 'huge'}).status_code == 422
    assert client.patch(path, json={'enabled': True, 'execute': True}).status_code == 422
    assert client.get('/v1/dialog/wrong/cognition').status_code == 422
    assert TestClient(client.app).get(path).status_code == 401
    client.delete(f'/v1/dialog/{SESSION}')
    assert client.get(path).json()['enabled'] is True


def test_cloud_path_never_receives_private_controller_state(api):
    client, runtime = api
    runtime.configured_cloud_provider = lambda: 'gemini'
    runtime.cloud_private_context_allowed = lambda: False
    client.post('/v1/turns', json={'message': 'Hallo', 'session_id': SESSION, 'remember': False})
    assert 'Antwortsteuerung' not in runtime._local_completion.call_args.kwargs['system_prompt']
    assert client.get(f'/v1/dialog/{SESSION}/cognition').json()['turns'] == 0


def test_expiry_and_clear_remove_controller_state():
    now = [0.0]
    sessions = DialogSessions(clock=lambda: now[0], ttl=10)
    with sessions.session(SESSION) as state:
        state.cognition.focus_terms = ['private']
    now[0] = 11
    with sessions.session(SESSION) as state:
        assert not state.cognition.focus_terms
        state.cognition.focus_terms = ['private']
    sessions.clear(SESSION)
    with sessions.session(SESSION) as state:
        assert not state.cognition.focus_terms
