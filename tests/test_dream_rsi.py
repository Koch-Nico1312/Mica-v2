from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "mica_core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from services.common.brain import MarkdownBrain
from services.common.improvements import ImprovementRegistry
from services.common.dream_rsi import (
    DEFAULT_POLICY,
    POLICY_ARTIFACT_NAME,
    DreamRSIEngine,
    DreamTreeStore,
    PolicyConfig,
    ReplaySimulator,
    reward_from_evaluation,
    attach_dream_rsi,
)


class FakeRegistry:
    """Minimal registry double that validates like the real one for config."""

    def __init__(self):
        self.proposed: list[tuple[str, str, str, str]] = []
        self.runtime: dict[str, dict[str, str]] = {}

    def propose(self, name: str, kind: str, content: str, evidence: str) -> dict[str, str]:
        self.proposed.append((name, kind, content, evidence))
        return {"id": f"{len(self.proposed):032d}", "status": "proposed"}

    def list(self) -> list[dict[str, str]]:
        return [{"status": "proposed"} for _ in self.proposed]

    def runtime_artifact(self, name: str) -> dict[str, str] | None:
        return self.runtime.get(name)


class DreamRSITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.previous = {key: os.environ.get(key) for key in (
            "MICA_DREAM_RSI_ENABLED", "MICA_DREAM_DB", "IMPROVEMENT_WORKSPACE",
        )}
        os.environ["MICA_DREAM_RSI_ENABLED"] = "1"
        os.environ["MICA_DREAM_DB"] = str(self.root / "dream.sqlite3")
        os.environ["IMPROVEMENT_WORKSPACE"] = str(self.root / "workspace")
        self.brain = MarkdownBrain(self.root / "brain", self.root / "index.sqlite3")
        self.registry = ImprovementRegistry(self.root / "improvements.sqlite3", self.brain)
        self.engine = attach_dream_rsi(self.registry, self.brain)

    def tearDown(self) -> None:
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temporary.cleanup()

    # ── Recording ────────────────────────────────────────────────────────────

    def test_lifecycle_events_build_a_discovery_tree(self) -> None:
        proposal = self.registry.propose("chat-style", "prompt", "Antworte knapp.", "test evidence")
        self.assertTrue(self.registry.evaluate(proposal["id"], True, True, "tests", "health"))
        self.assertTrue(self.registry.promote(proposal["id"]))

        trees = self.engine.store.trees()
        self.assertEqual(len(trees), 1)
        events = [node["event"] for node in trees[0]]
        self.assertEqual(events, ["propose", "evaluate", "promote"])
        promoted = trees[0][-1]
        self.assertEqual(promoted["reward"], 1.0)

    def test_reward_from_evaluation_is_deterministic(self) -> None:
        self.assertEqual(reward_from_evaluation(True, True), 1.0)
        self.assertEqual(reward_from_evaluation(True, False), 0.6)
        self.assertEqual(reward_from_evaluation(False, False), 0.0)

    def test_recording_failure_never_breaks_the_pipeline(self) -> None:
        def broken_listener(event: str, payload: dict) -> None:
            raise RuntimeError("boom")

        self.registry.on_event = broken_listener
        try:
            proposal = self.registry.propose("chat-style", "prompt", "Inhalt", "evidence")
            self.assertEqual(proposal["status"], "proposed")
        finally:
            self.registry.on_event = None

    # ── Policy schema ────────────────────────────────────────────────────────

    def test_policy_config_rejects_unknown_and_out_of_range_fields(self) -> None:
        self.assertIsNone(PolicyConfig.normalize({"mystery": 1}))
        self.assertIsNone(PolicyConfig.normalize({"propose_after_occurrences": 0}))
        self.assertIsNone(PolicyConfig.normalize({"propose_after_occurrences": 99}))
        self.assertIsNone(PolicyConfig.normalize({"kind_preference": ["bogus"]}))
        self.assertIsNone(PolicyConfig.normalize({"kind_preference": ["prompt", "prompt"]}))
        self.assertIsNone(PolicyConfig.normalize({"kind_preference": "prompt"}))
        valid = PolicyConfig.normalize({"kind_preference": ["config", "prompt"]})
        self.assertEqual(valid["kind_preference"], ["config", "prompt"])
        self.assertIsNone(PolicyConfig.normalize({"stop_on_shadow_failure": "yes"}))
        normalized = PolicyConfig.normalize({"propose_after_occurrences": 5, "stop_on_shadow_failure": True})
        self.assertEqual(normalized["propose_after_occurrences"], 5)
        self.assertTrue(normalized["stop_on_shadow_failure"])
        self.assertEqual(normalized["kind_preference"], DEFAULT_POLICY["kind_preference"])

    # ── Replay simulator ─────────────────────────────────────────────────────

    def test_replay_prefers_policies_that_stop_after_shadow_failure(self) -> None:
        store = DreamTreeStore(self.root / "replay.sqlite3")
        nodes: list[list[dict]] = []
        # Tree A: validation fails, then a retry tree that also fails.
        nodes.append([
            {"tree_id": "a", "improvement_id": "a", "improvement_name": "x", "kind": "prompt",
             "event": "propose", "outcome": "", "reward": 0.0, "cost": 1.0, "created_at": "t1"},
            {"tree_id": "a", "improvement_id": "a", "improvement_name": "x", "kind": "prompt",
             "event": "evaluate", "outcome": "failed", "reward": 0.0, "cost": 1.0, "created_at": "t2"},
        ])
        # Tree B: validation succeeds and gets promoted.
        nodes.append([
            {"tree_id": "b", "improvement_id": "b", "improvement_name": "y", "kind": "prompt",
             "event": "propose", "outcome": "", "reward": 0.0, "cost": 1.0, "created_at": "t3"},
            {"tree_id": "b", "improvement_id": "b", "improvement_name": "y", "kind": "prompt",
             "event": "evaluate", "outcome": "validated", "reward": 1.0, "cost": 1.0, "created_at": "t4"},
            {"tree_id": "b", "improvement_id": "b", "improvement_name": "y", "kind": "prompt",
             "event": "promote", "outcome": "", "reward": 1.0, "cost": 1.0, "created_at": "t5"},
        ])
        simulator = ReplaySimulator()
        stopping = simulator.replay(nodes, {**DEFAULT_POLICY, "stop_on_shadow_failure": True})
        continuing = simulator.replay(nodes, {**DEFAULT_POLICY, "stop_on_shadow_failure": False})
        self.assertEqual(stopping["wasted_fraction"], 0.0)
        self.assertGreaterEqual(stopping["score"], continuing["score"])
        # Determinism: identical inputs produce identical scores.
        self.assertEqual(stopping, simulator.replay(nodes, {**DEFAULT_POLICY, "stop_on_shadow_failure": True}))

    # ── Closed loop ──────────────────────────────────────────────────────────

    def test_cycle_is_skipped_when_disabled(self) -> None:
        os.environ["MICA_DREAM_RSI_ENABLED"] = "0"
        try:
            result = self.engine.run_cycle()
        finally:
            os.environ["MICA_DREAM_RSI_ENABLED"] = "1"
        self.assertEqual(result["status"], "skipped")
        self.assertIn("MICA_DREAM_RSI_ENABLED", result["reason"])

    def test_cycle_is_skipped_below_minimum_pool(self) -> None:
        self.registry.propose("chat-style", "prompt", "Inhalt", "evidence")
        result = self.engine.run_cycle()
        self.assertEqual(result["status"], "skipped")
        self.assertIn("pool below minimum", result["reason"])

    def test_cycle_proposes_the_best_policy_through_the_registry(self) -> None:
        # Build enough trees to pass the pool gate.
        for index in range(4):
            proposal = self.registry.propose(f"style-{index}", "prompt", f"Inhalt {index}", "evidence")
            self.registry.evaluate(proposal["id"], index % 2 == 0, index % 2 == 0, "tests", "health")
        captured: list[tuple[str, str, str, str]] = []
        original_propose = self.registry.propose

        def spy(name: str, kind: str, content: str, evidence: str) -> dict[str, str]:
            captured.append((name, kind, content, evidence))
            return original_propose(name, kind, content, evidence)

        self.registry.propose = spy  # type: ignore[method-assign]
        result = self.engine.run_cycle(max_candidates=3)
        self.assertEqual(result["status"], "completed")
        self.assertGreaterEqual(result["candidates"], 2)
        self.assertLessEqual(len(result["evaluations"]), 3)
        if result["proposal_id"]:
            self.assertEqual(len(captured), 1)
            name, kind, content, evidence = captured[0]
            self.assertEqual(name, POLICY_ARTIFACT_NAME)
            self.assertEqual(kind, "config")
            self.assertIn("Dream-RSI Replay", evidence)
            self.assertIn("propose_after_occurrences", content)

    def test_active_policy_reads_promoted_artifact_and_falls_back(self) -> None:
        self.assertEqual(self.engine.active_policy(), DEFAULT_POLICY)
        artifacts: dict[str, dict[str, str]] = {
            POLICY_ARTIFACT_NAME: {"kind": "config", "content": json.dumps({"propose_after_occurrences": 7})},
        }
        original = self.registry.runtime_artifact

        def fake_runtime_artifact(name: str) -> dict[str, str] | None:
            return artifacts.get(name)

        self.registry.runtime_artifact = fake_runtime_artifact  # type: ignore[method-assign]
        self.assertEqual(self.engine.active_policy()["propose_after_occurrences"], 7)
        artifacts[POLICY_ARTIFACT_NAME] = {"kind": "config", "content": "{invalid"}
        self.assertEqual(self.engine.active_policy(), DEFAULT_POLICY)
        del original  # keep linters quiet; the registry instance dies with the test

    def test_state_endpoint_shape(self) -> None:
        state = self.engine.state()
        self.assertTrue(state["enabled"])
        self.assertEqual(state["policy_artifact"], POLICY_ARTIFACT_NAME)
        self.assertIn("pool_size", state)
        self.assertIn("last_cycles", state)


if __name__ == "__main__":
    unittest.main()
