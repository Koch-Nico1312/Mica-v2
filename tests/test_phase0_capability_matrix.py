from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.action_adapters import execution_availability
from mica_core.services.common.audit import AuditLog
from mica_core.services.common.capabilities import (
    CAPABILITIES,
    RISK_DESTRUCTIVE,
    RISK_READ,
    RISK_REVERSIBLE,
    RISK_SENSITIVE_READ,
)
from mica_core.services.common.idempotency import IdempotencyStore
from mica_core.services.common.policy import PolicyEngine


class Phase0CapabilityMatrixTests(unittest.TestCase):
    """One common safety matrix, executed for every Phase-0 capability."""

    @staticmethod
    def _safe_operation(manifest) -> str:
        return next(
            (operation for operation in manifest.allowed_operations
             if operation not in manifest.blocked_operations),
            manifest.allowed_operations[0],
        )

    @staticmethod
    def _environment(manifest, root: Path) -> dict[str, str]:
        prefix = f"MICA_CAPABILITY_{manifest.module.upper()}"
        environment = {
            "MICA_WINDOWS_ENABLED_ACTIONS": f"{manifest.action},{manifest.module}",
            "MICA_WINDOWS_ALLOWED_ROOTS": str(root),
            "MICA_WINDOWS_ALLOWED_APPS": "notepad",
        }
        if manifest.network_required:
            environment[f"{prefix}_NETWORK"] = "true"
            environment[f"{prefix}_TARGETS"] = "example.invalid"
        if manifest.requires_recipient_allowlist:
            environment[f"{prefix}_RECIPIENTS"] = "phase0-dummy"
        for secret in manifest.required_secrets:
            environment[secret] = "phase0-placeholder"
        return environment

    def test_all_twenty_capabilities_share_the_complete_safety_matrix(self):
        self.assertEqual(len(CAPABILITIES), 20)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audit = AuditLog(root / "audit.jsonl")

            for index, manifest in enumerate(CAPABILITIES):
                with self.subTest(module=manifest.module):
                    operation = self._safe_operation(manifest)
                    params = {manifest.operation_field: operation} if operation else {}
                    environment = self._environment(manifest, root)

                    # Schema and explicit per-operation risk.
                    operation_schema = manifest.input_schema["properties"][manifest.operation_field]
                    self.assertIn(operation, operation_schema["enum"])
                    self.assertIn(operation, manifest.risk_by_operation)
                    risk = manifest.risk_for(params)
                    self.assertIn(risk, {RISK_READ, RISK_SENSITIVE_READ, RISK_REVERSIBLE, RISK_DESTRUCTIVE})

                    # Missing host enablement fails with an actionable reason.
                    self.assertEqual(
                        execution_availability(manifest.action, params, {}),
                        (False, "action_not_enabled_on_windows_host"),
                    )

                    with patch.dict(os.environ, environment, clear=False):
                        policy = PolicyEngine(root / f"policy-{index}.sqlite3")

                        # Happy planning path and dry-run never dispatch.
                        dry_run = policy.decide(manifest.action, params, dry_run=True)
                        blocked = operation in manifest.blocked_operations
                        if blocked:
                            self.assertFalse(dry_run.allowed)
                            self.assertEqual(dry_run.reason, "operation_requires_local_replacement")
                        else:
                            self.assertTrue(dry_run.allowed)
                            self.assertFalse(dry_run.requires_approval)

                        # Approval behaviour is risk-derived and rejection stays rejected.
                        decision = policy.decide(manifest.action, params)
                        if blocked:
                            self.assertFalse(decision.allowed)
                            self.assertEqual(decision.risk, "unavailable")
                        elif risk == RISK_READ:
                            self.assertTrue(decision.allowed)
                            self.assertFalse(decision.requires_approval)
                        else:
                            self.assertFalse(decision.allowed)
                            self.assertTrue(decision.requires_approval)
                            self.assertTrue(policy.resolve(decision.approval_id or "", False))
                            self.assertFalse(policy.approved(
                                decision.approval_id or "", manifest.action, params,
                            ))

                        # Not-Aus dominates every capability.
                        policy.set_emergency_stop(True)
                        stopped = policy.decide(manifest.action, params, dry_run=True)
                        self.assertFalse(stopped.allowed)
                        self.assertEqual(stopped.risk, "stopped")

                    # Retry and idempotency rules are bounded for every operation.
                    retry = manifest.retry_for(params)
                    self.assertLessEqual(retry.max_attempts, 3)
                    if risk == RISK_REVERSIBLE:
                        self.assertEqual(retry.max_attempts, 2)
                        self.assertTrue(retry.requires_idempotency_key)
                    if risk == RISK_DESTRUCTIVE:
                        self.assertEqual(retry.max_attempts, 1)
                        self.assertFalse(retry.retry_after_unknown_outcome)
                    store = IdempotencyStore(root / f"idempotency-{index}.sqlite3")
                    key = f"phase0-matrix-{index:02d}"
                    self.assertIsNone(store.begin(key, manifest.action, params))
                    store.complete(key, {"status": "staged"})
                    self.assertEqual(store.begin(key, manifest.action, params), {"status": "staged"})

                    # Secrets and sensitive content never survive audit serialization.
                    secret = f"secret-value-{index:02d}"
                    audit.append("capability.matrix", {
                        "action": manifest.action,
                        "api_token": secret,
                        "message": f"sensitive-{index:02d}",
                    })
                    stored = audit.path.read_text(encoding="utf-8")
                    self.assertNotIn(secret, stored)
                    self.assertNotIn(f"sensitive-{index:02d}", stored)


if __name__ == "__main__":
    unittest.main(verbosity=2)
