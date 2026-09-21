from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
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


READ_ONLY = {"brain.search", "brain.graph", "system.status", "files.list", "docker.status", "improvement.shadow"}
REVERSIBLE = {
    "files.create", "files.move", "settings.volume", "reminder.create",
    "connector.configure",
    "learning.configure", "automation.enable", "agent.plan.activate",
}
DESTRUCTIVE = {
    "files.delete", "network.change", "docker.lifecycle", "message.send", "system.admin",
    "improvement.invoke", "improvement.promote", "improvement.rollback",
}


def is_destructive(action: str, params: dict[str, Any]) -> bool:
    """Classify parameter-sensitive operations at their most dangerous mode."""
    capability = capability_for(action)
    if capability is not None:
        return capability.risk_for(params) == RISK_DESTRUCTIVE
    return action in DESTRUCTIVE or (action == "files.create" and bool(params.get("overwrite")))


@dataclass(frozen=True)
class Decision:
    allowed: bool
    requires_approval: bool
    risk: str
    reason: str
    approval_id: str | None = None


class PolicyEngine:
    """Persisted, deny-by-default policy decisions for the tool boundary.

    Model supplied action names are never authority. Reusable approvals are
    bound to the exact canonical parameter object; a confirmation for one
    path, message, or setting cannot become a wildcard grant. Destructive
    approvals are single use and expire quickly.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.approval_ttl = timedelta(seconds=max(60, int(os.getenv("MICA_APPROVAL_TTL_SECONDS", "900"))))
        self.scope_ttl = timedelta(days=max(1, int(os.getenv("MICA_REVERSIBLE_SCOPE_DAYS", "30"))))
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS approvals ("
                "id TEXT PRIMARY KEY, action TEXT NOT NULL, params TEXT NOT NULL, "
                "status TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS scopes ("
                "id TEXT PRIMARY KEY, action TEXT NOT NULL, expires_at TEXT NOT NULL, params TEXT)"
            )
            conn.execute("CREATE TABLE IF NOT EXISTS control (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            self._ensure_column(conn, "approvals", "expires_at", "TEXT")
            self._ensure_column(conn, "scopes", "params", "TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_lookup ON approvals(id, action, status, expires_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scopes_lookup ON scopes(action, params, expires_at)")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=5, isolation_level=None)
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    @staticmethod
    def _canonical_params(params: dict[str, Any]) -> str:
        """Return the exact, stable request payload an approval applies to."""
        return json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def is_emergency_stopped(self) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM control WHERE key = 'emergency_stop'").fetchone()
        return bool(row and row[0] == "1")

    def set_emergency_stop(self, active: bool) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO control(key, value) VALUES ('emergency_stop', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                ("1" if active else "0",),
            )
            if active:
                # Revocation is immediate for every not-yet-dispatched approval
                # and remembered reversible scope.
                conn.execute("UPDATE approvals SET status = 'revoked' WHERE status IN ('pending', 'approved')")
                conn.execute("DELETE FROM scopes")
            conn.execute("COMMIT")

    def decide(self, action: str, params: dict[str, Any], dry_run: bool = False) -> Decision:
        try:
            canonical_params = self._canonical_params(params)
        except (TypeError, ValueError):
            return Decision(False, False, "invalid", "Action parameters must be finite JSON data")
        if self.is_emergency_stopped():
            return Decision(False, False, "stopped", "Emergency stop is active")
        capability = capability_for(action)
        if capability is not None:
            available, availability_reason = capability.availability_for(params)
            if not available:
                return Decision(False, False, "unavailable", availability_reason)
            risk = capability.risk_for(params)
            if risk == RISK_READ:
                return Decision(True, False, risk, "Registered read-only capability")
            if risk in {RISK_SENSITIVE_READ, RISK_REVERSIBLE}:
                if dry_run:
                    return Decision(True, False, risk, "Dry run: no action will be sent")
                if self.has_scope(action, canonical_params):
                    return Decision(True, False, risk, "Previously granted parameter-bound scope")
                return self._request_approval(action, canonical_params, risk, "A parameter-bound user approval is required")
            if risk == RISK_DESTRUCTIVE:
                if dry_run:
                    return Decision(True, False, risk, "Dry run: no action will be sent")
                return self._request_approval(action, canonical_params, risk, "Explicit single-use human approval is required")
            return Decision(False, False, "unknown", "Capability has an unsupported risk classification")
        if action in READ_ONLY:
            return Decision(True, False, "read", "Read-only scope")
        if action in REVERSIBLE and not is_destructive(action, params):
            if dry_run:
                return Decision(True, False, "reversible", "Dry run: no action will be sent")
            if self.has_scope(action, canonical_params):
                return Decision(True, False, "reversible", "Previously granted, parameter-bound reversible scope")
            return self._request_approval(action, canonical_params, "reversible", "A saved user approval is required")
        if is_destructive(action, params):
            if dry_run:
                return Decision(True, False, "destructive", "Dry run: no action will be sent")
            return self._request_approval(action, canonical_params, "destructive", "Explicit human approval is required")
        return Decision(False, False, "unknown", "Action is not in the allowlist")

    def decide_plan(self, params: dict[str, Any], approval_id: str | None = None) -> Decision:
        """Authorize an immutable plan envelope without weakening per-step checks."""
        try:
            canonical_params = self._canonical_params(params)
        except (TypeError, ValueError):
            return Decision(False, False, "invalid", "Plan parameters must be finite JSON data")
        if self.is_emergency_stopped():
            return Decision(False, False, "stopped", "Emergency stop is active")
        risk = str(params.get("risk", "unknown"))
        plan_hash = str(params.get("plan_hash", ""))
        if risk not in {RISK_READ, RISK_SENSITIVE_READ, RISK_REVERSIBLE, RISK_DESTRUCTIVE} or len(plan_hash) != 64:
            return Decision(False, False, "unknown", "Unknown or malformed plan risk is blocked")
        if risk == RISK_READ:
            return Decision(True, False, risk, "Finite read-only plan")
        if approval_id and self.approved(approval_id, "agent.plan.activate", params):
            if risk == RISK_DESTRUCTIVE and not self.consume_approval(approval_id, "agent.plan.activate", params):
                return Decision(False, True, risk, "Plan approval was already consumed", approval_id)
            return Decision(True, False, risk, "Exact plan hash and budget were approved", approval_id)
        if risk in {RISK_SENSITIVE_READ, RISK_REVERSIBLE} and self.has_scope("agent.plan.activate", canonical_params):
            return Decision(True, False, risk, "Exact plan hash and budget are within approved scope")
        return self._request_approval(
            "agent.plan.activate", canonical_params, risk,
            "A parameter-bound plan approval is required" if risk != RISK_DESTRUCTIVE
            else "A fresh single-use approval is required for this destructive plan",
        )

    def grant_plan_step_scopes(self, steps: list[dict[str, Any]]) -> int:
        """Persist exact reversible step scopes after the immutable plan is approved."""
        if self.is_emergency_stopped():
            return 0
        expires_at = (datetime.now(UTC) + self.scope_ttl).isoformat()
        granted = 0
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for step in steps:
                action, params = str(step.get("action", "")), step.get("params", {})
                capability = capability_for(action)
                risk = capability.risk_for(params) if capability is not None else (
                    RISK_REVERSIBLE if action in REVERSIBLE else RISK_DESTRUCTIVE if is_destructive(action, params) else "unknown"
                )
                if risk not in {RISK_SENSITIVE_READ, RISK_REVERSIBLE}:
                    continue
                canonical = self._canonical_params(params)
                conn.execute(
                    "INSERT INTO scopes(id,action,expires_at,params) VALUES(?,?,?,?)",
                    (uuid.uuid4().hex, action, expires_at, canonical),
                )
                granted += 1
            conn.execute("COMMIT")
        return granted

    def _request_approval(self, action: str, canonical_params: str, risk: str, reason: str) -> Decision:
        approval_id = uuid.uuid4().hex
        created_at = datetime.now(UTC)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO approvals(id, action, params, status, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                (approval_id, action, canonical_params, "pending", created_at.isoformat(), (created_at + self.approval_ttl).isoformat()),
            )
        return Decision(False, True, risk, reason, approval_id)

    def resolve(self, approval_id: str, approved: bool) -> bool:
        """Resolve a still-valid prompt once, creating only an exact saved scope."""
        now = self._now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT action, params FROM approvals WHERE id = ? AND status = 'pending' "
                "AND expires_at > ?", (approval_id, now)
            ).fetchone()
            if not row:
                conn.execute("ROLLBACK")
                return False
            status = "approved" if approved else "rejected"
            result = conn.execute(
                "UPDATE approvals SET status = ? WHERE id = ? AND status = 'pending' AND expires_at > ?",
                (status, approval_id, now),
            )
            if result.rowcount != 1:
                conn.execute("ROLLBACK")
                return False
            capability = capability_for(row[0])
            capability_risk = capability.risk_for(json.loads(row[1])) if capability is not None else None
            plan_risk = None
            if row[0] == "agent.plan.activate":
                try:
                    plan_risk = json.loads(row[1]).get("risk")
                except (TypeError, ValueError, json.JSONDecodeError):
                    plan_risk = "unknown"
            reusable_action = row[0] in REVERSIBLE and plan_risk != RISK_DESTRUCTIVE
            if approved and (reusable_action or capability_risk in {RISK_SENSITIVE_READ, RISK_REVERSIBLE}):
                conn.execute(
                    "INSERT INTO scopes(id, action, expires_at, params) VALUES (?, ?, ?, ?)",
                    (uuid.uuid4().hex, row[0], (datetime.now(UTC) + self.scope_ttl).isoformat(), row[1]),
                )
            conn.execute("COMMIT")
        return True

    def approved(self, approval_id: str, action: str, params: dict[str, Any]) -> bool:
        """Check an unconsumed, unexpired approval without granting authority."""
        try:
            canonical_params = self._canonical_params(params)
        except (TypeError, ValueError):
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM approvals WHERE id = ? AND action = ? AND params = ? "
                "AND status = 'approved' AND expires_at > ?",
                (approval_id, action, canonical_params, self._now()),
            ).fetchone()
        return bool(row)

    def consume_approval(self, approval_id: str, action: str, params: dict[str, Any]) -> bool:
        """Atomically consume approval so a destructive request cannot be replayed."""
        try:
            canonical_params = self._canonical_params(params)
        except (TypeError, ValueError):
            return False
        with self._connect() as conn:
            result = conn.execute(
                "UPDATE approvals SET status = 'consumed' WHERE id = ? AND action = ? AND params = ? "
                "AND status = 'approved' AND expires_at > ?",
                (approval_id, action, canonical_params, self._now()),
            )
        return result.rowcount == 1

    def has_scope(self, action: str, canonical_params: str) -> bool:
        now = self._now()
        with self._connect() as conn:
            conn.execute("DELETE FROM scopes WHERE expires_at <= ?", (now,))
            row = conn.execute(
                "SELECT 1 FROM scopes WHERE action = ? AND params = ? AND expires_at > ?",
                (action, canonical_params, now),
            ).fetchone()
        return bool(row)

    def pending(self, limit: int = 100) -> list[dict[str, Any]]:
        now = self._now()
        with self._connect() as conn:
            conn.execute("UPDATE approvals SET status = 'expired' WHERE status = 'pending' AND expires_at <= ?", (now,))
            rows = conn.execute(
                "SELECT id, action, params, created_at, expires_at FROM approvals "
                "WHERE status = 'pending' AND expires_at > ? ORDER BY created_at DESC LIMIT ?",
                (now, max(1, min(limit, 200))),
            ).fetchall()
        return [{"id": row[0], "action": row[1], "params": json.loads(row[2]), "created_at": row[3], "expires_at": row[4]} for row in rows]
