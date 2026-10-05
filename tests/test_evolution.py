from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
import pytest

from backend.services.common.evolution import EvolutionStore
from backend.services.api.app import create_app
from backend.services.api.schemas import TaskExecution


def test_corrections_survive_restart_override_and_forget_entire_history(tmp_path):
    store = EvolutionStore(tmp_path / "evolution.sqlite3")
    initial = store.confirm("format", "Fließtext", "global", "Nutzerkorrektur: turn-1")
    replacement = store.confirm("format", "Stichpunkte", "global", "Nutzerkorrektur: turn-2")
    assert replacement["supersedes"] == initial["id"]
    store.confirm("format", "Codebeispiele", "technical", "turn-3")
    reopened = EvolutionStore(store.path)
    assert "Codebeispiele" in reopened.context("technical")
    assert "Stichpunkte" not in reopened.context("technical")
    assert "Stichpunkte" in reopened.context("companion")
    assert len(reopened.preferences(True)) == 3
    assert reopened.forget(replacement["id"])
    assert len(reopened.preferences(True)) == 1
    assert "Fließtext" not in reopened.context("companion")


def test_concurrent_corrections_keep_one_active_rule(tmp_path):
    store = EvolutionStore(tmp_path / "evolution.sqlite3")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda index: store.confirm("format", str(index), "global", "user"), range(12)))
    assert len(store.preferences()) == 1
    assert len(store.preferences(True)) == 12


@pytest.mark.parametrize("evidence,expected", [
    ({"registered": False, "status_code": 403}, "missing_tool"),
    ({"status_code": 403}, "missing_permission"),
    ({"error_type": "PermissionError"}, "missing_permission"),
    ({"status_code": 503}, "temporary_outage"),
    ({"error_type": "ReadTimeout"}, "temporary_outage"),
    ({"error_class": "unavailable"}, "temporary_outage"),
    ({"error_type": "ValueError"}, "broken_tool"),
])
def test_gap_classification(evidence, expected):
    assert EvolutionStore.classify(**evidence) == expected


def test_gap_evidence_is_deduplicated_and_retained(tmp_path):
    store = EvolutionStore(tmp_path / "evolution.sqlite3")
    a = store.record_gap("brain.search", error_type="ValueError")
    b = store.record_gap("brain.search", error_type="ValueError")
    assert a["id"] == b["id"]
    assert b["occurrences"] == 2
    assert EvolutionStore(store.path).gaps()[0]["source"] == "task_execution"


def test_preference_api_requires_explicit_local_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("MICA_API_TOKEN", "evolution-test-token-xxxxxxxxxxxxxxxxxxxxxxxx")
    monkeypatch.setenv("MICA_APPROVAL_SECRET", "evolution-test-secret")
    app = create_app(data_dir=tmp_path)
    with TestClient(app) as client:
        payload = {"key": "format", "value": "Stichpunkte", "source": "turn-1"}
        assert client.post("/v1/evolution/preferences", json=payload).status_code == 401
        client.headers["X-Mica-API-Token"] = "evolution-test-token-xxxxxxxxxxxxxxxxxxxxxxxx"
        assert client.post("/v1/evolution/preferences", json=payload).status_code == 401
        assert client.post("/v1/auth/approval-session", json={"secret": "evolution-test-secret"}).status_code == 200
        assert client.post("/v1/evolution/preferences", json=payload).status_code == 401
        client.headers["x-mica-approval-intent"] = "confirm"
        response = client.post("/v1/evolution/preferences", json=payload)
        assert response.status_code == 200, response.text
        identifier = response.json()["preference"]["id"]
        assert client.get("/v1/evolution/preferences").json()["preferences"][0]["source"] == "turn-1"
        assert client.delete(f"/v1/evolution/preferences/{identifier}").status_code == 200
        assert client.get("/v1/evolution/preferences?include_history=true").json() == {"preferences": []}
    with sqlite3.connect(app.state.runtime.evolution.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM learned_preferences").fetchone()[0] == 0


def test_task_failure_records_actual_gap_and_dry_run_does_not(tmp_path, monkeypatch):
    monkeypatch.setenv("MICA_API_TOKEN", "test-token")
    runtime = create_app(data_dir=tmp_path).state.runtime
    request = TaskExecution(action="files.list", params={}, dry_run=True)
    assert runtime.execute_task(request)["status"] == "dry_run"
    assert runtime.evolution.gaps() == []
    from fastapi import HTTPException
    with patch.object(runtime, "_dispatch_task", side_effect=HTTPException(403, "Approval required")):
        with pytest.raises(HTTPException):
            runtime.execute_task(request.model_copy(update={"dry_run": False, "task_id": "f" * 32}))
    assert runtime.evolution.gaps()[0]["category"] == "missing_permission"


def test_confirmed_preferences_reach_text_voice_and_respect_cloud_context_opt_in(tmp_path, monkeypatch):
    from backend.services.api.schemas import ChatRequest, TurnRequest
    monkeypatch.setenv("MICA_API_TOKEN", "context-test-token-xxxxxxxxxxxxxxxxxxxxxxxx")
    prompts = []
    runtime = create_app(data_dir=tmp_path, dependencies={
        '_local_completion': lambda prompt, *a, **k: prompts.append(prompt) or 'Antwort',
        'configured_cloud_provider': lambda: None,
    }).state.runtime
    runtime.evolution.confirm('format', 'EVOLUTION-PREFERENCE-SECRET', 'technical', 'confirmed-turn')
    runtime.chat(ChatRequest(message='Hallo', conversation_mode='technical', remember=False))
    assert 'EVOLUTION-PREFERENCE-SECRET' in prompts[-1]
    runtime._voice_turn(TurnRequest(message='Hallo', client='voice', conversation_mode='technical', remember=False))
    assert 'EVOLUTION-PREFERENCE-SECRET' in prompts[-1]
    with patch.object(runtime, 'configured_cloud_provider', return_value='openai'), patch.object(runtime, 'cloud_private_context_allowed', return_value=False):
        runtime.chat(ChatRequest(message='Hallo', conversation_mode='technical', remember=False))
        assert 'EVOLUTION-PREFERENCE-SECRET' not in prompts[-1]
    assert runtime.evolution.preferences()[0]['source'] == 'confirmed-turn'


def test_dispatched_tool_failure_and_missing_broker_have_distinct_gap_categories(tmp_path):
    runtime = create_app(data_dir=tmp_path).state.runtime
    response = Mock(status_code=200)
    response.json.return_value = {'dispatched': True, 'result': {'success': False, 'error_class': 'invalid_result'}}
    request = TaskExecution(action='files.list', params={}, dry_run=False, task_id='a' * 32)
    with patch.object(runtime, '_windows_preflight_evidence', return_value={'ok': True}), patch.object(runtime.httpx, 'post', return_value=response):
        result = runtime.execute_task(request)
        assert result['status'] == 'failed'
        assert runtime.evolution.gaps()[0]['category'] == 'broken_tool'
        response.json.return_value = {'dispatched': False}
        result = runtime.execute_task(request.model_copy(update={'task_id': 'b' * 32}))
        assert result['status'] == 'not_dispatched'
        assert runtime.evolution.gaps()[0]['category'] == 'temporary_outage'
