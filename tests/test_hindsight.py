from __future__ import annotations

import json
import importlib
import os
from pathlib import Path
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from services.common.brain import MarkdownBrain
from services.common.hindsight import HindsightMemory, selected_summary
from services.common.orchestrator import Orchestrator


class HindsightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {
            "MICA_HINDSIGHT_ENABLED": "1", "MICA_HINDSIGHT_ALLOW_PRIVATE": "1",
            "MICA_HINDSIGHT_URL": "http://127.0.0.1:8888", "MICA_HINDSIGHT_BANK": "test",
            "MICA_HINDSIGHT_DB": str(root / "sync.sqlite3"), "MICA_HINDSIGHT_ALLOW_REMOTE": "0",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.brain = MarkdownBrain(root / "brain", root / "index.sqlite3")
        self.memory = HindsightMemory(self.brain)
        self.remote = {}
        self.calls = []

    def request(self, method, suffix, payload=None, **kwargs):
        self.calls.append((method, suffix, payload))
        if method == "DELETE":
            self.remote.pop(suffix.split("/")[-1], None)
            return {}
        if suffix == "memories":
            self.assertFalse(payload["async"])
            for item in payload["items"]:
                self.remote[item["document_id"]] = item
            return {"success": True}
        if suffix == "memories/recall":
            return {"results": [{"document_id": key, "text": "FAKE INFERRED CLAIM"} for key in self.remote]}
        if suffix == "reflect":
            return {"text": "Rückblick", "based_on": {"memories": [{"document_id": key} for key in self.remote]}}
        raise AssertionError(suffix)

    def test_opt_in_and_invalid_destinations_never_send(self):
        for env in [
            {"MICA_HINDSIGHT_ENABLED": "0"}, {"MICA_HINDSIGHT_ALLOW_PRIVATE": "0"},
            {"MICA_HINDSIGHT_URL": "https://cloud.example"},
            {"MICA_HINDSIGHT_URL": "http://[invalid"},
            {"MICA_HINDSIGHT_URL": "http://localhost:invalid"},
            {"MICA_HINDSIGHT_URL": "http://user:password@localhost:8888"},
        ]:
            with self.subTest(env=env), patch.dict(os.environ, env), patch.object(HindsightMemory, "_request") as send:
                memory = HindsightMemory(self.brain)
                self.assertEqual(memory.sync()["status"], "disabled")
                self.assertEqual(memory.recall("Hallo"), [])
                self.assertEqual(memory.reflect("Hallo")["status"], "disabled")
                send.assert_not_called()

    def test_selected_user_excerpts_only_and_stale_summary_revocation(self):
        source = self.brain.write("conversations", "Chat", "Nutzer: Linux\nMica: erfundene Behauptung", {"hindsight_summary": "Nutzer sagte: Linux"})
        self.brain.write("conversations", "Alt", "vollständiges Gespräch")
        self.brain.write("evidence", "Raw", "private tool output")
        self.brain.write("memory", "Excluded", "sensibel", {"hindsight_exclude": True})
        self.brain.write("memory", "Secret", "password=hidden")
        self.assertEqual(list(self.memory.sources()), [source["id"]])
        self.assertNotIn("erfundene", self.memory.sources()[source["id"]]["item"]["content"])
        path = Path(source["path"])
        path.write_text(path.read_text(encoding="utf-8").replace("Nutzer: Linux", "Nutzer: Windows"), encoding="utf-8")
        self.assertEqual(self.memory.sources(), {})
        self.assertEqual(selected_summary("x" * 1801), "")

    def test_windows_newlines_preserve_evidence_and_selected_summary(self):
        body = "Nutzer: Linux\r\n\r\nMica: Antwort"
        source = self.brain.write("conversations", "Windows input", body, {"hindsight_summary": "Nutzer: Linux"})
        self.assertIn(source["id"], self.memory.sources())
        self.assertTrue(Path(source["path"]).read_bytes().endswith(body.encode()))
        corrected = "Nutzer: Windows\r\n\r\nMica: Antwort"
        self.brain.update_document(source["id"], corrected, "Nutzer: Windows")
        self.assertIn(source["id"], self.memory.sources())

    def test_restart_idempotency_correction_and_delete(self):
        source = self.brain.write("memory", "OS", "Ich benutze Linux")
        with patch.object(HindsightMemory, "_request", side_effect=self.request):
            self.assertEqual(self.memory.sync()["processed"], 1)
            restarted = HindsightMemory(self.brain)
            self.assertEqual(restarted.sync()["processed"], 0)
            self.assertEqual(len(self.calls), 2)
            self.brain.update_document(source["id"], "Ich benutze Windows")
            self.assertEqual(restarted.recall("OS"), [])
            self.assertEqual(restarted.reflect("OS")["status"], "pending")
            self.assertEqual(restarted.sync()["processed"], 1)
            self.assertEqual(self.remote[source["id"]]["content"], "Ich benutze Windows")
            self.brain.delete_document(source["id"])
            self.assertEqual(restarted.recall("OS"), [])
            self.assertEqual(restarted.sync()["processed"], 1)
            self.assertEqual(self.remote, {})

    def test_ambiguous_retain_timeout_survives_restart_and_source_removal(self):
        source = self.brain.write("memory", "OS", "Linux")
        def uncertain(method, suffix, payload=None, **kwargs):
            result = self.request(method, suffix, payload, **kwargs)
            if suffix == "memories":
                raise httpx.ReadTimeout("lost acknowledgement")
            return result
        with patch.object(HindsightMemory, "_request", side_effect=uncertain):
            self.assertEqual(self.memory.sync()["status"], "unavailable")
        self.assertIn(source["id"], self.remote)
        self.brain.delete_document(source["id"])
        with patch.object(HindsightMemory, "_request", side_effect=self.request):
            self.assertEqual(HindsightMemory(self.brain).sync()["processed"], 1)
        self.assertEqual(self.remote, {})

    def test_recall_uses_current_markdown_and_real_brain_search(self):
        source = self.brain.write("memory", "OS", "Ich arbeite unter Linux")
        with patch.object(HindsightMemory, "_request", side_effect=self.request):
            self.memory.sync()
            results = self.brain.search("Welches Betriebssystem bevorzugt man?")
        self.assertEqual(results[0]["id"], source["id"])
        self.assertEqual(results[0]["retrieval"], "hindsight")
        self.assertNotIn("FAKE", results[0]["snippet"])

    def test_remote_ranking_cannot_displace_exact_local_match(self):
        unrelated = self.brain.write("memory", "Stimme", "Weibliche Stimme")
        wanted = self.brain.write("memory", "Docker", "Docker-Neustart repariert")
        with patch.object(HindsightMemory, "_request", side_effect=self.request):
            self.memory.sync()
            # Remote service ranks the unrelated source first in insertion order.
            result = self.brain.search("Docker-Neustart", limit=2)
        self.assertEqual(result[0]["id"], wanted["id"])

    def test_outage_and_filtered_search_keep_local_results(self):
        source = self.brain.write("memory", "Linux", "Linux ist mein Betriebssystem")
        with patch.object(HindsightMemory, "_request", side_effect=self.request):
            self.memory.sync()
        with patch.object(HindsightMemory, "_request", side_effect=httpx.ConnectError("offline")):
            self.assertEqual(self.brain.search("Linux")[0]["id"], source["id"])
        with patch.object(HindsightMemory, "_request") as request:
            self.brain.search("Linux", kind="memory")
            request.assert_not_called()

    def test_reflect_requires_current_verifiable_sources(self):
        source = self.brain.write("memory", "OS", "Linux")
        with patch.object(HindsightMemory, "_request", side_effect=self.request):
            self.assertEqual(self.memory.reflect("OS")["status"], "pending")
            self.memory.sync()
            response = self.memory.reflect("OS")
        self.assertEqual(response["sources"], [source["id"]])
        self.assertTrue(response["inferred"])
        with patch.object(HindsightMemory, "_request", return_value={"text": "Guess", "based_on": {"memories": [{"document_id": "unknown"}]}}):
            self.assertEqual(self.memory.reflect("OS")["status"], "unverified")
        self.assertEqual(len(self.brain.documents()), 1)

    def test_revocation_during_recall_and_reflection(self):
        source = self.brain.write("memory", "OS", "Linux")
        with patch.object(HindsightMemory, "_request", side_effect=self.request):
            self.memory.sync()
        def revoked(method, suffix, payload=None, **kwargs):
            result = self.request(method, suffix, payload, **kwargs)
            self.brain.delete_document(source["id"])
            return result
        with patch.object(HindsightMemory, "_request", side_effect=revoked):
            self.assertEqual(self.memory.recall("OS"), [])

    def test_http_contract_headers_and_no_redirects(self):
        captured = []
        def handler(request):
            captured.append(request)
            return httpx.Response(200, json={"results": []})
        real_client = httpx.Client
        with patch.dict(os.environ, {"MICA_HINDSIGHT_API_KEY": "test-key"}), patch(
            "services.common.hindsight.httpx.Client",
            side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
        ):
            self.memory._request("POST", "memories/recall", {"query": "Linux", "max_tokens": 1200})
        self.assertEqual(str(captured[0].url), "http://127.0.0.1:8888/v1/default/banks/test/memories/recall")
        self.assertEqual(captured[0].headers["Authorization"], "Bearer test-key")
        self.assertEqual(json.loads(captured[0].content)["max_tokens"], 1200)

    def test_real_http_roundtrip_sync_recall_reflect_correction_and_deletion(self):
        remote = {}
        requests = []
        offline = [False]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def respond(self, status, data):
                encoded = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
            def do_DELETE(self):
                requests.append(self.path)
                key = self.path.rsplit("/", 1)[-1]
                existed = key in remote
                remote.pop(key, None)
                self.respond(200 if existed else 404, {"success": existed})
            def do_POST(self):
                requests.append(self.path)
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if offline[0]:
                    self.respond(503, {"detail": "unavailable"})
                elif self.path.endswith("/memories/recall"):
                    self.respond(200, {"results": [{"id": "fact", "document_id": key, "text": value["content"]} for key, value in remote.items()]})
                elif self.path.endswith("/memories"):
                    for item in body["items"]:
                        remote[item["document_id"]] = item
                    self.respond(200, {"success": True, "items_count": len(body["items"])})
                elif self.path.endswith("/reflect"):
                    self.respond(200, {"text": "Rückblick", "based_on": {"memories": [{"id": "fact", "document_id": key, "text": value["content"]} for key, value in remote.items()]}})
                else:
                    self.respond(404, {})
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {"MICA_HINDSIGHT_URL": f"http://127.0.0.1:{server.server_port}"}):
                memory = HindsightMemory(self.brain)
                source = self.brain.write("memory", "OS", "Linux")
                self.assertEqual(memory.sync()["status"], "ready")
                self.assertEqual(memory.recall("Betriebssystem")[0]["id"], source["id"])
                self.assertEqual(memory.reflect("OS")["status"], "ready")
                self.assertEqual(HindsightMemory(self.brain).sync()["processed"], 0)
                offline[0] = True
                self.assertEqual(self.brain.search("Linux")[0]["id"], source["id"])
                offline[0] = False
                self.brain.update_document(source["id"], "Windows")
                self.assertEqual(memory.sync()["status"], "ready")
                self.assertEqual(remote[source["id"]]["content"], "Windows")
                self.brain.delete_document(source["id"])
                self.assertEqual(memory.sync()["status"], "ready")
                self.assertEqual(remote, {})
                self.assertTrue(all(path.startswith("/v1/default/banks/test/") for path in requests))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_unconfirmed_ingestion_and_malformed_response_fail_closed(self):
        self.brain.write("memory", "OS", "Linux")
        with patch.object(HindsightMemory, "_request", return_value={"success": False}):
            self.assertEqual(self.memory.sync()["status"], "unavailable")
            self.assertEqual(self.memory.status()["status"], "pending")
        with patch.object(HindsightMemory, "_request", side_effect=self.request), patch("services.common.hindsight.time.time", return_value=9999999999):
            self.memory.sync()
        with patch.object(HindsightMemory, "_request", return_value={"results": None}):
            self.assertEqual(self.memory.recall("OS"), [])
        with patch.object(HindsightMemory, "_request", return_value={"text": "bad", "based_on": []}):
            self.assertEqual(self.memory.reflect("OS")["status"], "unverified")

    def test_failed_source_backoff_does_not_starve_other_sources(self):
        first = self.brain.write("memory", "Bad source", "Linux")
        second = self.brain.write("memory", "Good source", "Windows")
        def fail_first(method, suffix, payload=None, **kwargs):
            if suffix == "memories" and payload["items"][0]["document_id"] == first["id"]:
                raise httpx.ReadTimeout("bad source")
            return self.request(method, suffix, payload, **kwargs)
        with patch.object(HindsightMemory, "_request", side_effect=fail_first):
            self.assertEqual(self.memory.sync(limit=1)["status"], "unavailable")
            self.assertEqual(HindsightMemory(self.brain).sync(limit=1)["processed"], 1)
        self.assertIn(second["id"], self.remote)

    def test_completed_task_reports_have_source_links_and_skip_secrets(self):
        class Audit:
            def append(self, *args):
                pass
        orchestrator = Orchestrator(self.brain, Audit(), None)
        source = orchestrator.record_outcome("task", "docker.status", True, "Container läuft")
        selected = self.memory.sources()[source["id"]]
        self.assertIn("Werkzeugbericht", selected["item"]["content"])
        self.assertIn("Container läuft", selected["item"]["content"])
        self.assertIn("evidence_document", selected["doc"])
        secret = orchestrator.record_outcome("task", "docker.status", False, "password=hidden")
        self.assertNotIn(secret["id"], self.memory.sources())

    def test_api_confirmation_chat_and_reflect_routes(self):
        root = Path(self.temp.name)
        env = {
            "BRAIN_DIR": str(self.brain.root), "INDEX_PATH": str(self.brain.index_path),
            "AUDIT_PATH": str(root / "audit.jsonl"), "APPROVAL_DB": str(root / "approvals.sqlite3"),
            "SCHEDULE_DB": str(root / "schedules.sqlite3"), "IMPROVEMENT_DB": str(root / "improvements.sqlite3"),
            "IMPROVEMENT_WORKSPACE": str(root / "improvements"), "CONNECTOR_DB": str(root / "connectors.sqlite3"),
            "OPERATIONS_DB": str(root / "operations.sqlite3"), "TURN_BUDGET_DB": str(root / "turn-budget.sqlite3"),
            "MICA_PROFILE_PATH": str(root / "profile.json"), "MICA_APPROVAL_SECRET": "test-memory-secret",
            "MICA_LLM_PROVIDER": "ollama",
        }
        with patch.dict(os.environ, env):
            module = importlib.reload(importlib.import_module("services.api.app"))
            with TestClient(module.app) as client, patch.object(module, "_local_completion", return_value="Erfundene Antwort"), patch.object(HindsightMemory, "_request", side_effect=self.request):
                self.assertEqual(client.post("/v1/memory/hindsight/sync").status_code, 401)
                response = client.post("/v1/chat", json={"message": "Ich bevorzuge Linux"})
                self.assertEqual(response.status_code, 200)
                summary = next(iter(HindsightMemory(module.brain).sources().values()))
                self.assertNotIn("Erfundene Antwort", summary["item"]["content"])
                self.assertEqual(client.post("/v1/auth/approval-session", json={"secret": "test-memory-secret"}).status_code, 200)
                headers = {"X-Mica-Approval-Intent": "confirm"}
                synced = client.post("/v1/memory/hindsight/sync", headers=headers)
                self.assertEqual(synced.json()["status"], "ready")
                reflected = client.post("/v1/memory/hindsight/reflect", json={"message": "Was weißt du?"})
                self.assertEqual(reflected.json()["status"], "ready")
                with patch.object(HindsightMemory, "reflect", return_value={"status": "ready", "text": "Rückblick", "sources": [summary["doc"]["id"]]}) as reflect:
                    client.post("/v1/chat", json={"message": "Rückblick: Welche Entscheidungen haben wir getroffen?"})
                    reflect.assert_called_once()
                # The second chat is an independent source; remove it through
                # the same confirmed API so all remote deletions are checked.
                other = next(doc for doc in module.brain.documents() if doc["id"] != summary["doc"]["id"])
                client.delete(f"/v1/brain/documents/{other['id']}", headers=headers)
                key = summary["doc"]["id"]
                self.assertEqual(client.patch(f"/v1/brain/documents/{key}", json={"body": "Korrigiert"}).status_code, 401)
                corrected = client.patch(f"/v1/brain/documents/{key}", json={"body": "Nutzer: Ich bevorzuge Windows", "memory_excerpt": "Ich bevorzuge Windows"}, headers=headers)
                self.assertEqual(corrected.status_code, 200)
                self.assertEqual(corrected.json()["hindsight"]["status"], "pending")
                client.post("/v1/memory/hindsight/sync", headers=headers)
                self.assertEqual(self.remote[key]["content"], "Ich bevorzuge Windows")
                self.assertEqual(client.delete(f"/v1/brain/documents/{key}", headers=headers).status_code, 200)
                client.post("/v1/memory/hindsight/sync", headers=headers)
                self.assertEqual(self.remote, {})
                with patch.object(module.policy, "is_emergency_stopped", return_value=True):
                    self.assertEqual(client.post("/v1/memory/hindsight/reflect", json={"message": "Hallo"}).status_code, 409)

    def test_cloud_context_gate_skips_both_memory_reads(self):
        root = Path(self.temp.name)
        env = {
            "BRAIN_DIR": str(self.brain.root), "INDEX_PATH": str(self.brain.index_path),
            "AUDIT_PATH": str(root / "audit.jsonl"), "APPROVAL_DB": str(root / "approvals.sqlite3"),
            "SCHEDULE_DB": str(root / "schedules.sqlite3"), "IMPROVEMENT_DB": str(root / "improvements.sqlite3"),
            "IMPROVEMENT_WORKSPACE": str(root / "improvements"), "CONNECTOR_DB": str(root / "connectors.sqlite3"),
            "OPERATIONS_DB": str(root / "operations.sqlite3"), "TURN_BUDGET_DB": str(root / "turn-budget.sqlite3"),
            "MICA_PROFILE_PATH": str(root / "profile.json"), "MICA_LLM_PROVIDER": "openai_api",
            "MICA_CLOUD_ALLOW_PRIVATE_CONTEXT": "0",
        }
        with patch.dict(os.environ, env):
            module = importlib.reload(importlib.import_module("services.api.app"))
            with TestClient(module.app) as client, patch.object(module, "_local_completion", return_value="Hallo"), patch.object(HindsightMemory, "recall") as recall, patch.object(HindsightMemory, "reflect") as reflect:
                result = client.post("/v1/chat", json={"message": "Hallo", "memory_mode": "reflect"})
                self.assertEqual(result.status_code, 200)
                recall.assert_not_called()
                reflect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
