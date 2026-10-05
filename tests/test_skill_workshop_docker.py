"""Real networkless Docker shadow evaluation against independent fixtures."""
import json
import shutil
import subprocess

import pytest

from backend.host_agent import app as host
from backend.services.common.brain import MarkdownBrain
from backend.services.common.evolution import EvolutionStore
from backend.services.common.improvements import ImprovementRegistry
from backend.services.common.workshop import SkillWorkshop


@pytest.mark.integration
def test_actual_docker_shadow_reproduces_repairs_and_rejects_wrong_answers(tmp_path, monkeypatch):
    if not shutil.which("docker"):
        pytest.skip("Docker is unavailable")
    ready = subprocess.run(["docker", "image", "inspect", "python:3.12-alpine"], capture_output=True, timeout=10)
    if ready.returncode:
        pytest.skip("Shadow base image is not available locally")
    monkeypatch.setenv("IMPROVEMENT_WORKSPACE", str(tmp_path / "workspace"))
    registry = ImprovementRegistry(tmp_path / "improvements.sqlite3", MarkdownBrain(tmp_path / "brain", tmp_path / "index.sqlite3"))
    workshop = SkillWorkshop(EvolutionStore(tmp_path / "evolution.sqlite3"), registry)
    monkeypatch.setattr(host, "_config", lambda: {"improvement_root": str(registry.worktrees), "improvement_runtime_root": str(registry.runtime)})
    monkeypatch.setattr(host, "_EMERGENCY_STOPPED", False)
    suite = workshop.create_suite("Verdopple n", [
        {"id": "positive", "input": {"n": 2}, "expected": 4},
        {"id": "negative", "input": {"n": -2}, "expected": -4},
        {"id": "zero", "input": {"n": 0}, "expected": 0},
    ], "independent-fixtures")
    gap = workshop.store.record_gap("double", registered=False)
    images = []
    try:
        wrong = workshop.stage("double", suite["id"], "def main(payload):\n    return payload['n']", gap_id=gap["id"])
        images.append("mica-shadow-" + wrong["proposal"]["id"][:12])
        failed = host._shadow_improvement(wrong["proposal"]["id"])
        assert not failed["tests_passed"]
        assert failed["quality"]["candidate"]["correct"] == 1
        assert not registry.evaluate(wrong["proposal"]["id"], False, True, json.dumps(failed), "actual Docker")
        registry.record_shadow_failure(wrong["proposal"]["id"], "Wrong outputs")
        assert registry.active("double") is None
        original = registry.propose("double", "code", "def main(payload):\n    return payload.get('n', 0)", "known regression")
        # Establish a legacy revision; the new repair is evaluated independently.
        registry.evaluate(original["id"], True, True, "legacy smoke check", "legacy healthy")
        registry.promote(original["id"])
        repair = workshop.stage("double", suite["id"], "def main(payload):\n    return payload.get('n', 0) * 2", intent="repair")
        identifier = repair["proposal"]["id"]
        images.append("mica-shadow-" + identifier[:12])
        passed = host._shadow_improvement(identifier)
        assert passed["isolated"] and passed["tests_passed"] and passed["quality"]["reproduced"]
        assert passed["quality"]["baseline"]["correct"] == 1
        assert passed["quality"]["candidate"]["correct"] == 3
        assert registry.active("double") == original["id"]
        assert registry.evaluate(identifier, True, True, json.dumps(passed), "actual Docker")
        assert registry.promote(identifier)
        invoked = host._invoke_active_improvement(identifier, {"n": 3})
        assert invoked["result"] == 6 and invoked["isolated"]
        assert workshop.descriptions()[0]["name"] == "double"
        assert registry.rollback("double")
        assert registry.active("double") == original["id"]
    finally:
        for image in images:
            subprocess.run(["docker", "image", "rm", image], capture_output=True, timeout=15)
