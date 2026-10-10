"""Direct, read-only Atlassian MCP client with Windows-owned credentials."""
from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

import requests

from desktop.core.secure_store import delete_secret, get_secret, set_secret

ENDPOINT = "https://mcp.atlassian.com/v2/mcp"
EMAIL_SECRET = "MICA_JIRA_EMAIL"
TOKEN_SECRET = "MICA_JIRA_TOKEN"
READ_TOOLS = frozenset({"getAccessibleAtlassianResources", "atlassianUserInfo",
                        "getJiraIssue", "searchJiraIssuesUsingJql"})
MAX_RESPONSE = 2 * 1024 * 1024


class JiraError(RuntimeError):
    """Safe user-facing error; server bodies and credentials are never included."""


def validate_email(email: str) -> str:
    email = email.strip()
    if len(email) > 254 or not re.fullmatch(r"[^\s:@]+@[^\s:@]+\.[^\s:@]+", email):
        raise JiraError("Bitte eine gültige Atlassian-E-Mail-Adresse eingeben.")
    return email


def save_account(email: str, token: str) -> None:
    email = validate_email(email)
    if not token.strip() or len(token) > 8192 or any(c.isspace() for c in token):
        raise JiraError("Bitte einen gültigen eingeschränkten Atlassian-API-Token eingeben.")
    # Preserve the old pair if storing the new account fails halfway through.
    old_email, old_token = get_secret(EMAIL_SECRET), get_secret(TOKEN_SECRET)
    try:
        set_secret(TOKEN_SECRET, token)
        set_secret(EMAIL_SECRET, email)
    except Exception:
        try:
            for name, old in ((EMAIL_SECRET, old_email), (TOKEN_SECRET, old_token)):
                if old is None:
                    delete_secret(name)
                else:
                    set_secret(name, old)
        except Exception:
            raise JiraError("Speichern und Wiederherstellen fehlgeschlagen. Jira-Zugang im Windows-Anmeldetresor prüfen.") from None
        raise JiraError("Zugangsdaten konnten nicht im Windows-Anmeldetresor gespeichert werden.") from None


def forget_account() -> None:
    delete_secret(TOKEN_SECRET)
    delete_secret(EMAIL_SECRET)


class JiraMcpClient:
    def __init__(self, email: str, token: str, session=None):
        self.email = validate_email(email)
        if not token or any(c.isspace() for c in token):
            raise JiraError("Der Atlassian-API-Token fehlt oder ist ungültig.")
        self.session = session or requests.Session()
        self.session.trust_env = False
        self.session.auth = (self.email, token)
        self.session.headers.update({"Accept": "application/json, text/event-stream",
                                     "Content-Type": "application/json"})
        self.initialized = False

    @classmethod
    def from_saved_account(cls):
        email, token = get_secret(EMAIL_SECRET), get_secret(TOKEN_SECRET)
        if not email or not token:
            raise JiraError("Zuerst Atlassian-E-Mail und API-Token verbinden.")
        return cls(email, token)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.session.close()

    def _rpc(self, method: str, params: dict, *, notification=False) -> dict:
        identifier = uuid.uuid4().hex
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            payload["id"] = identifier
        started = time.monotonic()
        try:
            with self.session.post(ENDPOINT, json=payload, timeout=(5, 30),
                                   allow_redirects=False, stream=True) as response:
                if response.status_code in {401, 403}:
                    raise JiraError("Atlassian verweigert den Zugriff. Token, Berechtigungen und MCP-Freigabe prüfen.")
                if not 200 <= response.status_code < 300:
                    raise JiraError(f"Atlassian ist derzeit nicht erreichbar (HTTP {response.status_code}).")
                if notification:
                    return {}
                session_id = response.headers.get("Mcp-Session-Id")
                if session_id:
                    if len(session_id) > 4096 or not all(33 <= ord(c) <= 126 for c in session_id):
                        raise JiraError("Ungültige Atlassian-Sitzung.")
                    self.session.headers["Mcp-Session-Id"] = session_id
                content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
                if content_type not in {"application/json", "text/event-stream"}:
                    raise JiraError("Atlassian hat ein unbekanntes Antwortformat geliefert.")
                size, raw, event = 0, bytearray(), []
                for line in response.iter_lines(chunk_size=1024):
                    size += len(line) + 1
                    if size > MAX_RESPONSE or time.monotonic() - started > 45:
                        raise JiraError("Atlassian-Antwort überschreitet das Größen- oder Zeitlimit.")
                    if content_type == "application/json":
                        raw.extend(line)
                        continue
                    if line.startswith(b"data:"):
                        event.append(line[5:].lstrip())
                    elif not line and event:
                        message = json.loads(b"\n".join(event))
                        event = []
                        if isinstance(message, dict) and message.get("id") == identifier:
                            return self._result(message, identifier)
                if content_type == "application/json":
                    return self._result(json.loads(raw), identifier)
                raise JiraError("Atlassian hat keine passende MCP-Antwort geliefert.")
        except (requests.RequestException, ValueError, TypeError):
            raise JiraError("Die sichere Atlassian-Verbindung ist fehlgeschlagen oder die Antwort ist ungültig.") from None

    @staticmethod
    def _result(message: Any, identifier: str) -> dict:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or message.get("id") != identifier:
            raise JiraError("Ungültige MCP-Antwort von Atlassian.")
        if "error" in message or not isinstance(message.get("result"), dict):
            raise JiraError("Atlassian konnte die Anfrage nicht ausführen. Berechtigungen und Eingaben prüfen.")
        result = message["result"]
        if result.get("isError"):
            raise JiraError("Das Jira-Werkzeug konnte die Anfrage nicht ausführen.")
        return result

    def initialize(self):
        if self.initialized:
            return
        result = self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                          "clientInfo": {"name": "MICA", "version": "2.0"}})
        version = result.get("protocolVersion")
        if version not in {"2025-06-18", "2025-03-26"}:
            raise JiraError("Diese MCP-Protokollversion wird von MICA noch nicht unterstützt.")
        self.session.headers["MCP-Protocol-Version"] = version
        self._rpc("notifications/initialized", {}, notification=True)
        self.initialized = True

    def call(self, name: str, arguments: dict | None = None):
        if name not in READ_TOOLS:
            raise JiraError("Dieses Jira-Werkzeug ist nicht zum Lesen freigegeben.")
        self.initialize()
        return self._rpc("tools/call", {"name": name, "arguments": arguments or {}})

    def resources(self):
        result = self.call("getAccessibleAtlassianResources")
        data = result.get("structuredContent")
        if data is None:
            for item in result.get("content", []):
                if isinstance(item, dict) and item.get("type") == "text":
                    try:
                        data = json.loads(item.get("text", ""))
                        break
                    except (ValueError, TypeError):
                        continue
        if isinstance(data, dict):
            data = data.get("resources", data.get("data"))
        if not isinstance(data, list):
            raise JiraError("Die Liste der Atlassian-Websites konnte nicht gelesen werden.")
        return [item for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)]

    def search(self, cloud_id: str, jql: str):
        if not cloud_id or not jql.strip() or len(jql) > 2000:
            raise JiraError("Website und Jira-Suchausdruck fehlen oder sind zu lang.")
        return self.call("searchJiraIssuesUsingJql", {"cloudId": cloud_id, "jql": jql.strip(),
                                                     "maxResults": 20})

    def issue(self, cloud_id: str, key: str):
        if not cloud_id or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*-\d+", key.strip()):
            raise JiraError("Bitte eine Jira-Vorgangsnummer wie MICA-123 eingeben.")
        return self.call("getJiraIssue", {"cloudId": cloud_id, "issueIdOrKey": key.strip().upper()})
