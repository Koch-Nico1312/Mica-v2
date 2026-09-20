from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from actions.seo_agent import (
    BudgetStore,
    budget_db_path,
    daily_budget,
    enabled,
    seo_action,
    store_api_key,
    validated_endpoint,
)


class OpenSeoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.previous = {key: os.environ.get(key) for key in (
            "MICA_OPENSEO_ENABLED", "MICA_OPENSEO_URL", "MICA_OPENSEO_DAILY_BUDGET", "MICA_OPENSEO_DB",
        )}
        os.environ.pop("MICA_OPENSEO_ENABLED", None)
        os.environ.pop("MICA_OPENSEO_URL", None)
        os.environ["MICA_OPENSEO_DAILY_BUDGET"] = "2"
        os.environ["MICA_OPENSEO_DB"] = str(self.root / "connectors.sqlite3")

    def tearDown(self) -> None:
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temporary.cleanup()

    def test_disabled_by_default(self) -> None:
        self.assertFalse(enabled())
        self.assertIn("disabled", seo_action({"workflow": "keyword_research", "query": "seo"}))

    def test_missing_url_is_reported(self) -> None:
        os.environ["MICA_OPENSEO_ENABLED"] = "1"
        self.assertIn("MICA_OPENSEO_URL", seo_action({"workflow": "keyword_research", "query": "seo"}))

    def test_unknown_workflow_is_refused(self) -> None:
        os.environ["MICA_OPENSEO_ENABLED"] = "1"
        os.environ["MICA_OPENSEO_URL"] = "https://openseo.example"
        self.assertIn("unknown workflow", seo_action({"workflow": "nuke", "query": "x"}))

    def test_budget_is_persisted_and_enforced(self) -> None:
        budget = BudgetStore(self.root / "budget.sqlite3")
        self.assertTrue(budget.consume(1))
        self.assertTrue(budget.consume(1))
        self.assertFalse(budget.consume(1))
        self.assertEqual(budget.used_today(), 2)
        # Persistence across instances (separate API workers).
        self.assertEqual(BudgetStore(self.root / "budget.sqlite3").used_today(), 2)

    def test_exhausted_budget_blocks_request_before_network(self) -> None:
        os.environ["MICA_OPENSEO_ENABLED"] = "1"
        os.environ["MICA_OPENSEO_URL"] = "https://openseo.example"
        with patch("actions.seo_agent.BudgetStore") as store:
            store.return_value.consume.return_value = False
            store.return_value.used_today.return_value = 2
            result = seo_action({"workflow": "keyword_research", "query": "seo"})
        self.assertIn("budget exhausted", result)

    def test_mcp_payload_is_json_rpc_tools_call(self) -> None:
        import actions.seo_agent as module

        captured: dict = {}

        class FakeResponse:
            def __init__(self):
                self.text = '{"result": {"content": [{"text": "ok"}]}}'

            def raise_for_status(self):
                return None

            def json(self):
                import json as _json

                return _json.loads(self.text)

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, url, json=None, headers=None):
                captured["url"] = url
                captured["json"] = json
                return FakeResponse()

        os.environ["MICA_OPENSEO_URL"] = "https://openseo.example"
        try:
            with patch("httpx.Client", FakeClient):
                result = module._mcp_call("keyword_research", {"query": "seo"}, BudgetStore())
        finally:
            os.environ.pop("MICA_OPENSEO_URL", None)
        self.assertEqual(result["result"]["content"][0]["text"], "ok")
        self.assertTrue(captured["url"].endswith("/mcp"))
        self.assertEqual(captured["json"]["method"], "tools/call")
        self.assertEqual(captured["json"]["params"]["name"], "keyword_research")

    def test_plaintext_endpoint_is_refused_outside_loopback(self) -> None:
        os.environ["MICA_OPENSEO_ENABLED"] = "1"
        os.environ["MICA_OPENSEO_URL"] = "http://openseo.example"
        with self.assertRaises(ValueError):
            validated_endpoint()
        with patch("actions.seo_agent.BudgetStore") as store:
            result = seo_action({"workflow": "keyword_research", "query": "seo"})
        # The key must never travel in cleartext, and no budget is burned on a
        # misconfigured endpoint.
        self.assertIn("https", result)
        store.return_value.consume.assert_not_called()

    def test_loopback_and_https_endpoints_are_allowed(self) -> None:
        for url in ("http://127.0.0.1:3000", "http://localhost:3000", "https://openseo.example"):
            with self.subTest(url=url):
                os.environ["MICA_OPENSEO_URL"] = url
                self.assertEqual(validated_endpoint(), url)
        for url in ("ftp://openseo.example", "https://", "openseo.example"):
            with self.subTest(url=url):
                os.environ["MICA_OPENSEO_URL"] = url.rstrip("/")
                with self.assertRaises(ValueError):
                    validated_endpoint()

    def test_budget_db_path_ignores_the_working_directory(self) -> None:
        os.environ.pop("MICA_OPENSEO_DB", None)
        before = budget_db_path()
        self.assertTrue(before.is_absolute())
        self.assertEqual(before.name, "connectors.sqlite3")
        cwd = os.getcwd()
        try:
            os.chdir(self.root)
            self.assertEqual(budget_db_path(), before)
        finally:
            os.chdir(cwd)
        os.environ["MICA_OPENSEO_DB"] = str(self.root / "explicit.sqlite3")
        self.assertEqual(budget_db_path(), self.root / "explicit.sqlite3")

    def test_store_api_key_without_keyring_reports_clearly(self) -> None:
        with patch.dict(sys.modules, {"keyring": None}):
            result = store_api_key("secret")
        self.assertIn("keyring", result.lower())
        self.assertIn("NOT", result)


if __name__ == "__main__":
    unittest.main()
