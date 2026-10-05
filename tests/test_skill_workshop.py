import hashlib
import json

import pytest

from backend.services.common.brain import MarkdownBrain
from backend.services.common.evolution import EvolutionStore
from backend.services.common.improvements import ImprovementRegistry
from backend.services.common.quality_runner import compare
from backend.services.common.workshop import SkillWorkshop


@pytest.fixture
def workshop(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPROVEMENT_WORKSPACE", str(tmp_path / "workspace"))
    store = EvolutionStore(tmp_path / "evolution.sqlite3")
    brain = MarkdownBrain(tmp_path / "brain", tmp_path / "index.sqlite3")
    return SkillWorkshop(store, ImprovementRegistry(tmp_path / "improvements.sqlite3", brain))


def suite(workshop):
    return workshop.create_suite("Verdopple die Zahl n", [
        {"id": "positive", "input": {"n": 2}, "expected": 4},
        {"id": "negative", "input": {"n": -2}, "expected": -4},
        {"id": "zero", "input": {"n": 0}, "expected": 0},
    ], "independent-user-fixtures")


def test_forge_stages_frozen_suite_and_requires_real_quality_evidence(workshop):
    gap = workshop.store.record_gap("double", registered=False)
    spec = suite(workshop)
    result = workshop.stage("double", spec["id"], "def main(payload):\n    return payload['n'] * 2", gap_id=gap["id"])
    identifier = result["proposal"]["id"]
    path = workshop.registry.candidate_path(identifier)
    manifest = json.loads((path / "shadow.json").read_text())
    for file, key in [("quality.json", "quality_sha256"), ("quality_runner.py", "quality_runner_sha256")]:
        assert hashlib.sha256((path / file).read_bytes()).hexdigest() == manifest[key]
    assert not workshop.registry.evaluate(identifier, True, True, "tests passed", "healthy")
    bundle = json.loads((path / "quality.json").read_text())
    report = compare(bundle)
    assert report["passed"]
    assert report["baseline"]["correct"] == 0
    assert report["candidate"]["correct"] == 3
    assert report["candidate"]["duration_ms"] > 0
    assert report["candidate"]["user_corrections"] is None
    assert workshop.registry.evaluate(identifier, True, True, json.dumps({"quality": report}), "isolated fixture run")
    assert workshop.registry.promote(identifier)
    assert workshop.registry.runtime_artifact("double")["content"].strip().endswith("return payload['n'] * 2")


def test_permission_and_outage_are_not_skill_generation_triggers(workshop):
    spec = suite(workshop)
    for category in ({"status_code": 403}, {"status_code": 503}):
        gap = workshop.store.record_gap("double", **category)
        with pytest.raises(ValueError, match="permission or outage"):
            workshop.stage("double", spec["id"], "def main(payload):\n    return 4", gap_id=gap["id"])
    assert workshop.registry.list() == []


def test_repair_reproduces_failure_and_preserves_active_until_promotion(workshop):
    original = workshop.registry.propose("double", "code", "def main(payload):\n    return payload['n']", "known bug reproduction")
    assert workshop.registry.evaluate(original["id"], True, True, "old smoke check", "healthy")
    assert workshop.registry.promote(original["id"])
    spec = suite(workshop)
    result = workshop.stage("double", spec["id"], "def main(payload):\n    return payload['n'] * 2", intent="repair")
    identifier = result["proposal"]["id"]
    assert result["job"]["baseline_id"] == original["id"]
    assert "-    return payload['n']" in result["job"]["patch"]
    assert workshop.registry.active("double") == original["id"]
    bundle = json.loads((workshop.registry.candidate_path(identifier) / "quality.json").read_text())
    report = compare(bundle)
    assert report["reproduced"] and report["passed"]
    assert workshop.registry.evaluate(identifier, True, True, json.dumps({"quality": report}), "isolated fixture run")
    assert workshop.registry.promote(identifier)
    assert workshop.registry.rollback("double")
    assert workshop.registry.active("double") == original["id"]


def test_regression_rejects_candidate_and_unreproduced_repair_is_not_valid():
    cases = [{"id": "a", "input": {"n": 2}, "expected": 4}, {"id": "b", "input": {"n": 3}, "expected": 6}]
    report = compare({"suite_id": "suite", "cases": cases,
                      "baseline": "def main(payload):\n    return payload['n'] * 2",
                      "candidate": "def main(payload):\n    return 4", "intent": "repair"})
    assert not report["passed"]
    assert report["regressions"] == ["b"]
    assert not report["reproduced"]


def test_generation_does_not_receive_test_answers_and_is_bounded(workshop):
    spec = suite(workshop)
    gap = workshop.store.record_gap("double", registered=False)
    calls = []
    def generate(prompt):
        calls.append(prompt)
        assert "independent-user-fixtures" not in prompt
        assert '"expected"' not in prompt
        return json.dumps({"code": "import os\ndef main(payload):\n    return 1"})
    with pytest.raises(ValueError, match="bounded validation"):
        workshop.generate("double", spec["id"], generate, gap_id=gap["id"])
    assert len(calls) == 2
    assert workshop.registry.list() == []


def test_revision_metrics_are_observed_not_assumed_and_deduplicate_tasks(workshop):
    revision = workshop.registry.propose('double', 'code', 'def main(payload):\n    return 0', 'metrics test')
    assert workshop.metrics(revision['id'])['user_corrections'] is None
    metrics = workshop.observe(revision['id'], 'task-1', False, 30, 0.02, 2, 'actual-user-feedback')
    assert metrics['tasks'] == 1 and metrics['errors'] == 1 and metrics['user_corrections'] == 2
    metrics = workshop.observe(revision['id'], 'task-1', True, 40, 0.03, 1, 'corrected-measurement')
    assert metrics['tasks'] == 1 and metrics['errors'] == 0 and metrics['user_corrections'] == 1
    assert metrics['duration_ms'] == 40 and metrics['provider_cost'] == 0.03


def test_evolution_backup_restores_rules_suites_gaps_and_observations(tmp_path, workshop):
    from backend.backup_restore import _state_export, _restore_evolution
    workshop.store.confirm('format', 'Stichpunkte', 'global', 'turn-1')
    gap = workshop.store.record_gap('double', registered=False)
    spec = suite(workshop)
    revision = workshop.stage('double', spec['id'], 'def main(payload):\n    return 0', gap_id=gap['id'])
    workshop.observe(revision['proposal']['id'], 'task-1', False, 30, 0, 2, 'user')
    export = json.loads(_state_export(workshop.store.path.parent))['evolution']
    restored = EvolutionStore(tmp_path / 'restored' / 'evolution.sqlite3')
    counts = _restore_evolution(export, restored.path)
    assert counts['evolution_learned_preferences'] == 1
    assert restored.preferences()[0]['value'] == 'Stichpunkte'
    assert restored.gaps()[0]['id'] == gap['id']
    with restored.connect() as conn:
        assert conn.execute('SELECT user_corrections FROM revision_observations').fetchone()[0] == 2
        assert conn.execute('SELECT id FROM quality_suites').fetchone()[0] == spec['id']


def test_generation_accepts_fenced_json_and_rejects_outage_before_model_call(workshop):
    spec = suite(workshop)
    unavailable = workshop.store.record_gap('double', status_code=503)
    with pytest.raises(ValueError, match='permission or outage'):
        workshop.generate('double', spec['id'], lambda prompt: pytest.fail('No model request for outage'), gap_id=unavailable['id'])
    gap = workshop.store.record_gap('double', registered=False)
    result = workshop.generate('double', spec['id'], lambda prompt: '```json\n' + json.dumps({'code': "def main(payload):\n    return payload['n'] * 2"}) + '\n```', gap_id=gap['id'])
    assert result['status'] == 'proposed'


def test_quality_candidate_cannot_be_promoted_after_baseline_changes(workshop):
    original = workshop.registry.propose('double', 'code', "def main(payload):\n    return payload['n']", 'old')
    workshop.registry.evaluate(original['id'], True, True, 'old tests', 'healthy')
    workshop.registry.promote(original['id'])
    spec = suite(workshop)
    staged = workshop.stage('double', spec['id'], "def main(payload):\n    return payload['n'] * 2", intent='repair')
    identifier = staged['proposal']['id']
    bundle = json.loads((workshop.registry.candidate_path(identifier) / 'quality.json').read_text())
    report = compare(bundle)
    assert workshop.registry.evaluate(identifier, True, True, json.dumps({'quality': report}), 'healthy')
    competing = workshop.registry.propose('double', 'code', "def main(payload):\n    return 0", 'competing revision')
    workshop.registry.evaluate(competing['id'], True, True, 'other tests', 'healthy')
    assert workshop.registry.promote(competing['id'])
    assert not workshop.registry.promote(identifier)


def test_timeout_is_reported_and_does_not_pass_quality_gate():
    report = compare({'suite_id': 'suite', 'cases': [{'id': 'timeout', 'input': {}, 'expected': 1}],
                      'baseline': 'def main(payload):\n    return 0',
                      'candidate': 'def main(payload):\n    while True:\n        pass', 'intent': 'repair'})
    assert not report['passed']
    assert report['candidate']['cases'][0]['error'] == 'timeout'


def test_attempt_budget_is_enforced_across_store_restarts(workshop):
    gap = workshop.store.record_gap('double', registered=False)
    spec = suite(workshop)
    for index in range(3):
        workshop.stage('double', spec['id'], f'def main(payload):\n    return {index}', gap_id=gap['id'])
    restarted = SkillWorkshop(EvolutionStore(workshop.store.path), workshop.registry)
    with pytest.raises(ValueError, match='three candidate attempts'):
        restarted.stage('double', spec['id'], 'def main(payload):\n    return 4', gap_id=gap['id'])
