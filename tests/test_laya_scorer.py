from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "backend"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from services.common.laya_scorer import (
    HeuristicTriage,
    LayaScorer,
    build_scorer,
    laya_enabled,
    rerank_retrieval,
    triage_signal,
)


class FakeRouter:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def predict(self, state, questions):
        self.calls.append((state, questions))
        return self.response


class LayaScorerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_names = (
            "MICA_LAYA_ENABLED",
            "MICA_LAYA_MIN_CONFIDENCE",
            "MICA_LAYA_RERANK_WEIGHT",
            "MICA_LAYA_PROPOSAL_THRESHOLD",
            "MICA_LAYA_MODEL_DIR",
        )
        self.previous = {name: os.environ.get(name) for name in self.env_names}
        for name in self.env_names:
            os.environ.pop(name, None)

    def tearDown(self) -> None:
        for name, value in self.previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_disabled_by_default(self) -> None:
        self.assertFalse(laya_enabled())

    def test_scorer_returns_none_without_laya_package(self) -> None:
        # The feature is disabled, so no import or model load may be attempted.
        scorer = LayaScorer()
        self.assertIsNone(scorer.rerank([
            {"policy": {"a": 1}, "score": 0.5, "expected_reward": 1.0,
             "expected_cost": 2.0, "wasted_fraction": 0.0, "source": "heuristic"},
            {"policy": {"a": 2}, "score": 0.9, "expected_reward": 2.0,
             "expected_cost": 2.0, "wasted_fraction": 0.0, "source": "heuristic"},
        ]))
        self.assertIsNone(scorer.triage("RuntimeError", "agent-plan:system.status", 5))

    def test_rerank_skips_trivial_batches(self) -> None:
        scorer = LayaScorer()
        self.assertIsNone(scorer.rerank([{"policy": {}, "score": 1.0, "expected_reward": 1.0,
                                          "expected_cost": 1.0, "wasted_fraction": 0.0, "source": "heuristic"}]))

    def test_rerank_uses_one_score_question_per_candidate_and_current_schema(self) -> None:
        router = FakeRouter({"answers": {
            "candidate_0": {"score": 2.0, "confidence": 0.9},
            "candidate_1": {"score": 0.0, "confidence": 0.9},
        }})
        scorer = LayaScorer(router=router)
        evaluations = [
            {"policy": {"name": "semantic-winner"}, "score": 0.50, "expected_reward": 1.0,
             "expected_cost": 2.0, "wasted_fraction": 0.0, "source": "heuristic"},
            {"policy": {"name": "replay-winner"}, "score": 0.51, "expected_reward": 1.0,
             "expected_cost": 2.0, "wasted_fraction": 0.0, "source": "heuristic"},
        ]
        ranked = scorer.rerank(evaluations)
        self.assertIsNotNone(ranked)
        self.assertEqual(ranked[0]["policy"]["name"], "semantic-winner")
        self.assertEqual(ranked[0]["laya_score"], 1.0)
        _, questions = router.calls[0]
        self.assertEqual(set(questions), {"candidate_0", "candidate_1"})

    def test_low_confidence_rerank_falls_back(self) -> None:
        router = FakeRouter({"answers": {
            "candidate_0": {"score": 2.0, "confidence": 0.39},
            "candidate_1": {"score": 0.0, "confidence": 0.9},
        }})
        scorer = LayaScorer(router=router)
        evaluations = [
            {"policy": {"a": 1}, "score": 0.5, "expected_reward": 1.0,
             "expected_cost": 2.0, "wasted_fraction": 0.0, "source": "heuristic"},
            {"policy": {"a": 2}, "score": 0.6, "expected_reward": 1.0,
             "expected_cost": 2.0, "wasted_fraction": 0.0, "source": "heuristic"},
        ]
        self.assertIsNone(scorer.rerank(evaluations))

    def test_calibrated_answer_confidence_takes_precedence(self) -> None:
        router = FakeRouter({"answers": {
            "priority": {"score": 1.5, "confidence": 0.28, "answer_confidence": 0.53},
            "worth_proposing": {"noul": 0.7},
        }})
        result = LayaScorer(router=router).triage("RuntimeError", "scheduler", 4)
        self.assertIsNotNone(result)
        self.assertEqual(result["engine"], "laya")
        self.assertEqual(result["confidence"], 0.53)

    def test_retrieval_rerank_preserves_items_and_uses_score_field(self) -> None:
        router = FakeRouter({"answers": {
            "document_0": {"score": 0.2, "confidence": 0.8},
            "document_1": {"score": 1.8, "confidence": 0.8},
        }})
        results = [
            {"id": "a", "title": "Other", "snippet": "unrelated", "kind": "note"},
            {"id": "b", "title": "Qwen start", "snippet": "start command", "kind": "runbook"},
        ]
        ranked = LayaScorer(router=router).rerank_retrieval("Wie starte ich Qwen?", results)
        self.assertIsNotNone(ranked)
        self.assertEqual([item["id"] for item in ranked], ["b", "a"])
        self.assertEqual({item["id"] for item in ranked}, {"a", "b"})

    def test_triage_uses_current_score_and_noul_fields(self) -> None:
        router = FakeRouter({"answers": {
            "priority": {"score": 1.6, "confidence": 0.85},
            "worth_proposing": {"noul": 0.72},
        }})
        result = LayaScorer(router=router).triage("RuntimeError", "scheduler", 5)
        self.assertEqual(result["engine"], "laya")
        self.assertEqual(result["priority"], 0.8)
        self.assertTrue(result["worth_proposing"])
        self.assertEqual(result["proposal_probability"], 0.72)

    def test_public_retrieval_wrapper_keeps_original_on_failure(self) -> None:
        original = [{"id": "a"}, {"id": "b"}]
        os.environ["MICA_LAYA_ENABLED"] = "1"
        fake = Mock()
        fake.rerank_retrieval.return_value = None
        with patch("services.common.laya_scorer.build_scorer", return_value=fake):
            self.assertIs(rerank_retrieval("query", original), original)

    def test_build_scorer_reuses_one_instance(self) -> None:
        self.assertIs(build_scorer(), build_scorer())

    def test_local_model_directory_is_passed_to_router_without_network(self) -> None:
        os.environ["MICA_LAYA_ENABLED"] = "1"
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "multilingual").mkdir()
            os.environ["MICA_LAYA_MODEL_DIR"] = directory
            router = object()
            router_type = Mock(return_value=router)
            fake_laya = SimpleNamespace(Router=router_type)
            with patch.dict(sys.modules, {"laya": fake_laya}), \
                 patch("services.common.laya_scorer.LAYA_AVAILABLE", True):
                self.assertIs(LayaScorer()._ensure_router(), router)
            router_type.assert_called_once_with(
                models={
                    "english": directory,
                    "multilingual": (directory, "multilingual"),
                },
                default="multilingual",
                preload=False,
            )

    def test_missing_configured_model_directory_fails_closed(self) -> None:
        os.environ["MICA_LAYA_ENABLED"] = "1"
        os.environ["MICA_LAYA_MODEL_DIR"] = str(ROOT / "does-not-exist")
        fake_laya = SimpleNamespace(Router=Mock())
        with patch.dict(sys.modules, {"laya": fake_laya}), \
             patch("services.common.laya_scorer.LAYA_AVAILABLE", True):
            scorer = LayaScorer()
            self.assertIsNone(scorer._ensure_router())
            self.assertTrue(scorer._router_failed)

    def test_compose_bakes_laya_dependency_and_checkpoints_when_enabled(self) -> None:
        dockerfile = (ROOT / "backend" / "docker" / "Dockerfile.python").read_text(encoding="utf-8")
        compose = (ROOT / "backend" / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn('"laya==0.3.20"', dockerfile)
        self.assertIn("snapshot_download('convaiinnovations/laya'", dockerfile)
        self.assertIn("local_dir='/opt/mica/laya-model'", dockerfile)
        self.assertGreaterEqual(compose.count("MICA_INSTALL_LAYA: ${MICA_LAYA_ENABLED:-0}"), 2)
        self.assertIn("MICA_LAYA_MODEL_DIR: /opt/mica/laya-model", compose)

    def test_heuristic_triage_is_deterministic_and_bounded(self) -> None:
        first = HeuristicTriage.triage("RuntimeError", "agent-plan:system.status", 5)
        second = HeuristicTriage.triage("RuntimeError", "agent-plan:system.status", 5)
        self.assertEqual(first, second)
        self.assertTrue(0.0 <= first["priority"] <= 1.0)
        self.assertIn(first["worth_proposing"], {True, False})
        self.assertEqual(first["engine"], "heuristic")
        low = HeuristicTriage.triage("ValueError", "unseen-context", 1)
        self.assertFalse(low["worth_proposing"])

    def test_triage_signal_falls_back_without_laya(self) -> None:
        result = triage_signal("HTTPError", "scheduler:learning.monitor", 9)
        self.assertEqual(result["engine"], "heuristic")
        self.assertTrue(0.0 <= result["priority"] <= 1.0)


if __name__ == "__main__":
    unittest.main()
