"""Opt-in connector registry; secrets remain environment-owned, never in Markdown."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


CONNECTORS = {"telegram", "whatsapp", "push", "sip"}
REQUIRED_ENV = {
    "telegram": ("MICA_TELEGRAM_BOT_TOKEN",),
    "whatsapp": ("MICA_WHATSAPP_ACCESS_TOKEN", "MICA_WHATSAPP_PHONE_NUMBER_ID"),
    "push": ("MICA_PUSH_URL",),
    "sip": ("MICA_SIP_ARI_URL", "MICA_SIP_ARI_USER", "MICA_SIP_ARI_PASSWORD"),
}


class ConnectorRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS connectors (name TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS inbound_events ("
                "connector TEXT NOT NULL, provider_event_id TEXT NOT NULL, received_at TEXT NOT NULL, "
                "PRIMARY KEY (connector, provider_event_id))"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_inbound_events_received ON inbound_events(received_at)")
            for name in CONNECTORS:
                conn.execute("INSERT OR IGNORE INTO connectors(name, enabled) VALUES (?, 0)", (name,))

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path)
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _validate(name: str) -> str:
        if name not in CONNECTORS:
            raise ValueError("Connector is not supported")
        return name

    def set_enabled(self, name: str, enabled: bool) -> None:
        name = self._validate(name)
        with self._connect() as conn:
            conn.execute("UPDATE connectors SET enabled = ? WHERE name = ?", (int(enabled), name))

    def enabled(self, name: str) -> bool:
        name = self._validate(name)
        with self._connect() as conn:
            row = conn.execute("SELECT enabled FROM connectors WHERE name = ?", (name,)).fetchone()
        return bool(row and row[0])

    def list(self) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT name, enabled FROM connectors ORDER BY name").fetchall()
        return [
            {"name": name, "enabled": bool(enabled), "external": True,
             "configured": all(os.getenv(variable, "").strip() for variable in REQUIRED_ENV[name])}
            for name, enabled in rows
        ]

    def endpoint(self, name: str) -> str:
        name = self._validate(name)
        if not self.enabled(name):
            raise ValueError("Connector is disabled")
        endpoint_variable = {"push": "MICA_PUSH_URL", "sip": "MICA_SIP_ARI_URL"}.get(name, f"MICA_CONNECTOR_{name.upper()}_URL")
        endpoint = os.getenv(endpoint_variable, "").strip()
        if not endpoint:
            raise ValueError("Connector endpoint is not configured")
        return endpoint

    def claim_inbound_event(self, name: str, provider_event_id: str) -> bool:
        """Claim a provider event once after authentication has succeeded.

        Provider retries are normal.  Persisting only a non-secret event ID
        prevents duplicate Brain entries and duplicate planning while keeping
        webhook payloads and credentials out of the registry database.
        """
        name = self._validate(name)
        event_id = str(provider_event_id or "").strip()
        if not event_id or len(event_id) > 512:
            raise ValueError("Provider event id is invalid")
        received_at = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            # Bound the idempotency ledger even when a provider has a very
            # long-lived webhook.  Thirty days is far beyond normal retry
            # windows and does not affect connector enablement state.
            conn.execute(
                "DELETE FROM inbound_events WHERE received_at < datetime('now', '-30 days')"
            )
            result = conn.execute(
                "INSERT OR IGNORE INTO inbound_events(connector, provider_event_id, received_at) VALUES (?, ?, ?)",
                (name, event_id, received_at),
            )
        return result.rowcount == 1
