from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "mica_core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from services.common.laya_scorer import HeuristicTriage, LayaScorer, laya_enabled, triage_signal


class LayaScorerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous = os.environ.get("MICA_LAYA_ENABLED")
        os.environ.pop("MICA_LAYA_ENABLED", None)

    def tearDown(self) -> None:
        if self.previous is None:
            os.environ.pop("MICA_LAYA_ENABLED", None)
        else:
            os.environ["MICA_LAYA_ENABLED"] = self.previous

    def test_disabled_by_default(self) -> None:
        self.assertFalse(laya_enabled())

    def test_scorer_returns_none_without_laya_package(self) -> None:
        # The laya package is not installed in the test environment; the
        # scorer must degrade to None instead of raising.
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
