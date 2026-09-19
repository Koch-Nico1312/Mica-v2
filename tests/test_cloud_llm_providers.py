from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
MICA_CORE = ROOT / "mica_core"
sys.path.insert(0, str(MICA_CORE))

from services.common import cloud_llm


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class CloudProviderUnitTests(unittest.TestCase):
    def test_cloud_is_never_selected_from_key_presence_or_invalid_provider(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-existing", "MICA_LLM_PROVIDER": "unknown"}, clear=True):
            self.assertIsNone(cloud_llm.configured_cloud_provider())

    def test_openai_uses_responses_api_store_false_and_env_key(self) -> None:
        post = Mock(return_value=FakeResponse({
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "Hallo"}]}],
            "usage": {"input_tokens": 4, "output_tokens": 2},
        }))
        with (
            patch.dict(os.environ, {
                "MICA_LLM_PROVIDER": "openai_api",
                "OPENAI_API_KEY": "fake-openai-key",
                "MICA_OPENAI_MODEL": "test-openai-model",
            }, clear=True),
            patch.object(cloud_llm.httpx, "post", post),
        ):
            result = cloud_llm.cloud_completion("Frage", "MICA", 123, 0.2)

        self.assertEqual(result.text, "Hallo")
        self.assertEqual(result.provider, "openai_api")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.openai.com/v1/responses")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer fake-openai-key")
        self.assertEqual(kwargs["json"]["model"], "test-openai-model")
        self.assertIs(kwargs["json"]["store"], False)
        self.assertNotIn("fake-openai-key", str(kwargs["json"]))

    def test_gemini_uses_generate_content_and_google_key_fallback(self) -> None:
        post = Mock(return_value=FakeResponse({
            "candidates": [{"content": {"parts": [{"text": "Guten Tag"}]}}],
            "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2},
        }))
        with (
            patch.dict(os.environ, {
                "MICA_LLM_PROVIDER": "gemini",
                "GOOGLE_API_KEY": "fake-google-key",
                "MICA_GEMINI_MODEL": "test-gemini-model",
            }, clear=True),
            patch.object(cloud_llm.httpx, "post", post),
        ):
            result = cloud_llm.cloud_completion("Frage", "MICA", 88, 0.4)

        self.assertEqual(result.text, "Guten Tag")
        args, kwargs = post.call_args
        self.assertEqual(
            args[0],
            "https://generativelanguage.googleapis.com/v1beta/models/test-gemini-model:generateContent",
        )
        self.assertEqual(kwargs["headers"]["x-goog-api-key"], "fake-google-key")
        self.assertEqual(kwargs["json"]["contents"][0]["parts"][0]["text"], "Frage")

    def test_google_key_takes_precedence_and_private_context_needs_second_opt_in(self) -> None:
        with patch.dict(os.environ, {
            "MICA_LLM_PROVIDER": "gemini",
            "GOOGLE_API_KEY": "preferred-google-key",
            "GEMINI_API_KEY": "secondary-gemini-key",
        }, clear=True):
            self.assertFalse(cloud_llm.cloud_private_context_allowed())
            self.assertEqual(cloud_llm._required_key("gemini"), "preferred-google-key")

        with patch.dict(os.environ, {
            "MICA_LLM_PROVIDER": "gemini",
            "MICA_CLOUD_ALLOW_PRIVATE_CONTEXT": "true",
        }, clear=True):
            self.assertTrue(cloud_llm.cloud_private_context_allowed())

    def test_missing_key_fails_before_network(self) -> None:
        post = Mock()
        with (
            patch.dict(os.environ, {"MICA_LLM_PROVIDER": "openai_api"}, clear=True),
            patch.object(cloud_llm.httpx, "post", post),
            self.assertRaisesRegex(cloud_llm.CloudLLMError, "OPENAI_API_KEY"),
        ):
            cloud_llm.cloud_completion("Frage", "MICA", 50, 0.3)
        post.assert_not_called()


class ActiveApiCloudProviderTests(unittest.TestCase):
    def test_v1_chat_reaches_explicit_openai_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = {
                "BRAIN_DIR": str(root / "brain"),
                "INDEX_PATH": str(root / "index.sqlite3"),
                "AUDIT_PATH": str(root / "audit.jsonl"),
                "APPROVAL_DB": str(root / "approvals.sqlite3"),
                "SCHEDULE_DB": str(root / "schedules.sqlite3"),
                "IMPROVEMENT_DB": str(root / "improvements.sqlite3"),
                "IMPROVEMENT_WORKSPACE": str(root / "improvements"),
                "CONNECTOR_DB": str(root / "connectors.sqlite3"),
                "OPERATIONS_DB": str(root / "operations.sqlite3"),
                "TURN_BUDGET_DB": str(root / "turn-budget.sqlite3"),
                "MICA_PROFILE_PATH": str(root / "profile.json"),
                "MICA_APPROVAL_SECRET": "provider-test-secret",
                "MICA_LLM_PROVIDER": "openai_api",
                "OPENAI_API_KEY": "fake-route-key",
            }
            post = Mock(return_value=FakeResponse({
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "Aktive Route"}]}],
            }))
            with patch.dict(os.environ, environment, clear=False):
                module = importlib.reload(importlib.import_module("services.api.app"))
                with (
                    patch.object(module.brain, "search", return_value=[]),
                    patch.object(module.brain, "write", return_value={"id": "1"}),
                    patch.object(cloud_llm.httpx, "post", post),
                    TestClient(module.app) as client,
                ):
                    response = client.post("/v1/chat", json={"message": "Hallo", "conversation_mode": "personal"})
                    operation_summary = module.operations.summary(hours=1)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "Aktive Route")
        self.assertEqual(response.json()["mode"], "cloud-opt-in")
        self.assertEqual(post.call_args.args[0], "https://api.openai.com/v1/responses")
        self.assertEqual(post.call_args.kwargs["json"]["input"], "Hallo")
        self.assertEqual(operation_summary["external_calls"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
