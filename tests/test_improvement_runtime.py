from __future__ import annotations

import concurrent.futures
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "mica_core"
sys.path.insert(0, str(ROOT))

from services.common.brain import MarkdownBrain
from services.common.improvements import ImprovementRegistry
from services.common.policy import PolicyEngine


class ImprovementRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.previous_workspace = os.environ.get("IMPROVEMENT_WORKSPACE")
        os.environ["IMPROVEMENT_WORKSPACE"] = str(self.root / "workspace")
        self.brain = MarkdownBrain(self.root / "brain", self.root / "index.sqlite3")
        self.registry = ImprovementRegistry(self.root / "improvements.sqlite3", self.brain)

    def tearDown(self) -> None:
        if self.previous_workspace is None:
            os.environ.pop("IMPROVEMENT_WORKSPACE", None)
        else:
            os.environ["IMPROVEMENT_WORKSPACE"] = self.previous_workspace
        self.temporary.cleanup()

    def _validated(self, name: str, kind: str, content: str) -> dict[str, str]:
        proposal = self.registry.propose(name, kind, content, "local test evidence")
        self.assertTrue(self.registry.evaluate(proposal["id"], True, True, "tests passed", "health passed"))
        return proposal

    def test_promotion_publishes_a_verified_data_only_runtime_artifact(self) -> None:
        proposal = self._validated("chat-style", "prompt", "Antworte freundlich und knapp.")
        self.assertTrue(self.registry.promote(proposal["id"]))

        state = self.registry.runtime_state()
        self.assertEqual(state["activation"], "data-only")
        self.assertEqual(state["artifacts"][0]["name"], "chat-style")
        self.assertEqual(state["artifacts"][0]["execution"], "data-only")
        active = self.registry.runtime_artifact("chat-style")
        self.assertIsNotNone(active)
        self.assertEqual(active["content"], "Antworte freundlich und knapp.\n")
        self.assertTrue((self.registry.runtime / active["path"]).is_file())

    def test_failed_shadow_quarantines_candidate_and_republishes_previous_active_artifact(self) -> None:
        first = self._validated("chat-style", "prompt", "Version eins.")
        self.assertTrue(self.registry.promote(first["id"]))
        second = self._validated("chat-style", "prompt", "Defekte Version zwei.")

        self.assertTrue(self.registry.record_shadow_failure(second["id"], "healthcheck failed"))
        self.assertEqual(self.registry.active("chat-style"), first["id"])
        self.assertEqual(self.registry.runtime_artifact("chat-style")["content"], "Version eins.\n")
        failed = next(item for item in self.registry.list("chat-style") if item["id"] == second["id"])
        self.assertEqual(failed["status"], "shadow_failed")
        self.assertFalse(self.registry.promote(second["id"]))

    def test_late_health_failure_of_an_active_revision_rolls_back_automatically(self) -> None:
        first = self._validated("chat-style", "prompt", "Sichere Version eins.")
        self.assertTrue(self.registry.promote(first["id"]))
        second = self._validated("chat-style", "prompt", "Version zwei.")
        self.assertTrue(self.registry.promote(second["id"]))

        self.assertTrue(self.registry.record_shadow_failure(second["id"], "post-promotion healthcheck failed"))
        self.assertEqual(self.registry.active("chat-style"), first["id"])
        self.assertEqual(self.registry.runtime_artifact("chat-style")["content"], "Sichere Version eins.\n")
        failed = next(item for item in self.registry.list("chat-style") if item["id"] == second["id"])
        self.assertEqual(failed["status"], "rolled_back")
        self.assertIn("healthcheck failed", failed["failure_reason"])

    def test_parallel_promotions_cannot_create_two_active_revisions(self) -> None:
        # Separate instances simulate independent API workers sharing both the
        # SQLite database and isolated Git workspace.
        other = ImprovementRegistry(self.root / "improvements.sqlite3", self.brain)
        first = self._validated("parallel-style", "prompt", "Erste Variante.")
        second = self._validated("parallel-style", "prompt", "Zweite Variante.")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda candidate: other.promote(candidate), [first["id"], second["id"]]))

        self.assertEqual(outcomes.count(True), 1)
        active = [item for item in self.registry.list("parallel-style") if item["status"] == "active"]
        self.assertEqual(len(active), 1)
        self.assertEqual(self.registry.runtime_artifact("parallel-style")["id"], active[0]["id"])

    def test_protected_configuration_and_host_capable_code_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "policy, secrets or host permissions"):
            self.registry.propose("ui-options", "config", '{"policy": {"allow": true}}', "evidence")
        with self.assertRaisesRegex(ValueError, "policy, secrets or host permissions"):
            self.registry.propose("ui-options", "config", '{"api_key": "must-not-be-stored"}', "evidence")
        with self.assertRaisesRegex(ValueError, "may not import host capabilities"):
            self.registry.propose("helper", "code", "import subprocess\n", "evidence")

    def test_promoted_code_is_marked_for_the_isolated_runner_only(self) -> None:
        code = (
            "def main(payload):\n"
            "    return {'healthcheck': bool(payload.get('healthcheck')), "
            "'text': str(payload.get('text', '')).strip()}\n"
        )
        proposal = self._validated("normalise-text", "code", code)
        self.assertTrue(self.registry.promote(proposal["id"]))
        active = self.registry.runtime_artifact("normalise-text")
        self.assertEqual(active["execution"], "isolated-container-only")
        self.assertIn("def main(payload)", active["content"])

        with self.assertRaisesRegex(ValueError, "private or interpreter attributes"):
            self.registry.propose(
                "unsafe-introspection", "code",
                "def main(payload):\n    return payload.__class__.__name__\n", "evidence",
            )

    def test_code_invocation_needs_a_fresh_parameter_bound_approval(self) -> None:
        policy = PolicyEngine(self.root / "invoke-approvals.sqlite3")
        params = {"improvement_id": "a" * 32, "payload": {"text": "eins"}}
        decision = policy.decide("improvement.invoke", params)
        self.assertEqual(decision.risk, "destructive")
        self.assertTrue(decision.requires_approval)
        self.assertTrue(policy.resolve(decision.approval_id or "", True))
        self.assertFalse(policy.consume_approval(
            decision.approval_id or "", "improvement.invoke",
            {"improvement_id": "a" * 32, "payload": {"text": "zwei"}},
        ))
        self.assertTrue(policy.consume_approval(decision.approval_id or "", "improvement.invoke", params))
        self.assertFalse(policy.consume_approval(decision.approval_id or "", "improvement.invoke", params))


if __name__ == "__main__":
    unittest.main()
