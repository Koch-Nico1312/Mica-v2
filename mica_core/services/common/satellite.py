"""Satellite registry and room presence manager for MICA Phase 4.5.

Enables physical presence anchors (e.g. Raspberry Pi room satellites) with
heartbeat tracking, hardware telemetry, and room-specific voice announcements.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SatelliteRegistry:
    """Manages physical room satellites and announcement queues."""

    def __init__(self, db_path: str | Path, heartbeat_timeout_seconds: int = 45):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds

        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS satellites (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    room TEXT NOT NULL,
                    ip_address TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL, -- 'online', 'offline', 'error'
                    capabilities_json TEXT NOT NULL DEFAULT '["mic", "speaker"]',
                    telemetry_json TEXT NOT NULL DEFAULT '{}',
                    last_seen_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS satellite_announcements (
                    id TEXT PRIMARY KEY,
                    satellite_id TEXT, -- NULL means broadcast to all
                    message TEXT NOT NULL,
                    priority TEXT NOT NULL DEFAULT 'normal',
                    status TEXT NOT NULL, -- 'pending', 'delivered', 'expired'
                    created_at TEXT NOT NULL,
                    delivered_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_satellites_status ON satellites(status, last_seen_at);
                CREATE INDEX IF NOT EXISTS idx_satellite_announcements_pending ON satellite_announcements(satellite_id, status);
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=5, isolation_level=None)
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
        finally:
            conn.close()

    def register(
        self,
        satellite_id: str,
        name: str,
        room: str,
        ip_address: str = "",
        capabilities: list[str] | None = None,
    ) -> dict[str, Any]:
        now = _now()
        caps = capabilities or ["mic", "speaker"]
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO satellites (id, name, room, ip_address, status, capabilities_json, telemetry_json, last_seen_at, created_at) "
                "VALUES (?, ?, ?, ?, 'online', ?, '{}', ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, room=excluded.room, ip_address=excluded.ip_address, "
                "status='online', capabilities_json=excluded.capabilities_json, last_seen_at=excluded.last_seen_at",
                (satellite_id, name, room, ip_address, json.dumps(caps), now, now),
            )
        return {
            "id": satellite_id,
            "name": name,
            "room": room,
            "ip_address": ip_address,
            "status": "online",
            "capabilities": caps,
            "last_seen_at": now,
        }

    def heartbeat(
        self,
        satellite_id: str,
        telemetry: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Update heartbeat timestamp and return pending announcements."""
        now = _now()
        telemetry_json = json.dumps(telemetry or {}, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                "UPDATE satellites SET status='online', last_seen_at=?, telemetry_json=? WHERE id=?",
                (now, telemetry_json, satellite_id),
            )
            # Fetch pending announcements for this satellite or broadcast
            rows = conn.execute(
                "SELECT id, message, priority, created_at FROM satellite_announcements "
                "WHERE (satellite_id = ? OR satellite_id IS NULL) AND status = 'pending' "
                "ORDER BY created_at ASC LIMIT 10",
                (satellite_id,),
            ).fetchall()

            announcements = []
            for r in rows:
                announcements.append({
                    "id": r[0],
                    "message": r[1],
                    "priority": r[2],
                    "created_at": r[3],
                })
        return announcements

    def queue_announcement(
        self,
        satellite_id: str | None,
        message: str,
        priority: str = "normal",
    ) -> dict[str, Any]:
        msg_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO satellite_announcements (id, satellite_id, message, priority, status, created_at) "
                "VALUES (?, ?, ?, ?, 'pending', ?)",
                (msg_id, satellite_id, message, priority, now),
            )
        return {
            "id": msg_id,
            "satellite_id": satellite_id,
            "message": message,
            "priority": priority,
            "status": "pending",
            "created_at": now,
        }

    def mark_announcement_delivered(self, announcement_id: str) -> bool:
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE satellite_announcements SET status='delivered', delivered_at=? WHERE id=?",
                (now, announcement_id),
            )
            return cur.rowcount > 0

    def list_satellites(self) -> list[dict[str, Any]]:
        now_dt = datetime.now(UTC)
        timeout = timedelta(seconds=self.heartbeat_timeout_seconds)

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, room, ip_address, status, capabilities_json, telemetry_json, last_seen_at, created_at "
                "FROM satellites ORDER BY room, name"
            ).fetchall()

        results = []
        for r in rows:
            try:
                last_dt = datetime.fromisoformat(r[7])
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=UTC)
                is_alive = (now_dt - last_dt) <= timeout
            except Exception:
                is_alive = False

            status = "online" if is_alive else "offline"
            try:
                caps = json.loads(r[5])
            except Exception:
                caps = []
            try:
                telem = json.loads(r[6])
            except Exception:
                telem = {}

            results.append({
                "id": r[0],
                "name": r[1],
                "room": r[2],
                "ip_address": r[3],
                "status": status,
                "capabilities": caps,
                "telemetry": telem,
                "last_seen_at": r[7],
                "created_at": r[8],
            })
        return results

    def get_satellite(self, satellite_id: str) -> dict[str, Any] | None:
        all_nodes = self.list_satellites()
        for node in all_nodes:
            if node["id"] == satellite_id:
                return node
        return None
