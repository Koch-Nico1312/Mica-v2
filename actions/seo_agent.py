"""OpenSEO bridge: SEO workflows via the Model Context Protocol.

OpenSEO (https://github.com/every-app/open-seo) exposes keyword research, rank
tracking, competitor insights, backlinks, site audits and AI visibility over
MCP, either self-hosted (Docker) or hosted at openseo.so. SEO data itself is
billed by DataForSEO, so this adapter adds hard cost control:

- Disabled unless MICA_OPENSEO_ENABLED=1 and an OpenSEO URL is configured.
- The DataForSEO API key lives in the OS keyring (never in config files or
  memory dumps); MICA only ever references it by name.
- Every MCP request consumes a locally persisted daily budget
  (MICA_OPENSEO_DAILY_BUDGET); when exhausted, requests are refused until the
  next day.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

WORKFLOWS = {
    "keyword_research": "Keywords for a topic or seed term",
    "rank_tracking": "Rankings for a domain and keywords",
    "competitor_insights": "Competing domains for a topic",
    "backlinks": "Backlink profile of a domain",
    "site_audit": "Technical audit findings for a site",
    "ai_visibility": "Brand visibility in AI answers",
}
KEYRING_SERVICE = "mica-openseo"
KEYRING_USER = "dataforseo-api-key"


def enabled() -> bool:
    return os.getenv("MICA_OPENSEO_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def server_url() -> str:
    return os.getenv("MICA_OPENSEO_URL", "").strip().rstrip("/")


def daily_budget() -> int:
    try:
        return max(0, int(os.getenv("MICA_OPENSEO_DAILY_BUDGET", "20")))
    except ValueError:
        return 20


class BudgetStore:
    """Local, durable per-day request counter for paid SEO API calls."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.getenv("MICA_OPENSEO_DB", "connectors.sqlite3"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS openseo_budget ("
                "day TEXT PRIMARY KEY, used INTEGER NOT NULL)"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Always close the connection: an open handle blocks Windows from
        deleting the database file (e.g. during test cleanup)."""
        conn = sqlite3.connect(self.path, timeout=10)
        conn.execute("PRAGMA busy_timeout = 10000")
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _today() -> str:
        return datetime.now(UTC).date().isoformat()

    def used_today(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT used FROM openseo_budget WHERE day = ?", (self._today(),)).fetchone()
        return int(row[0]) if row else 0

    def consume(self, amount: int = 1) -> bool:
        """Atomically take budget for one request; False when exhausted."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO openseo_budget(day, used) VALUES(?, 0) ON CONFLICT(day) DO NOTHING",
                (self._today(),),
            )
            row = conn.execute("SELECT used FROM openseo_budget WHERE day = ?", (self._today(),)).fetchone()
            used = int(row[0]) if row else 0
            if used + amount > daily_budget():
                conn.execute("COMMIT")
                return False
            conn.execute("UPDATE openseo_budget SET used = used + ? WHERE day = ?", (amount, self._today()))
            conn.execute("COMMIT")
            return True


def store_api_key(api_key: str) -> str:
    """Persist the DataForSEO key in the OS keyring; nothing is written to disk."""
    try:
        import keyring
    except Exception as error:
        return f"seo: keyring unavailable ({error}); key was NOT stored."
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, api_key.strip())
        return "seo: DataForSEO API key stored in the OS keyring."
    except Exception as error:
        return f"seo: storing the key failed ({error}). It was NOT saved."


def _load_api_key() -> str | None:
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or None
    except Exception:
        return None


def _mcp_call(workflow: str, params: dict[str, Any], budget: BudgetStore, timeout: int = 45) -> dict[str, Any]:
    """One JSON-RPC tools/call against the OpenSEO MCP endpoint."""
    import httpx

    url = server_url()
    if not url.startswith(("http://", "https://")):
        raise ValueError("MICA_OPENSEO_URL must be an http(s) endpoint")
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    api_key = _load_api_key()
    if api_key:
        headers["X-DataForSEO-API-Key"] = api_key
    payload = {
        "jsonrpc": "2.0", "id": uuid.uuid4().hex,
        "method": "tools/call",
        "params": {"name": workflow, "arguments": params},
    }
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=5.0), trust_env=False) as client:
        response = client.post(url + "/mcp", json=payload, headers=headers)
        response.raise_for_status()
        text = response.text.strip()
        if text.startswith("event:") or text.startswith("data:"):
            for line in text.splitlines():
                if line.startswith("data:"):
                    return json.loads(line[5:].strip())
            raise ValueError("OpenSEO returned an empty SSE event")
        return response.json()


def seo_action(parameters: dict[str, Any], response: Any = None, player: Any = None) -> str:
    """MICA tool entry point for the OpenSEO workflows."""
    workflow = str(parameters.get("workflow", "")).strip()
    query = str(parameters.get("query", "")).strip()
    domain = str(parameters.get("domain", "")).strip()
    if not enabled():
        return "seo: disabled. Set MICA_OPENSEO_ENABLED=1 and configure MICA_OPENSEO_URL to enable."
    if not server_url():
        return "seo: MICA_OPENSEO_URL is not configured (self-hosted OpenSEO or https://openseo.so/mcp)."
    if workflow == "set_key":
        key = str(parameters.get("api_key", "")).strip()
        if not key:
            return "seo: api_key parameter is empty; nothing stored."
        return store_api_key(key)
    if workflow not in WORKFLOWS:
        return "seo: unknown workflow. Use one of: " + ", ".join(sorted(WORKFLOWS))
    if not query and not domain:
        return "seo: a 'query' or 'domain' parameter is required."

    budget = BudgetStore()
    if not budget.consume(1):
        return (
            f"seo: daily DataForSEO budget exhausted ({budget.used_today()}/{daily_budget()}). "
            "Raise MICA_OPENSEO_DAILY_BUDGET or wait for the next day."
        )
    params: dict[str, Any] = {}
    if query:
        params["query"] = query[:300]
    if domain:
        params["domain"] = domain[:200]
    try:
        result = _mcp_call(workflow, params, budget)
    except Exception as error:
        return f"seo: request failed ({error})."
    content = result.get("result", {}).get("content") if isinstance(result, dict) else None
    if isinstance(content, list) and content and isinstance(content[0], dict) and "text" in content[0]:
        text = str(content[0]["text"])
        return f"seo[{workflow}]: {text[:3000]}"
    return f"seo[{workflow}]: " + json.dumps(result, ensure_ascii=False)[:3000]
