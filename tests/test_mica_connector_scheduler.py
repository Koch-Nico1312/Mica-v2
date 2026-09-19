from __future__ import annotations

import hashlib
import hmac
import importlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "mica_core"
sys.path.insert(0, str(ROOT))

from services.common.connectors import ConnectorRegistry
from services.common.scheduler_store import ScheduleStore


class ConnectorRegistryAndScheduleTests(unittest.TestCase):
    def test_inbound_event_claim_is_connector_scoped_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = ConnectorRegistry(Path(temp) / "connectors.sqlite3")
            self.assertTrue(registry.claim_inbound_event("telegram", "update:10"))
            self.assertFalse(registry.claim_inbound_event("telegram", "update:10"))
            self.assertTrue(registry.claim_inbound_event("whatsapp", "update:10"))

    def test_finite_recurrence_creates_only_the_next_pending_occurrence(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ScheduleStore(Path(temp) / "schedules.sqlite3")
            first_run = datetime.now(UTC) + timedelta(minutes=3)
            first = store.create(
                "Wiederkehrende Erinnerung", first_run.isoformat(), "reminder.dispatch",
                {"connector": "telegram", "message": "Zeit zum Pausieren"},
                {"every_seconds": 60, "occurrences": 3},
            )
            claimed = store.claim_due(first_run + timedelta(seconds=1))
            self.assertEqual(claimed[0]["status"], "awaiting_approval")
            pending = store.list("pending")
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["series_id"], first["id"])
            self.assertEqual(pending[0]["recurrence"], {"every_seconds": 60, "occurrences": 2})
            second = store.claim_due(first_run + timedelta(seconds=61))
            self.assertEqual(len(second), 1)
            self.assertEqual(len(store.list("pending")), 1)
            self.assertEqual(store.list("pending")[0]["recurrence"], {"every_seconds": 60, "occurrences": 1})

    def test_recurrence_must_be_finite_and_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ScheduleStore(Path(temp) / "schedules.sqlite3")
            future = (datetime.now(UTC) + timedelta(minutes=3)).isoformat()
            with self.assertRaises(ValueError):
                store.create("Unbounded", future, "brain.reindex", recurrence={"every_seconds": 60})
            with self.assertRaises(ValueError):
                store.create("Too fast", future, "brain.reindex", recurrence={"every_seconds": 1, "occurrences": 2})


@unittest.skipUnless(
    importlib.util.find_spec("fastapi") and importlib.util.find_spec("httpx"),
    "FastAPI/httpx are installed in the mica-api image, not this lightweight local interpreter",
)
class ProviderWebhookApiTests(unittest.TestCase):
    @contextmanager
    def api(self):
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
            "BRAIN_DIR": str(Path(temp) / "brain"),
            "INDEX_PATH": str(Path(temp) / "index.sqlite3"),
            "AUDIT_PATH": str(Path(temp) / "audit.jsonl"),
            "APPROVAL_DB": str(Path(temp) / "approvals.sqlite3"),
            "SCHEDULE_DB": str(Path(temp) / "schedules.sqlite3"),
            "IMPROVEMENT_DB": str(Path(temp) / "improvements.sqlite3"),
            "CONNECTOR_DB": str(Path(temp) / "connectors.sqlite3"),
            "MICA_APPROVAL_SECRET": "test-local-approval-secret",
            "MICA_TELEGRAM_WEBHOOK_SECRET": "telegram-webhook-secret",
            "MICA_WHATSAPP_VERIFY_TOKEN": "whatsapp-verify-token",
            "MICA_WHATSAPP_APP_SECRET": "whatsapp-app-secret",
            "MICA_LLM_FALLBACK_URL": "",
        }, clear=False):
            module = importlib.import_module("services.api.app")
            module = importlib.reload(module)
            with TestClient(module.app) as client:
                yield client, module

    def test_telegram_requires_opt_in_parses_text_and_deduplicates(self):
        payload = {"update_id": 901, "message": {"message_id": 1, "chat": {"id": 42}, "text": "Bitte Status"}}
        with self.api() as (client, module):
            disabled = client.post("/v1/connectors/telegram/webhook", json=payload, headers={"X-Telegram-Bot-Api-Secret-Token": "telegram-webhook-secret"})
            self.assertEqual(disabled.status_code, 409)
            module.connectors.set_enabled("telegram", True)
            with patch.dict(os.environ, {"MICA_TELEGRAM_INBOUND_CHAT_IDS": "99"}):
                not_allowlisted = client.post("/v1/connectors/telegram/webhook", json=payload, headers={"X-Telegram-Bot-Api-Secret-Token": "telegram-webhook-secret"})
            self.assertEqual(not_allowlisted.status_code, 403)
            accepted = client.post("/v1/connectors/telegram/webhook", json=payload, headers={"X-Telegram-Bot-Api-Secret-Token": "telegram-webhook-secret"})
            self.assertEqual(accepted.status_code, 200)
            self.assertTrue(accepted.json()["plan"]["dry_run"])
            self.assertEqual(accepted.json()["plan"]["action"], "brain.search")
            duplicate = client.post("/v1/connectors/telegram/webhook", json=payload, headers={"X-Telegram-Bot-Api-Secret-Token": "telegram-webhook-secret"})
            self.assertEqual(duplicate.json(), {"accepted": True, "duplicate": True})
            invalid = client.post("/v1/connectors/telegram/webhook", json={"update_id": 902}, headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"})
            self.assertEqual(invalid.status_code, 401)

    def test_whatsapp_challenge_signature_and_reminder_broker_path(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"field": "messages", "value": {"messages": [{"id": "wamid.123", "from": "436600000000", "type": "text", "text": {"body": "Hallo MICA"}}]}}]}],
        }
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = "sha256=" + hmac.new(b"whatsapp-app-secret", raw, hashlib.sha256).hexdigest()
        with self.api() as (client, module):
            disabled = client.get("/v1/connectors/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "whatsapp-verify-token", "hub.challenge": "opaque-challenge"})
            self.assertEqual(disabled.status_code, 409)
            module.connectors.set_enabled("whatsapp", True)
            challenge = client.get("/v1/connectors/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "whatsapp-verify-token", "hub.challenge": "opaque-challenge"})
            self.assertEqual(challenge.status_code, 200)
            self.assertEqual(challenge.text, "opaque-challenge")
            rejected = client.post("/v1/connectors/whatsapp/webhook", content=raw, headers={"X-Hub-Signature-256": "sha256=wrong"})
            self.assertEqual(rejected.status_code, 401)
            accepted = client.post("/v1/connectors/whatsapp/webhook", content=raw, headers={"X-Hub-Signature-256": signature, "Content-Type": "application/json"})
            self.assertEqual(accepted.status_code, 200)
            self.assertEqual(accepted.json()["received"], 1)

            due_at = datetime.now(UTC) + timedelta(minutes=3)
            scheduled = module.schedule_store.create("Erinnerung senden", due_at.isoformat(), "reminder.dispatch", {"connector": "telegram", "message": "Pause"})
            module.schedule_store.claim_due(due_at + timedelta(seconds=1))

            class BrokerResponse:
                status_code = 200

                @staticmethod
                def raise_for_status():
                    return None

                @staticmethod
                def json():
                    return {"dispatched": True}

            with patch.object(module.httpx, "post", return_value=BrokerResponse()) as post:
                response = client.post(f"/v1/schedules/{scheduled['id']}/dispatch", json={"approval_id": "fresh-browser-approval"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(post.call_args.kwargs["json"]["action"], "message.send")
            self.assertEqual(module.schedule_store.get(scheduled["id"])["status"], "completed")


if __name__ == "__main__":
    unittest.main()
