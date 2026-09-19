from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "mica_core"
sys.path.insert(0, str(ROOT))

from services.common.audit import AuditLog, redact_secrets


class ProviderAuditSecurityTests(unittest.TestCase):
    def test_redacts_provider_keys_embedded_in_errors_and_urls(self) -> None:
        openai_key = "sk-project-THIS_MUST_NEVER_REACH_THE_AUDIT"
        gemini_key = "AIzaTHIS_MUST_NEVER_REACH_THE_AUDIT_123456"
        opaque_key = "opaque-provider-credential"
        value = {
            "reason": (
                f"POST failed: Authorization: Bearer {openai_key}; "
                f"https://example.invalid/generate?key={gemini_key}&alt=json"
            ),
            "detail": f"OPENAI_API_KEY={opaque_key}",
        }

        serialized = json.dumps(redact_secrets(value))

        self.assertNotIn(openai_key, serialized)
        self.assertNotIn(gemini_key, serialized)
        self.assertNotIn(opaque_key, serialized)
        self.assertGreaterEqual(serialized.count("[REDACTED]"), 3)

    def test_audit_read_api_source_never_contains_provider_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "audit.jsonl"
            audit = AuditLog(path)
            secret = "sk-live-NOT_FOR_LOGGING_123456789"
            audit.append("chat.failed", {
                "provider": "openai_api",
                "reason": f"upstream rejected api_key={secret}",
            })

            raw = path.read_text(encoding="utf-8")
            exposed = json.dumps(audit.read(), ensure_ascii=False)
            chain_valid = audit.verify()

        self.assertNotIn(secret, raw)
        self.assertNotIn(secret, exposed)
        self.assertIn("[REDACTED]", raw)
        self.assertTrue(chain_valid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
