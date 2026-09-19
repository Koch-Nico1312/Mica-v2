from __future__ import annotations

import importlib
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "mica_core"
sys.path.insert(0, str(CORE))

from services.common.brain import MarkdownBrain
from services.common.learning import (
    DomainRegistry, LearningService, SafeWebClient, _BingResultParser, _DDGResultParser,
    parse_research_command,
)
from services.common.scheduler_store import ScheduleStore


class FakeFetcher:
    def fetch(self, url: str, _hosts: list[str]) -> dict[str, str]:
        return {"url": url, "text": "Belegter offizieller Dokumentationstext. " * 20}


def fake_search(_query: str, hosts: list[str], max_results: int) -> list[dict[str, str]]:
    return [
        {"title": f"Quelle {index}", "url": f"https://{hosts[0]}/guide-{index}", "snippet": ""}
        for index in range(1, max_results + 1)
    ]


class Phase2LearningUnitTests(unittest.TestCase):
    def test_default_domains_and_command_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            registry = DomainRegistry(Path(temporary) / "domains.json")
            self.assertEqual([item["id"] for item in registry.all()], ["it-programmierung", "server-homelab"])
            self.assertEqual(
                parse_research_command(
                    "Informier dich über FastAPI Sicherheit im Lernfeld IT/Programmierung.", registry,
                ),
                ("FastAPI Sicherheit", "it-programmierung"),
            )
            self.assertEqual(
                parse_research_command("Informier dich über Backups im Lernfeld unbekannt", registry),
                ("Backups", ""),
            )

    def test_domain_updates_reject_urls_and_invalid_hosts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            registry = DomainRegistry(Path(temporary) / "domains.json")
            updated = registry.update("it-programmierung", {"source_hosts": ["docs.python.org"]})
            self.assertEqual(updated["source_hosts"], ["docs.python.org"])
            with self.assertRaises(ValueError):
                registry.update("it-programmierung", {"source_hosts": ["https://docs.python.org/path"]})

    def test_safe_web_client_blocks_private_and_non_https_targets(self) -> None:
        client = SafeWebClient()
        with patch.object(socket, "getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaises(ValueError):
                client.validate_url("https://docs.python.org/3/", ["docs.python.org"])
        with self.assertRaises(ValueError):
            client.validate_url("http://docs.python.org/3/", ["docs.python.org"])
        with self.assertRaises(ValueError):
            client.validate_url("https://user:pass@docs.python.org/", ["docs.python.org"])

    def test_search_parser_extracts_direct_and_redirected_https_results(self) -> None:
        parser = _DDGResultParser()
        parser.feed(
            '<a class="result__a" href="https://docs.python.org/3/">Python Docs</a>'
            '<a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.docker.com%2Fmanual">Docker Docs</a>'
        )
        self.assertEqual(parser.results[0]["url"], "https://docs.python.org/3/")
        self.assertEqual(parser.results[1]["url"], "https://docs.docker.com/manual")
        bing = _BingResultParser()
        bing.feed('<li class="b_algo"><h2><a href="https://docs.python.org/3/library/typing.html">typing</a></h2></li>')
        self.assertEqual(bing.results, [{
            "title": "typing", "url": "https://docs.python.org/3/library/typing.html", "snippet": "",
        }])
        redirected = _BingResultParser()
        redirected.feed('<li class="b_algo"><h2><a href="https://www.bing.com/ck/a?u=a1aHR0cHM6Ly9kb2NzLnB5dGhvbi5vcmcvMy8">docs</a></h2></li>')
        self.assertEqual(redirected.results[0]["url"], "https://docs.python.org/3/")

    def test_research_stores_cited_domain_markdown_and_scoped_search(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"MICA_LEARNING_NETWORK": "1"}):
            root = Path(temporary)
            brain = MarkdownBrain(root / "brain", root / "index.sqlite3")
            registry = DomainRegistry(root / "domains.json")
            service = LearningService(
                brain, registry,
                lambda _prompt: "## Kernaussagen\nDocker nutzt Healthchecks [1].\n\n## Widersprüche\nKeine erkannt\n\n## Unsicherheiten\nKeine erkannt\n\n## Offene Fragen\nKeine erkannt",
                searcher=fake_search, fetcher=FakeFetcher(),
            )
            result = service.research("Docker Healthchecks", "server-homelab", 2)
            self.assertEqual(result["status"], "completed")
            document = brain.documents()[0]
            self.assertEqual(document["domain_id"], "server-homelab")
            self.assertEqual(document["review_status"], "reviewed")
            self.assertEqual(len(document["source_urls"]), 2)
            self.assertEqual(brain.search("Healthchecks", domain_id="server-homelab")[0]["id"], document["id"])
            self.assertEqual(brain.search("Healthchecks", domain_id="it-programmierung"), [])

    def test_research_prompt_never_includes_existing_private_brain_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"MICA_LEARNING_NETWORK": "1"}):
            root = Path(temporary)
            brain = MarkdownBrain(root / "brain", root / "index.sqlite3")
            brain.write("conversations", "Privat", "PRIVATE-BRAIN-SECRET")
            captured: list[str] = []

            def summarize(prompt: str) -> str:
                captured.append(prompt)
                return "Kernaussagen\nFakt [1]\nWidersprüche\nKeine erkannt\nUnsicherheiten\nKeine erkannt\nOffene Fragen\nKeine erkannt"

            service = LearningService(
                brain, DomainRegistry(root / "domains.json"), summarize,
                searcher=fake_search, fetcher=FakeFetcher(),
            )
            service.research("Python Typing", "it-programmierung", 2)
            self.assertNotIn("PRIVATE-BRAIN-SECRET", captured[0])
            self.assertIn("INHALT (UNTRUSTED)", captured[0])

    def test_network_off_fails_closed_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"MICA_LEARNING_NETWORK": "0"}):
            root = Path(temporary)
            brain = MarkdownBrain(root / "brain", root / "index.sqlite3")
            service = LearningService(brain, DomainRegistry(root / "domains.json"), lambda _prompt: "no")
            with self.assertRaises(PermissionError):
                service.research("Docker Backup", "server-homelab")
            self.assertEqual(brain.documents(), [])

    def test_monitoring_is_gated_finite_and_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "MICA_LEARNING_NETWORK": "1", "MICA_LEARNING_MONITORING_ENABLED": "1",
        }):
            root = Path(temporary)
            brain = MarkdownBrain(root / "brain", root / "index.sqlite3")
            service = LearningService(
                brain, DomainRegistry(root / "domains.json"), lambda _prompt: "",
                searcher=fake_search, fetcher=FakeFetcher(),
            )
            first = service.monitor("Docker releases", "server-homelab", 2)
            second = service.monitor("Docker releases", "server-homelab", 2)
            self.assertEqual(first["status"], "draft")
            self.assertEqual(second["status"], "unchanged")
            self.assertEqual(len(brain.documents()), 1)
            store = ScheduleStore(root / "schedule.sqlite3")
            self.assertIn("learning.monitor", __import__("services.common.scheduler_store", fromlist=["SCHEDULABLE_ACTIONS"]).SCHEDULABLE_ACTIONS)


class Phase2LearningApiTests(unittest.TestCase):
    @staticmethod
    def environment(temporary: str) -> dict[str, str]:
        root = Path(temporary)
        return {
            "BRAIN_DIR": str(root / "brain"), "INDEX_PATH": str(root / "index.sqlite3"),
            "AUDIT_PATH": str(root / "audit.jsonl"), "APPROVAL_DB": str(root / "approvals.sqlite3"),
            "SCHEDULE_DB": str(root / "schedules.sqlite3"), "IMPROVEMENT_DB": str(root / "improvements.sqlite3"),
            "IMPROVEMENT_WORKSPACE": str(root / "improvements"), "CONNECTOR_DB": str(root / "connectors.sqlite3"),
            "LEARNING_DOMAINS_PATH": str(root / "domains.json"), "MICA_PROFILE_PATH": str(root / "profile.json"),
            "MICA_APPROVAL_SECRET": "phase2-test-secret", "MICA_LEARNING_NETWORK": "0",
            "MICA_LEARNING_MONITORING_ENABLED": "0",
        }

    def test_public_contracts_fail_closed_and_pwa_exposes_learning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, self.environment(temporary), clear=False):
            module = importlib.reload(importlib.import_module("services.api.app"))
            with TestClient(module.app) as client:
                domains = client.get("/v1/learning/domains")
                self.assertEqual(domains.status_code, 200)
                self.assertFalse(domains.json()["network_enabled"])
                self.assertEqual(len(domains.json()["domains"]), 2)
                blocked = client.post("/v1/learning/research", json={
                    "schema_version": 1, "topic": "Docker Backup", "domain_id": "server-homelab",
                })
                self.assertEqual(blocked.status_code, 403)
                self.assertEqual(client.post("/v1/learning/monitors", json={
                    "query": "Docker Releases", "domain_id": "server-homelab",
                }).status_code, 409)
                update_payload = {"source_hosts": ["docs.python.org"]}
                approval = client.patch("/v1/learning/domains/it-programmierung", json=update_payload)
                self.assertEqual(approval.status_code, 403)
                approval_id = approval.json()["detail"]["approval_id"]
                self.assertTrue(module.policy.resolve(approval_id, True))
                updated = client.patch("/v1/learning/domains/it-programmierung", json=update_payload)
                self.assertEqual(updated.status_code, 200)
                self.assertEqual(updated.json()["domain"]["source_hosts"], ["docs.python.org"])
                prompt = client.post("/v1/turns", json={
                    "message": "Informier dich über Docker im Lernfeld unbekannt", "client": "pwa",
                })
                self.assertIn("Bitte nenne", prompt.json()["reply"])

        html = (CORE / "web_ui" / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-view="learning"', html)
        self.assertIn("/v1/learning/research", html)
        self.assertIn("function loadLearning()", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
