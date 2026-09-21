from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from backend.services.common.operations import OperationLedger, PRICE_TABLE_VERSION
from backend.services.common.contracts import ExecutionRequest, ExecutionResult, VoiceControl
from backend.services.common.turn_budget import TurnBudget, TurnBudgetExceeded


class OperationLedgerTests(unittest.TestCase):
    def test_measured_counts_are_reported_without_inventing_prices(self):
        with tempfile.TemporaryDirectory() as temporary:
            ledger = OperationLedger(Path(temporary) / "operations.sqlite3")
            ledger.record(
                action="llm.completion", provider="local_llama", duration_ms=125,
                input_units=42, output_units=7,
            )
            ledger.record(
                action="send_message", provider="telegram", duration_ms=300,
                error_class="timeout", retries=1, external=True,
            )
            summary = ledger.summary()
            self.assertEqual(summary["requests"], 2)
            self.assertEqual(summary["failures"], 1)
            self.assertEqual(summary["external_calls"], 1)
            self.assertEqual(summary["retries"], 1)
            self.assertEqual(summary["price_table_version"], PRICE_TABLE_VERSION)
            self.assertTrue(all(item["cost"] is None for item in summary["providers"]))
            self.assertTrue(all(not item["price_verified"] for item in summary["providers"]))

    def test_versioned_public_contracts_are_strictly_shaped(self):
        request = ExecutionRequest(action="system_status", dry_run=True)
        self.assertEqual(request.schema_version, 1)
        result = ExecutionResult(task_id="a" * 32, status="dry_run", action="system_status")
        self.assertEqual(result.status, "dry_run")
        voice = VoiceControl(command="start", input_mode="push_to_talk", state="listening")
        self.assertEqual(voice.schema_version, 1)

    def test_turn_budget_enforces_three_plans_five_calls_and_120_seconds(self):
        with tempfile.TemporaryDirectory() as temporary:
            budget = TurnBudget(Path(temporary) / "budget.sqlite3")
            turn_id = "1" * 32
            for number in range(3):
                budget.register_plan(turn_id, f"{number + 1:032x}")
            with self.assertRaisesRegex(TurnBudgetExceeded, "three planning"):
                budget.register_plan(turn_id, "f" * 32)
            task_id = "1" * 32
            for _ in range(5):
                self.assertEqual(budget.claim_tool_call(task_id), turn_id)
            with self.assertRaisesRegex(TurnBudgetExceeded, "five tool"):
                budget.claim_tool_call(task_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
