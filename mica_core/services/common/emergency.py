"""Mobile emergency access service (Sam / Swift & Hawk inspired) for MICA Phase 4.5.

Provides a hardened, minimal-overhead remote interface for critical homelab emergencies:
- Server and container health overview
- Critical ambient alerts feed
- Instant system-wide Emergency Stop (Not-Aus)
- Remote resolution of autonomous action tickets
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .autonomous_guard import AutonomousActionGuard
from .policy import PolicyEngine


@dataclass(frozen=True)
class EmergencySession:
    token: str
    expires_at: datetime
    ip_address: str


class EmergencyService:
    """Hardened emergency access manager with rate-limiting and session revocation."""

    def __init__(
        self,
        secret: str | None = None,
        session_ttl_minutes: int = 15,
        max_failed_attempts: int = 5,
        lockout_seconds: int = 300,
    ):
        raw_secret = secret or os.getenv("MICA_EMERGENCY_SECRET") or os.getenv("MICA_APPROVAL_SECRET", "")
        self._secret_digest = hashlib.sha256(raw_secret.encode("utf-8")).digest() if raw_secret else b""
        self.session_ttl = timedelta(minutes=max(1, min(session_ttl_minutes, 60)))
        self.max_failed_attempts = max_failed_attempts
        self.lockout_seconds = lockout_seconds

        self._sessions: dict[str, EmergencySession] = {}
        self._failed_attempts: dict[str, list[float]] = {}

    @property
    def configured(self) -> bool:
        return bool(self._secret_digest)

    def _is_locked_out(self, client_key: str) -> bool:
        now = time.monotonic()
        attempts = [t for t in self._failed_attempts.get(client_key, []) if now - t < self.lockout_seconds]
        self._failed_attempts[client_key] = attempts
        return len(attempts) >= self.max_failed_attempts

    def _record_failed_attempt(self, client_key: str) -> None:
        now = time.monotonic()
        attempts = self._failed_attempts.get(client_key, [])
        attempts.append(now)
        self._failed_attempts[client_key] = attempts

    def login(self, supplied_secret: str, client_ip: str = "remote") -> str | None:
        """Authenticate with emergency secret, returning short-lived token."""
        if not self.configured:
            return None
        if self._is_locked_out(client_ip):
            return None

        supplied_digest = hashlib.sha256(supplied_secret.encode("utf-8")).digest()
        if not hmac.compare_digest(self._secret_digest, supplied_digest):
            self._record_failed_attempt(client_ip)
            return None

        token = secrets.token_urlsafe(32)
        expiry = datetime.now(UTC) + self.session_ttl
        self._sessions[token] = EmergencySession(token=token, expires_at=expiry, ip_address=client_ip)
        return token

    def validate_token(self, token: str | None) -> bool:
        if not token:
            return False
        session = self._sessions.get(token)
        if not session:
            return False
        now = datetime.now(UTC)
        if session.expires_at <= now:
            self._sessions.pop(token, None)
            return False
        return True

    def revoke_all_sessions(self) -> None:
        self._sessions.clear()

    def get_emergency_overview(
        self,
        policy: PolicyEngine,
        phase4_store: Any | None = None,
        ambient_monitor: Any | None = None,
        guard: AutonomousActionGuard | None = None,
    ) -> dict[str, Any]:
        """Compile a compact, high-priority emergency status overview."""
        is_stopped = policy.is_emergency_stopped()

        # Fetch latest server observation
        server_state: dict[str, Any] = {
            "target": "zimaos-local",
            "status": "unknown",
            "cpu_percent": 0.0,
            "memory_percent": 0.0,
            "disk_percent": 0.0,
            "unhealthy_containers": 0,
            "restart_count": 0,
        }
        if phase4_store:
            try:
                obs = phase4_store.server_observations()
                if obs:
                    latest = obs[0]
                    server_state.update({
                        "target": latest.get("target_id", "zimaos-local"),
                        "status": "healthy" if latest.get("unhealthy_count", 0) == 0 else "degraded",
                        "cpu_percent": latest.get("cpu_percent", 0.0),
                        "memory_percent": latest.get("memory_percent", 0.0),
                        "disk_percent": latest.get("disk_percent", 0.0),
                        "unhealthy_containers": latest.get("unhealthy_count", 0),
                        "restart_count": latest.get("restart_count", 0),
                    })
            except Exception:
                pass

        # Fetch active critical alerts
        critical_alerts: list[dict[str, Any]] = []
        if ambient_monitor:
            try:
                events = ambient_monitor.list_events(status="pending", limit=10)
                critical_alerts = [
                    {"id": e["id"], "title": e["title"], "message": e["message"], "severity": e["severity"], "created_at": e["created_at"]}
                    for e in events if e["severity"] in ("warning", "critical")
                ]
            except Exception:
                pass

        # Fetch pending autonomous action tickets
        pending_tickets: list[dict[str, Any]] = []
        if guard:
            try:
                tickets = guard.list_tickets(status="pending")
                pending_tickets = [
                    {"id": t["id"], "action": t["action"], "risk": t["risk"], "tier": t["tier"], "origin": t["origin"], "created_at": t["created_at"]}
                    for t in tickets
                ]
            except Exception:
                pass

        return {
            "emergency_stop_active": is_stopped,
            "system_overall": "emergency_stopped" if is_stopped else server_state["status"],
            "server": server_state,
            "critical_alerts": critical_alerts,
            "pending_tickets": pending_tickets,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def trigger_emergency_stop(
        self,
        policy: PolicyEngine,
        guard: AutonomousActionGuard | None = None,
    ) -> bool:
        """Execute full Not-Aus and invalidate all pending autonomous actions."""
        policy.set_emergency_stop(True)
        if guard:
            guard.revoke_all_on_emergency_stop()
        return True

    def resume_from_emergency_stop(
        self,
        policy: PolicyEngine,
    ) -> bool:
        """Clear emergency stop after manual operator verification."""
        policy.set_emergency_stop(False)
        return True
