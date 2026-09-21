from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "backend"
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


class WorstFirstScorer:
    """Stand-in for the Laya scorer: ranks the lowest replay score first."""

    def rerank(self, evaluations: list[dict]) -> list[dict]:
        return sorted(evaluations, key=lambda item: item["score"])


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

    def test_every_policy_field_changes_the_replayed_score(self) -> None:
        """The world model has to answer for each knob, otherwise the loop can
        only ever learn the single field the replay actually reads."""
        simulator = ReplaySimulator()

        def tree(index: int, outcome: str, name: str, kind: str = "prompt") -> list[dict]:
            return [
                {"tree_id": f"t{index}", "improvement_id": f"i{index}", "improvement_name": name,
                 "kind": kind, "event": "propose", "outcome": "", "reward": 0.0, "cost": 1.0, "created_at": f"a{index}"},
                {"tree_id": f"t{index}", "improvement_id": f"i{index}", "improvement_name": name,
                 "kind": kind, "event": "evaluate", "outcome": outcome, "reward": 1.0, "cost": 1.0, "created_at": f"b{index}"},
            ]

        # One signal seen three times: first attempt fails, later ones are
        # retries, and only the last one validates. Waiting for the signal to
        # repeat before retrying is cheaper, so the higher threshold scores higher.
        repeated = [tree(0, "failed", "repeated"), tree(1, "failed", "repeated"), tree(2, "validated", "repeated")]
        strict = simulator.replay(repeated, {**DEFAULT_POLICY, "propose_after_occurrences": 3})
        eager = simulator.replay(repeated, {**DEFAULT_POLICY, "propose_after_occurrences": 1})
        self.assertGreater(strict["skipped"], 0)
        self.assertEqual(eager["skipped"], 0)
        self.assertGreater(strict["score"], eager["score"])

        # Retry cost: the backoff factor makes the repeats more expensive.
        cheap = simulator.replay(repeated, {**DEFAULT_POLICY, "propose_after_occurrences": 1, "retry_backoff_factor": 1.0})
        pricey = simulator.replay(repeated, {**DEFAULT_POLICY, "propose_after_occurrences": 1, "retry_backoff_factor": 3.0})
        self.assertGreater(pricey["expected_cost"], cheap["expected_cost"])
        self.assertLess(pricey["score"], cheap["score"])

        # Open candidates: a cap below the number of unresolved trees refuses them.
        pool = [tree(index, "validated", f"distinct-{index}") for index in range(6)]
        narrow = simulator.replay(pool, {**DEFAULT_POLICY, "max_open_candidates": 2})
        wide = simulator.replay(pool, {**DEFAULT_POLICY, "max_open_candidates": 25})
        self.assertEqual(wide["skipped"], 0)
        self.assertGreater(narrow["skipped"], 0)
        self.assertGreater(wide["expected_reward"], narrow["expected_reward"])

        # Kind preference: validated reward is weighted by the recorded kind.
        preferred = simulator.replay(pool, {**DEFAULT_POLICY, "kind_preference": ["prompt", "config"]})
        disliked = simulator.replay(pool, {**DEFAULT_POLICY, "kind_preference": ["code", "runbook"]})
        self.assertGreater(preferred["expected_reward"], disliked["expected_reward"])
        self.assertGreater(preferred["score"], disliked["score"])

    def test_replay_tolerates_a_malformed_policy(self) -> None:
        trees = [[
            {"tree_id": "a", "improvement_id": "a", "improvement_name": "x", "kind": "prompt",
             "event": "propose", "outcome": "", "reward": 0.0, "cost": 1.0, "created_at": "t1"},
            {"tree_id": "a", "improvement_id": "a", "improvement_name": "x", "kind": "prompt",
             "event": "evaluate", "outcome": "validated", "reward": 1.0, "cost": 1.0, "created_at": "t2"},
        ]]
        result = ReplaySimulator().replay(trees, {"propose_after_occurrences": "junk", "retry_backoff_factor": None})
        self.assertEqual(result["expected_cost"], 1.0 + 1.0)

    # ── Discovery-tree tagging ───────────────────────────────────────────────

    def test_tag_tree_persists_the_error_signature(self) -> None:
        proposal = self.registry.propose("signal-artifact", "prompt", "Inhalt", "evidence")
        self.engine.store.tag_tree(proposal["id"], "TypeError:boom@actions/x.py")
        nodes = [node for tree in self.engine.store.trees() for node in tree]
        propose_node = next(node for node in nodes if node["event"] == "propose")
        self.assertEqual(json.loads(propose_node["detail"])["error_signature"], "TypeError:boom@actions/x.py")
        # An empty signature is a no-op, never an empty string in the store.
        self.engine.store.tag_tree(proposal["id"], "  ")
        again = next(node for tree in self.engine.store.trees() for node in tree if node["event"] == "propose")
        self.assertEqual(json.loads(again["detail"])["error_signature"], "TypeError:boom@actions/x.py")

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
        # Six trees: the grid rotates by pool size, so 6 lands on the
        # stop_on_shadow_failure grid. The first tree retries a failing candidate,
        # so stopping after the first failure is measurably cheaper than carrying
        # the retry — that variant must beat the baseline and become a proposal.
        first = self.registry.propose("style-0", "prompt", "Inhalt 0", "evidence")
        self.registry.evaluate(first["id"], False, False, "tests", "health")
        self.registry.evaluate(first["id"], False, False, "tests", "health")
        for index in range(1, 6):
            proposal = self.registry.propose(f"style-{index}", "prompt", f"Inhalt {index}", "evidence")
            self.registry.evaluate(proposal["id"], True, True, "tests", "health")
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
        # A real proposal went through the registry, with the winning policy.
        self.assertTrue(result["proposal_id"])
        self.assertEqual(len(captured), 1)
        name, kind, content, evidence = captured[0]
        self.assertEqual(name, POLICY_ARTIFACT_NAME)
        self.assertEqual(kind, "config")
        self.assertIn("Dream-RSI Replay", evidence)
        policy = json.loads(content)
        self.assertTrue(policy["stop_on_shadow_failure"])
        # The winner is the best-scoring candidate and it beats the baseline.
        winner = result["winner"]
        self.assertEqual(winner["policy"], policy)
        self.assertEqual(winner["score"], max(item["score"] for item in result["evaluations"]))
        baseline = next(item for item in result["evaluations"] if item["source"] == "baseline")
        self.assertGreater(winner["score"], baseline["score"])

    def test_a_crash_in_a_third_party_scorer_cannot_break_a_cycle(self) -> None:
        self._seed_pool()

        class BrokenScorer:
            def rerank(self, evaluations: list[dict]) -> list[dict]:
                return [{"policy": {"nonsense": True}}, "not-a-row", evaluations[0]]

        self.engine.scorer = BrokenScorer()
        captured = self._spy_propose()
        result = self.engine.run_cycle(max_candidates=3)
        # The cycle completes on the engine's own evaluations, not the junk.
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["evaluations"])
        self.assertTrue(all(item.get("policy") for item in result["evaluations"]))
        del captured

    # ── Baseline guard ───────────────────────────────────────────────────────

    def _seed_pool(self, count: int = 4) -> None:
        for index in range(count):
            proposal = self.registry.propose(f"pool-{index}", "prompt", f"Inhalt {index}", "evidence")
            self.registry.evaluate(proposal["id"], index % 2 == 0, index % 2 == 0, "tests", "health")

    def _bias_scores(self, baseline_score: float, candidate_score: float) -> None:
        """Force the replay to rank any non-baseline policy below/above baseline."""
        baseline = self.engine.active_policy()
        real_replay = self.engine.simulator.replay

        def biased(trees: list[list[dict]], policy: dict) -> dict:
            result = dict(real_replay(trees, policy))
            result["score"] = baseline_score if policy == baseline else candidate_score
            return result

        self.engine.simulator.replay = biased  # type: ignore[method-assign]

    def _limit_candidates_to_variant(self, variant: dict) -> None:
        self.engine._grid_candidates = lambda baseline, budget, pool: [variant] if budget > 0 else []

    def test_cycle_never_proposes_a_candidate_below_the_active_policy(self) -> None:
        self._seed_pool()
        variant = {**DEFAULT_POLICY, "propose_after_occurrences": 5}
        self._limit_candidates_to_variant(variant)
        self._bias_scores(baseline_score=9.0, candidate_score=1.0)
        # The scorer ranks the worse candidate first; it still must not be proposed.
        self.engine.scorer = WorstFirstScorer()
        proposed = self._spy_propose()
        result = self.engine.run_cycle(max_candidates=3)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["proposal_id"], "")
        self.assertEqual(proposed, [])
        self.assertIn("does not beat the active policy", result["reason"])
        self.assertEqual(result["winner"]["policy"], variant)

    def _spy_propose(self) -> list[str]:
        captured: list[str] = []
        original_propose = self.registry.propose

        def spy(name: str, kind: str, content: str, evidence: str) -> dict[str, str]:
            captured.append(content)
            return original_propose(name, kind, content, evidence)

        self.registry.propose = spy  # type: ignore[method-assign]
        return captured

    def test_cycle_proposes_the_candidate_that_beats_the_baseline(self) -> None:
        self._seed_pool()
        variant = {**DEFAULT_POLICY, "propose_after_occurrences": 5}
        self._limit_candidates_to_variant(variant)
        self._bias_scores(baseline_score=1.0, candidate_score=9.0)
        captured = self._spy_propose()
        result = self.engine.run_cycle(max_candidates=3)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["proposal_id"])
        self.assertEqual(len(captured), 1)
        self.assertEqual(json.loads(captured[0])["propose_after_occurrences"], 5)
        # Promotion stays a separate, explicit step.
        self.assertIsNone(self.registry.runtime_artifact(POLICY_ARTIFACT_NAME))

    def test_cycle_still_proposes_when_the_scorer_ranks_a_worse_candidate_first(self) -> None:
        self._seed_pool()
        variant = {**DEFAULT_POLICY, "propose_after_occurrences": 5}
        self._limit_candidates_to_variant(variant)
        self._bias_scores(baseline_score=1.0, candidate_score=9.0)

        self.engine.scorer = WorstFirstScorer()
        captured = self._spy_propose()
        result = self.engine.run_cycle(max_candidates=3)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["proposal_id"])
        # The lower-scoring baseline was ranked first but must not be proposed.
        self.assertEqual(len(captured), 1)
        self.assertEqual(json.loads(captured[0])["propose_after_occurrences"], 5)

    def test_cycle_without_a_better_candidate_reports_the_baseline(self) -> None:
        self._seed_pool()
        self._limit_candidates_to_variant(DEFAULT_POLICY)
        result = self.engine.run_cycle(max_candidates=3)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["proposal_id"], "")
        self.assertIn("matches the active policy", result["reason"])

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
