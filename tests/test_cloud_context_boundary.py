"""Exercise the privacy boundary at the actual desktop/PWA HTTP entry points."""
import importlib
import json

import pytest
from fastapi.testclient import TestClient

from backend.services.common import cloud_llm


@pytest.mark.parametrize('endpoint', ['/v1/chat', '/v1/turns'])
@pytest.mark.parametrize('provider', ['openai_api', 'gemini'])
@pytest.mark.parametrize('allow_private', [False, True])
def test_cloud_payload_requires_private_opt_in(tmp_path, monkeypatch, endpoint, provider, allow_private):
    for variable, filename in {
        'BRAIN_DIR': 'brain', 'INDEX_PATH': 'index.sqlite3',
        'AUDIT_PATH': 'audit.jsonl', 'APPROVAL_DB': 'approvals.sqlite3',
        'SCHEDULE_DB': 'schedules.sqlite3', 'MICA_STATE_DB': 'state.sqlite3',
        'IMPROVEMENT_DB': 'improvements.sqlite3', 'IMPROVEMENT_WORKSPACE': 'improvements',
        'CONNECTOR_DB': 'connectors.sqlite3', 'OPERATIONS_DB': 'operations.sqlite3',
        'TURN_BUDGET_DB': 'budget.sqlite3', 'MICA_PROFILE_PATH': 'profile.json',
    }.items():
        monkeypatch.setenv(variable, str(tmp_path / filename))
    monkeypatch.setenv('MICA_APPROVAL_SECRET', 'privacy-test-secret')
    monkeypatch.setenv('MICA_LLM_PROVIDER', provider)
    monkeypatch.setenv('OPENAI_API_KEY', 'fake-test-key')
    monkeypatch.setenv('GOOGLE_API_KEY', 'fake-test-key')
    monkeypatch.setenv('MICA_CLOUD_ALLOW_PRIVATE_CONTEXT', '1' if allow_private else '0')
    monkeypatch.setenv('MICA_DREAM_RSI_ENABLED', '0')
    module = importlib.import_module('backend.services.api.app').create_app().state.runtime
    from unittest.mock import Mock
    search = Mock(return_value=[{'title': 'PRIVATE-BRAIN', 'snippet': 'PRIVATE-SNIPPET', 'confidence': 'high'}])
    profile = Mock(return_value='PRIVATE-PROFILE')
    reflection = Mock(return_value={'status': 'ready', 'text': 'PRIVATE-REFLECTION', 'sources': ['PRIVATE-SOURCE']})
    monkeypatch.setattr(module.brain, 'search', search)
    monkeypatch.setattr(module.brain, 'write', Mock(return_value={'id': '1'}))
    monkeypatch.setattr(module, 'profile_prompt', profile)
    monkeypatch.setattr(module.HindsightMemory, 'reflect', reflection)
    monkeypatch.setattr(module, '_active_assistant_profile', lambda: (
        'PRIVATE-PROMPT', {'chat_tokens': 64, 'temperature': 0.2}, 'PRIVATE-RUNBOOK',
    ))
    monkeypatch.setattr(module.phase4_store, 'twin_settings', lambda: {'cloud_opt_in': True})
    monkeypatch.setattr(module.phase4_store, 'twin_prompt', lambda: 'PRIVATE-TWIN')
    payloads = []

    def post(url, **kwargs):
        payloads.append(kwargs['json'])
        response = Mock()
        response.json.return_value = (
            {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'Antwort'}]}]}
            if provider == 'openai_api' else
            {'candidates': [{'content': {'parts': [{'text': 'Antwort'}]}}]}
        )
        return response

    monkeypatch.setattr(cloud_llm.httpx, 'post', post)
    with TestClient(module.app, headers={"X-Mica-API-Token": "mica-test-api-token-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}) as client:
        response = client.post(endpoint, json={'message': 'rückblick: Hallo', 'conversation_mode': 'personal'})
    assert response.status_code == 200, response.text
    assert response.json()['reply'] == 'Antwort'
    assert len(payloads) == 1
    wire = json.dumps(payloads[0])
    for secret in ['PRIVATE-BRAIN', 'PRIVATE-SNIPPET', 'PRIVATE-PROFILE', 'PRIVATE-REFLECTION',
                   'PRIVATE-SOURCE', 'PRIVATE-PROMPT', 'PRIVATE-RUNBOOK', 'PRIVATE-TWIN']:
        assert (secret in wire) is allow_private, secret
    assert search.call_count == int(allow_private)
    assert profile.call_count == int(allow_private)
    assert reflection.call_count == int(allow_private)
