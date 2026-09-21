"""Autonomous action authorization and human-approval layer for MICA Phase 4.5.

Guards all actions initiated autonomously by Ambient or Vision perception triggers,
ensuring irreversible or sensitive host actions cannot execute without explicit,
tamper-proof operator approval and tight integration with Emergency Stop (Not-Aus).
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from .capabilities import (
    RISK_DESTRUCTIVE,
    RISK_READ,
    RISK_REVERSIBLE,
    RISK_SENSITIVE_READ,
    capability_for,
)
from .policy import PolicyEngine, is_destructive


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class AutonomousDecision:
    allowed: bool
    requires_approval: bool
    tier: int  # 0: Read, 1: Reversible, 2: Destructive
    risk: str
    reason: str
    ticket_id: str | None = None
    approval_token: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AutonomousActionGuard:
    """Multi-tier security gate for autonomous actions triggered by perception."""

    def __init__(
        self,
        db_path: str | Path,
        ticket_ttl_minutes: int = 15,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ticket_ttl = timedelta(minutes=max(1, min(ticket_ttl_minutes, 120)))

        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS autonomous_tickets (
                    id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    tier INTEGER NOT NULL,
                    risk TEXT NOT NULL,
                    origin_json TEXT NOT NULL,
                    status TEXT NOT NULL, -- 'pending', 'approved', 'rejected', 'consumed', 'expired', 'revoked'
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    resolved_at TEXT,
                    resolved_by TEXT,
                    approval_token TEXT
                );
                CREATE TABLE IF NOT EXISTS autonomous_policies (
                    action TEXT PRIMARY KEY,
                    auto_allow_tier1 INTEGER NOT NULL DEFAULT 0,
                    max_auto_per_hour INTEGER NOT NULL DEFAULT 5,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_autonomous_tickets_lookup ON autonomous_tickets(status, expires_at);
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

    def classify_action(self, action: str, params: dict[str, Any]) -> tuple[int, str]:
        """Classify action into Tier 0 (Read), Tier 1 (Reversible), or Tier 2 (Destructive)."""
        capability = capability_for(action)
        if capability is not None:
            risk = capability.risk_for(params)
        elif is_destructive(action, params):
            risk = RISK_DESTRUCTIVE
        else:
            risk = RISK_REVERSIBLE

        if risk == RISK_READ:
            return 0, risk
        if risk in (RISK_SENSITIVE_READ, RISK_REVERSIBLE):
            return 1, risk
        return 2, RISK_DESTRUCTIVE

    def is_tier1_auto_allowed(self, action: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT auto_allow_tier1 FROM autonomous_policies WHERE action = ?", (action,)
            ).fetchone()
            return bool(row and row[0] == 1)

    def set_tier1_policy(self, action: str, auto_allow: bool, max_per_hour: int = 5) -> None:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO autonomous_policies(action, auto_allow_tier1, max_auto_per_hour, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(action) DO UPDATE SET auto_allow_tier1=excluded.auto_allow_tier1, "
                "max_auto_per_hour=excluded.max_auto_per_hour, updated_at=excluded.updated_at",
                (action, 1 if auto_allow else 0, max_per_hour, now),
            )

    def evaluate_proposal(
        self,
        action: str,
        params: dict[str, Any],
        origin: dict[str, Any],
        policy_engine: PolicyEngine,
    ) -> AutonomousDecision:
        """Evaluate an autonomous action proposal against safety policy and kill switch."""
        if policy_engine.is_emergency_stopped():
            return AutonomousDecision(
                allowed=False,
                requires_approval=False,
                tier=2,
                risk="stopped",
                reason="Not-Aus (Emergency Stop) ist aktiv; alle autonomen Aktionen sind blockiert.",
            )

        tier, risk = self.classify_action(action, params)

        # Tier 0: Read-only observation is always autonomously allowed
        if tier == 0:
            return AutonomousDecision(
                allowed=True,
                requires_approval=False,
                tier=0,
                risk=risk,
                reason="Leseoperation ist autonom zulässig.",
            )

        # Tier 1: Reversible remediation
        if tier == 1 and self.is_tier1_auto_allowed(action):
            return AutonomousDecision(
                allowed=True,
                requires_approval=False,
                tier=1,
                risk=risk,
                reason="Reversible Aktion ist über die autonome Richtlinie freigegeben.",
            )

        # Otherwise (Tier 1 without pre-approval OR Tier 2 Destructive): MUST require human approval ticket
        ticket_id = uuid.uuid4().hex
        now_dt = datetime.now(UTC)
        now_str = now_dt.isoformat()
        expires_str = (now_dt + self.ticket_ttl).isoformat()
        params_json = json.dumps(params, ensure_ascii=False, sort_keys=True)
        origin_json = json.dumps(origin, ensure_ascii=False, sort_keys=True)

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO autonomous_tickets (id, action, params_json, tier, risk, origin_json, status, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                (ticket_id, action, params_json, tier, risk, origin_json, now_str, expires_str),
            )

        reason = (
            "Autonome Aktion erfordert manuelle Freigabe (Tier 2 Destruktiv)."
            if tier == 2
            else "Autonome Aktion erfordert Bestätigung (Tier 1 Reversibel ohne Dauerfreigabe)."
        )
        return AutonomousDecision(
            allowed=False,
            requires_approval=True,
            tier=tier,
            risk=risk,
            reason=reason,
            ticket_id=ticket_id,
        )

    def list_tickets(self, status: str | None = None) -> list[dict[str, Any]]:
        now = _now()
        with self._connect() as conn:
            # Mark expired tickets first
            conn.execute("UPDATE autonomous_tickets SET status='expired' WHERE status='pending' AND expires_at <= ?", (now,))
            query = (
                "SELECT id, action, params_json, tier, risk, origin_json, status, created_at, expires_at, resolved_at, resolved_by "
                "FROM autonomous_tickets "
            )
            params: list[Any] = []
            if status:
                query += "WHERE status = ? "
                params.append(status)
            query += "ORDER BY created_at DESC LIMIT 50"
            rows = conn.execute(query, params).fetchall()

        results = []
        for r in rows:
            results.append({
                "id": r[0],
                "action": r[1],
                "params": json.loads(r[2]),
                "tier": r[3],
                "risk": r[4],
                "origin": json.loads(r[5]),
                "status": r[6],
                "created_at": r[7],
                "expires_at": r[8],
                "resolved_at": r[9],
                "resolved_by": r[10],
            })
        return results

    def get_ticket(self, ticket_id: str) -> dict[str, Any] | None:
        tickets = self.list_tickets()
        for t in tickets:
            if t["id"] == ticket_id:
                return t
        return None

    def approve_ticket(self, ticket_id: str, operator_id: str = "operator") -> tuple[bool, str]:
        """Approve an autonomous ticket, generating a single-use token for execution."""
        now = _now()
        token = secrets.token_hex(24)
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE autonomous_tickets SET status='approved', resolved_at=?, resolved_by=?, approval_token=? "
                "WHERE id=? AND status='pending' AND expires_at > ?",
                (now, operator_id, token, ticket_id, now),
            )
            if cur.rowcount != 1:
                return False, "Ticket nicht gefunden, abgelaufen oder bereits bearbeitet."
        return True, token

    def reject_ticket(self, ticket_id: str, operator_id: str = "operator") -> bool:
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE autonomous_tickets SET status='rejected', resolved_at=?, resolved_by=? "
                "WHERE id=? AND status='pending' AND expires_at > ?",
                (now, operator_id, ticket_id, now),
            )
            return cur.rowcount == 1

    def consume_token(self, ticket_id: str, token: str) -> bool:
        """Atomically consume the approval token upon execution."""
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE autonomous_tickets SET status='consumed' "
                "WHERE id=? AND approval_token=? AND status='approved' AND expires_at > ?",
                (ticket_id, token, now),
            )
            return cur.rowcount == 1

    def revoke_all_on_emergency_stop(self) -> int:
        """Instantly revoke all pending or approved tickets when Emergency Stop fires."""
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE autonomous_tickets SET status='revoked', resolved_at=? "
                "WHERE status IN ('pending', 'approved')",
                (now,),
            )
            return cur.rowcount
