"""Ambient awareness and proactive alerting engine for MICA Phase 4.5.

Monitors environmental, server, schedule, and vision states continuously,
triggering proactive notifications with anti-spam cooldown, priority tiers,
and configurable quiet hours (DND).
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any, Iterator

SEVERITIES = ("info", "notice", "warning", "critical")
SEVERITY_ORDER = {"info": 0, "notice": 1, "warning": 2, "critical": 3}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _is_quiet_hours(
    start_hour: int = 23,
    end_hour: int = 7,
    now_moment: datetime | None = None,
) -> bool:
    """Check if the local time falls within configured quiet hours."""
    now = (now_moment or datetime.now()).astimezone()
    hour = now.hour
    if start_hour > end_hour:  # Crosses midnight (e.g. 23:00 to 07:00)
        return hour >= start_hour or hour < end_hour
    return start_hour <= hour < end_hour


class AmbientMonitor:
    """Evaluates environmental signals and manages proactive ambient notifications."""

    def __init__(
        self,
        db_path: str | Path,
        default_cooldown_seconds: int = 1800,
        quiet_hours_enabled: bool = True,
        quiet_start_hour: int = 23,
        quiet_end_hour: int = 7,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.default_cooldown_seconds = default_cooldown_seconds
        self.quiet_hours_enabled = quiet_hours_enabled
        self.quiet_start_hour = quiet_start_hour
        self.quiet_end_hour = quiet_end_hour

        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS ambient_events (
                    id TEXT PRIMARY KEY,
                    trigger_type TEXT NOT NULL,
                    code TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    target_id TEXT,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL, -- 'pending', 'delivered', 'acknowledged', 'suppressed'
                    created_at TEXT NOT NULL,
                    acknowledged_at TEXT
                );
                CREATE TABLE IF NOT EXISTS ambient_cooldowns (
                    key TEXT PRIMARY KEY,
                    last_triggered_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ambient_events_status ON ambient_events(status, created_at);
                CREATE INDEX IF NOT EXISTS idx_ambient_events_code ON ambient_events(code, created_at);
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

    def in_cooldown(self, key: str, cooldown_seconds: int | None = None) -> bool:
        cooldown = cooldown_seconds if cooldown_seconds is not None else self.default_cooldown_seconds
        now_dt = datetime.now(UTC)
        with self._connect() as conn:
            row = conn.execute("SELECT last_triggered_at FROM ambient_cooldowns WHERE key = ?", (key,)).fetchone()
            if not row:
                return False
            try:
                last_dt = datetime.fromisoformat(row[0])
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=UTC)
                return (now_dt - last_dt).total_seconds() < cooldown
            except Exception:
                return False

    def mark_cooldown(self, key: str) -> None:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO ambient_cooldowns(key, last_triggered_at) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET last_triggered_at = excluded.last_triggered_at",
                (key, now),
            )

    def trigger_event(
        self,
        trigger_type: str,
        code: str,
        title: str,
        message: str,
        severity: str = "notice",
        target_id: str | None = None,
        details: dict[str, Any] | None = None,
        cooldown_seconds: int | None = None,
    ) -> dict[str, Any] | None:
        """Trigger a proactive event with cooldown and quiet-hour handling."""
        if severity not in SEVERITIES:
            severity = "notice"

        cooldown_key = f"{trigger_type}:{code}:{target_id or 'global'}"
        if self.in_cooldown(cooldown_key, cooldown_seconds):
            return None

        # Quiet hours check: non-critical events are suppressed during quiet hours
        suppressed = False
        if self.quiet_hours_enabled and _is_quiet_hours(self.quiet_start_hour, self.quiet_end_hour):
            if SEVERITY_ORDER[severity] < SEVERITY_ORDER["critical"]:
                suppressed = True

        event_id = uuid.uuid4().hex
        now = _now()
        status = "suppressed" if suppressed else "pending"
        details_json = json.dumps(details or {}, ensure_ascii=False, sort_keys=True)

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO ambient_events (id, trigger_type, code, title, message, severity, target_id, details_json, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, trigger_type, code, title, message, severity, target_id, details_json, status, now),
            )

        self.mark_cooldown(cooldown_key)
        return {
            "id": event_id,
            "trigger_type": trigger_type,
            "code": code,
            "title": title,
            "message": message,
            "severity": severity,
            "target_id": target_id,
            "status": status,
            "created_at": now,
        }

    def evaluate_server_state(self, observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Proactively evaluate recent server metrics for anomalies and trends."""
        events: list[dict[str, Any]] = []
        if not observations:
            return events

        latest = observations[0]
        target = latest.get("target_id", "server")
        cpu = float(latest.get("cpu_percent") or 0.0)
        mem = float(latest.get("memory_percent") or 0.0)
        disk = float(latest.get("disk_percent") or 0.0)
        unhealthy = int(latest.get("unhealthy_count") or 0)
        restarts = int(latest.get("restart_count") or 0)

        if disk >= 90.0:
            ev = self.trigger_event(
                "server", "disk_critical",
                f"Kritischer Speicherplatz auf {target}",
                f"Der freie Speicherplatz auf {target} ist auf {disk:.1f}% gefallen.",
                severity="critical", target_id=target, details={"disk_percent": disk},
            )
            if ev:
                events.append(ev)
        elif disk >= 80.0:
            ev = self.trigger_event(
                "server", "disk_warning",
                f"Speicherplatz-Warnung auf {target}",
                f"Festplattenauslastung auf {target} liegt bei {disk:.1f}%.",
                severity="warning", target_id=target, details={"disk_percent": disk},
            )
            if ev:
                events.append(ev)

        if unhealthy > 0:
            ev = self.trigger_event(
                "server", "containers_unhealthy",
                f"Ungesunde Container auf {target}",
                f"{unhealthy} Container auf {target} melden Unhealthy-Zustand.",
                severity="critical", target_id=target, details={"unhealthy_count": unhealthy},
            )
            if ev:
                events.append(ev)

        if restarts > 3:
            ev = self.trigger_event(
                "server", "restart_loop",
                f"Neustart-Schleife auf {target}",
                f"Container auf {target} haben {restarts} Neustarts durchgeführt.",
                severity="warning", target_id=target, details={"restart_count": restarts},
            )
            if ev:
                events.append(ev)

        if cpu >= 90.0:
            ev = self.trigger_event(
                "server", "cpu_spike",
                f"Hohe CPU-Auslastung auf {target}",
                f"Die CPU-Auslastung auf {target} beträgt {cpu:.1f}%.",
                severity="warning", target_id=target, details={"cpu_percent": cpu},
            )
            if ev:
                events.append(ev)

        return events

    def evaluate_schedules(self, schedules: list[dict[str, Any]], notice_minutes: int = 15) -> list[dict[str, Any]]:
        """Evaluate impending calendar schedules / reminders."""
        events: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        window = timedelta(minutes=notice_minutes)

        for item in schedules:
            run_at_raw = item.get("run_at")
            if not run_at_raw:
                continue
            try:
                run_dt = datetime.fromisoformat(run_at_raw)
                if run_dt.tzinfo is None:
                    run_dt = run_dt.replace(tzinfo=UTC)
                delta = run_dt - now
                if timedelta(seconds=0) <= delta <= window:
                    sched_id = item.get("id", "")
                    name = item.get("name", "Termin")
                    ev = self.trigger_event(
                        "schedule", "upcoming_event",
                        f"Bevorstehender Termin: {name}",
                        f"In {max(1, int(delta.total_seconds() // 60))} Minuten steht '{name}' an.",
                        severity="info", target_id=sched_id, details={"schedule_id": sched_id, "name": name},
                        cooldown_seconds=3600,
                    )
                    if ev:
                        events.append(ev)
            except Exception:
                continue
        return events

    def evaluate_vision_diagnostic(self, rack_diag: dict[str, Any], target_id: str = "server-rack") -> list[dict[str, Any]]:
        """Evaluate structured vision analysis results from server rack or room cameras."""
        events: list[dict[str, Any]] = []
        severity = rack_diag.get("severity", "healthy")
        anomalies = rack_diag.get("detected_anomalies", [])

        if severity in ("critical", "warning") and anomalies:
            ev = self.trigger_event(
                "vision", f"rack_{severity}",
                f"Optische Anomalie am Server-Rack ({target_id})",
                f"Kamera erkennt: {anomalies[0]}",
                severity=severity, target_id=target_id, details=rack_diag,
                cooldown_seconds=900,
            )
            if ev:
                events.append(ev)
        return events

    def list_events(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        query = "SELECT id, trigger_type, code, title, message, severity, target_id, details_json, status, created_at, acknowledged_at FROM ambient_events "
        params: list[Any] = []
        if status:
            query += "WHERE status = ? "
            params.append(status)
        query += "ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 100)))

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        results = []
        for r in rows:
            try:
                details = json.loads(r[7])
            except Exception:
                details = {}
            results.append({
                "id": r[0],
                "trigger_type": r[1],
                "code": r[2],
                "title": r[3],
                "message": r[4],
                "severity": r[5],
                "target_id": r[6],
                "details": details,
                "status": r[8],
                "created_at": r[9],
                "acknowledged_at": r[10],
            })
        return results

    def acknowledge_event(self, event_id: str) -> bool:
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE ambient_events SET status = 'acknowledged', acknowledged_at = ? "
                "WHERE id = ? AND status IN ('pending', 'suppressed', 'delivered')",
                (now, event_id),
            )
            return cur.rowcount > 0

    def pending_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(1) FROM ambient_events WHERE status = 'pending'").fetchone()
            return int(row[0] if row else 0)
