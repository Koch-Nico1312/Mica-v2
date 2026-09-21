from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator

from .capabilities import (
    RISK_DESTRUCTIVE,
    RISK_READ,
    RISK_REVERSIBLE,
    RISK_SENSITIVE_READ,
    capability_for,
)


RISK_ORDER = {RISK_READ: 0, RISK_SENSITIVE_READ: 1, RISK_REVERSIBLE: 2, RISK_DESTRUCTIVE: 3, "unknown": 4}
PLAN_STATUSES = {"draft", "ready", "active", "paused", "completed", "cancelled", "failed"}
STEP_STATUSES = {"pending", "running", "completed", "failed", "blocked"}
PRESENCE_STATES = {
    "offline", "idle", "listening", "thinking", "approval_required", "executing", "speaking", "error",
}
SAFE_TWIN_SOURCES = {"task", "schedule", "confirmed_profile", "chat_summary", "usage_metric"}
SENSITIVE_TWIN_CATEGORIES = {"identity", "relationship", "location", "personal"}
EXCLUDED_TWIN_CATEGORIES = {"secret", "raw_audio", "full_chat", "audit_payload", "brain", "health", "finance"}
SECRET_MARKERS = ("password", "passwd", "api_key", "api-key", "bearer ", "private key", "secret=", "token=")
DEFAULT_BUDGET = {"max_steps": 6, "max_tool_calls": 10, "max_corrections": 2, "max_minutes": 10}
HARD_BUDGET = {"max_steps": 12, "max_tool_calls": 20, "max_corrections": 3, "max_minutes": 30}
CORE_PLAN_ACTION_RISKS = {
    "system.status": RISK_READ, "docker.status": RISK_READ,
    "files.list": RISK_SENSITIVE_READ, "files.create": RISK_REVERSIBLE, "files.move": RISK_REVERSIBLE,
    "files.delete": RISK_DESTRUCTIVE, "network.change": RISK_DESTRUCTIVE,
    "docker.lifecycle": RISK_DESTRUCTIVE, "system.admin": RISK_DESTRUCTIVE,
}


def enabled(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def phase4_enabled() -> bool:
    return enabled("MICA_PHASE4_ENABLED")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def day_state_for(moment: datetime | None = None) -> str:
    hour = (moment or datetime.now().astimezone()).astimezone().hour
    return "morning" if 5 <= hour < 11 else "day" if 11 <= hour < 18 else "evening" if 18 <= hour < 23 else "night"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash_plan(
    goal: str, steps: list[dict[str, Any]], budget: dict[str, int], revision: int,
    assessment: dict[str, Any],
) -> str:
    return hashlib.sha256(_canonical({
        "goal": goal, "steps": steps, "budget": budget, "revision": revision, "assessment": assessment,
    }).encode()).hexdigest()


def steps_for_goal(goal: str) -> list[dict[str, Any]]:
    """Decompose a small supported local goal without model-generated tools."""
    normalized = goal.casefold()
    server_words = ("zima", "server", "homelab")
    wants_server = any(word in normalized for word in server_words)
    wants_container = any(word in normalized for word in ("docker", "container", "dienst"))
    wants_system = any(word in normalized for word in ("cpu", "ram", "speicher", "last", "systemstatus", "status"))
    steps: list[dict[str, Any]] = []
    if wants_server or wants_system:
        steps.append({"action": "system.status", "params": {}, "expected_change": "Keine Änderung; Systemstatus lesen"})
    if wants_server or wants_container:
        steps.append({"action": "docker.status", "params": {}, "expected_change": "Keine Änderung; Containerstatus lesen"})
    if not steps:
        raise ValueError("goal cannot be decomposed into the bounded local capability set")
    return steps


def assess_plan(steps: list[dict[str, Any]], risks: list[str]) -> dict[str, Any]:
    data_categories: set[str] = set()
    target_systems: set[str] = set()
    for step in steps:
        action = step["action"]
        if action.startswith("files."):
            data_categories.add("local_file_metadata" if action == "files.list" else "local_files")
            target_systems.add("allowlisted_host_files")
        elif action.startswith("docker."):
            data_categories.add("container_metadata")
            target_systems.add("allowlisted_zimaos_containers")
        elif action.startswith("system."):
            data_categories.add("system_metrics")
            target_systems.add("zimaos_host")
        elif action.startswith("network."):
            data_categories.add("network_configuration")
            target_systems.add("allowlisted_zimaos_network_profile")
    risk = max(risks, key=lambda item: RISK_ORDER.get(item, 4))
    reversibility = (
        "read_only" if risk in {RISK_READ, RISK_SENSITIVE_READ}
        else "reversible" if risk == RISK_REVERSIBLE else "destructive_or_irreversible"
    )
    return {
        "data_categories": sorted(data_categories), "target_systems": sorted(target_systems),
        "reversibility": reversibility, "unknown_impacts": False,
        "required_approval": "none" if risk == RISK_READ else "parameter_bound" if risk in {RISK_SENSITIVE_READ, RISK_REVERSIBLE} else "single_use",
    }


def validate_budget(value: dict[str, Any] | None, step_count: int) -> dict[str, int]:
    budget = {**DEFAULT_BUDGET, **(value or {})}
    if set(budget) != set(DEFAULT_BUDGET):
        raise ValueError("budget contains unsupported fields")
    for key, hard_limit in HARD_BUDGET.items():
        item = budget[key]
        if isinstance(item, bool) or not isinstance(item, int) or not 1 <= item <= hard_limit:
            raise ValueError(f"{key} must be between 1 and {hard_limit}")
    if step_count > budget["max_steps"]:
        raise ValueError("plan exceeds its step budget")
    return budget


def normalize_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(steps, list) or not steps:
        raise ValueError("at least one finite plan step is required")
    if len(steps) > HARD_BUDGET["max_steps"]:
        raise ValueError("plan exceeds the hard step limit")
    normalized: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or set(step) - {"action", "params", "expected_change"}:
            raise ValueError("plan steps accept only action, params and expected_change")
        action = str(step.get("action", "")).strip()
        params = step.get("params", {})
        capability = capability_for(action)
        registered_safe = capability is not None and action in CORE_PLAN_ACTION_RISKS and not capability.network_required
        if not action or not registered_safe:
            raise ValueError(f"step {index + 1} uses an unregistered capability")
        if not isinstance(params, dict) or len(params) > 64:
            raise ValueError("step params must be a small JSON object")
        if action in {"system.status", "docker.status"}:
            targets = [item.strip() for item in os.getenv("MICA_SERVER_AGENT_TARGETS", "zimaos-local").split(",") if item.strip()]
            target_id = str(params.get("target_id", targets[0] if targets else "")).strip()
            if not target_id or target_id not in targets:
                raise ValueError(f"step {index + 1} uses a server outside the local allowlist")
            params = {**params, "target_id": target_id}
        try:
            _canonical(params)
        except (TypeError, ValueError) as error:
            raise ValueError("step params must be finite JSON data") from error
        normalized.append({
            "action": action,
            "params": params,
            "expected_change": str(step.get("expected_change", ""))[:500],
        })
    return normalized


class Phase4Store:
    """Additive local store for finite plans, diagnostics, twin facts and presence."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_plans (
                    id TEXT PRIMARY KEY, goal TEXT NOT NULL, task_id TEXT, status TEXT NOT NULL,
                    revision INTEGER NOT NULL, plan_hash TEXT NOT NULL, risk TEXT NOT NULL,
                    budget TEXT NOT NULL, tool_calls INTEGER NOT NULL DEFAULT 0,
                    corrections INTEGER NOT NULL DEFAULT 0, dry_run_at TEXT, approval_id TEXT,
                    started_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    last_error TEXT, assessment TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS agent_plan_steps (
                    id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, position INTEGER NOT NULL,
                    action TEXT NOT NULL, params TEXT NOT NULL, expected_change TEXT NOT NULL,
                    risk TEXT NOT NULL, status TEXT NOT NULL, result TEXT,
                    idempotency_key TEXT NOT NULL, executed_at TEXT,
                    approval_id TEXT,
                    UNIQUE(plan_id, position), UNIQUE(idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS server_observations (
                    id TEXT PRIMARY KEY, target_id TEXT NOT NULL, observed_at TEXT NOT NULL,
                    cpu_percent REAL, memory_percent REAL, load_percent REAL, disk_percent REAL,
                    containers_total INTEGER NOT NULL, unhealthy_count INTEGER NOT NULL,
                    restart_count INTEGER NOT NULL, mica_services_ok INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS server_diagnostics (
                    id TEXT PRIMARY KEY, target_id TEXT NOT NULL, observation_id TEXT NOT NULL,
                    severity TEXT NOT NULL, code TEXT NOT NULL, status TEXT NOT NULL,
                    task_id TEXT, plan_id TEXT, created_at TEXT NOT NULL,
                    UNIQUE(target_id, observation_id, code)
                );
                CREATE TABLE IF NOT EXISTS digital_twin_settings (
                    id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL DEFAULT 0,
                    cloud_opt_in INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS digital_twin_evidence (
                    id TEXT PRIMARY KEY, fact_key TEXT NOT NULL, source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL, value TEXT NOT NULL, confidence REAL NOT NULL,
                    category TEXT NOT NULL, observed_at TEXT NOT NULL,
                    UNIQUE(fact_key, source_type, source_id)
                );
                CREATE TABLE IF NOT EXISTS digital_twin_facts (
                    id TEXT PRIMARY KEY, fact_key TEXT NOT NULL UNIQUE, value TEXT NOT NULL,
                    category TEXT NOT NULL, confidence REAL NOT NULL, observation_count INTEGER NOT NULL,
                    active INTEGER NOT NULL, confirmed INTEGER NOT NULL DEFAULT 0,
                    revoked INTEGER NOT NULL DEFAULT 0, rationale TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS presence_state (
                    id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL,
                    source TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS improvement_signals (
                    signature TEXT PRIMARY KEY, error_type TEXT NOT NULL, occurrences INTEGER NOT NULL,
                    suggestion_id TEXT, quarantined INTEGER NOT NULL DEFAULT 0,
                    last_seen_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_plan_corrections (
                    id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    replacement_steps TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, UNIQUE(plan_id, revision, reason)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_plans_status ON agent_plans(status, updated_at);
                CREATE INDEX IF NOT EXISTS idx_plan_steps_next ON agent_plan_steps(plan_id, status, position);
                CREATE INDEX IF NOT EXISTS idx_server_observed ON server_observations(target_id, observed_at);
                CREATE INDEX IF NOT EXISTS idx_twin_evidence ON digital_twin_evidence(fact_key, observed_at);
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO digital_twin_settings(id,enabled,cloud_opt_in,updated_at) VALUES(1,0,0,?)",
                (_now(),),
            )
            conn.execute(
                "INSERT OR IGNORE INTO presence_state(id,state,source,updated_at) VALUES(1,'idle','system',?)",
                (_now(),),
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(agent_plan_steps)")}
            if "approval_id" not in columns:
                conn.execute("ALTER TABLE agent_plan_steps ADD COLUMN approval_id TEXT")
            plan_columns = {row[1] for row in conn.execute("PRAGMA table_info(agent_plans)")}
            if "assessment" not in plan_columns:
                conn.execute("ALTER TABLE agent_plans ADD COLUMN assessment TEXT NOT NULL DEFAULT '{}'")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _risk(action: str, params: dict[str, Any]) -> str:
        capability = capability_for(action)
        if capability:
            return capability.risk_for(params)
        if action == "files.create" and bool(params.get("overwrite")):
            return RISK_DESTRUCTIVE
        return CORE_PLAN_ACTION_RISKS.get(action, "unknown")

    def _plan_row(self, row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "id": row[0], "goal": row[1], "task_id": row[2], "status": row[3], "revision": row[4],
            "plan_hash": row[5], "risk": row[6], "budget": json.loads(row[7]), "tool_calls": row[8],
            "corrections": row[9], "dry_run_at": row[10], "approval_id": row[11], "started_at": row[12],
            "created_at": row[13], "updated_at": row[14], "last_error": row[15],
            "assessment": json.loads(row[16] or "{}"),
        }

    def _steps(self, plan_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id,position,action,params,expected_change,risk,status,result,idempotency_key,executed_at,approval_id "
                "FROM agent_plan_steps WHERE plan_id=? ORDER BY position", (plan_id,),
            ).fetchall()
        return [{
            "id": row[0], "position": row[1], "action": row[2], "params": json.loads(row[3]),
            "expected_change": row[4], "risk": row[5], "status": row[6],
            "result": json.loads(row[7]) if row[7] else None, "idempotency_key": row[8], "executed_at": row[9],
            "approval_id": row[10],
        } for row in rows]

    def create_plan(
        self, goal: str, steps: list[dict[str, Any]], budget: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        goal = goal.strip()[:1000]
        if not goal:
            raise ValueError("goal is required")
        steps = normalize_steps(steps)
        budget_value = validate_budget(budget, len(steps))
        risks = [self._risk(step["action"], step["params"]) for step in steps]
        risk = max(risks, key=lambda item: RISK_ORDER.get(item, 4))
        if risk == "unknown":
            raise ValueError("unknown plan risk is blocked")
        plan_id, revision, now = uuid.uuid4().hex, 1, _now()
        assessment = assess_plan(steps, risks)
        plan_hash = _hash_plan(goal, steps, budget_value, revision, assessment)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO agent_plans(id,goal,task_id,status,revision,plan_hash,risk,budget,created_at,updated_at,assessment) "
                "VALUES(?,?,?,'draft',?,?,?,?,?,?,?)",
                (plan_id, goal[:1000], task_id, revision, plan_hash, risk, _canonical(budget_value), now, now, _canonical(assessment)),
            )
            for position, (step, step_risk) in enumerate(zip(steps, risks), start=1):
                conn.execute(
                    "INSERT INTO agent_plan_steps(id,plan_id,position,action,params,expected_change,risk,status,idempotency_key) "
                    "VALUES(?,?,?,?,?,?,?,'pending',?)",
                    (uuid.uuid4().hex, plan_id, position, step["action"], _canonical(step["params"]),
                     step["expected_change"], step_risk, hashlib.sha256(f"{plan_hash}:{position}".encode()).hexdigest()),
                )
            conn.execute("COMMIT")
        return self.get_plan(plan_id) or {}

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id,goal,task_id,status,revision,plan_hash,risk,budget,tool_calls,corrections,dry_run_at,"
                "approval_id,started_at,created_at,updated_at,last_error,assessment FROM agent_plans WHERE id=?", (plan_id,),
            ).fetchone()
        if not row:
            return None
        plan = self._plan_row(row)
        plan["steps"] = self._steps(plan_id)
        plan["correction_proposals"] = self.correction_proposals(plan_id)
        return plan

    def correction_proposals(self, plan_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id,revision,replacement_steps,reason,status,created_at FROM agent_plan_corrections "
                "WHERE plan_id=? ORDER BY created_at DESC", (plan_id,),
            ).fetchall()
        return [{"id": row[0], "revision": row[1], "replacement_steps": json.loads(row[2]),
                 "reason": row[3], "status": row[4], "created_at": row[5]} for row in rows]

    def list_plans(self, status: str | None = None) -> list[dict[str, Any]]:
        if status and status not in PLAN_STATUSES:
            raise ValueError("invalid plan status")
        query = "SELECT id FROM agent_plans"
        values: tuple[Any, ...] = ()
        if status:
            query += " WHERE status=?"
            values = (status,)
        query += " ORDER BY created_at DESC LIMIT 200"
        with self._connect() as conn:
            ids = [row[0] for row in conn.execute(query, values).fetchall()]
        return [plan for item in ids if (plan := self.get_plan(item))]

    def dry_run(self, plan_id: str, policy: Any) -> dict[str, Any] | None:
        plan = self.get_plan(plan_id)
        if not plan:
            return None
        preview = []
        for step in plan["steps"]:
            decision = policy.decide(step["action"], step["params"], dry_run=True)
            preview.append({
                "position": step["position"], "action": step["action"], "risk": step["risk"],
                "allowed": decision.allowed, "expected_change": step["expected_change"],
                "requires_approval": step["risk"] != RISK_READ,
                "required_approval": (
                    "none" if step["risk"] == RISK_READ else "parameter_bound"
                    if step["risk"] in {RISK_SENSITIVE_READ, RISK_REVERSIBLE} else "single_use"
                ),
            })
        timestamp = _now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE agent_plans SET status='ready',dry_run_at=?,updated_at=?,last_error=NULL WHERE id=? "
                "AND status IN ('draft','ready','paused')", (timestamp, timestamp, plan_id),
            )
        return {"plan_id": plan_id, "plan_hash": plan["plan_hash"], "risk": plan["risk"], "steps": preview, "mutated_external_state": False}

    def activate(self, plan_id: str, policy: Any, approval_id: str | None = None) -> tuple[dict[str, Any] | None, Any]:
        plan = self.get_plan(plan_id)
        if not plan:
            return None, None
        if not plan["dry_run_at"]:
            raise ValueError("a complete dry-run is required before activation")
        blocked = next((step for step in plan["steps"] if step["status"] == "blocked"), None)
        if plan["status"] == "paused" and blocked:
            if not approval_id or not policy.approved(approval_id, blocked["action"], blocked["params"]):
                decision = policy.decide(blocked["action"], blocked["params"])
                return plan, decision
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("UPDATE agent_plan_steps SET status='pending',approval_id=? WHERE id=? AND status='blocked'", (approval_id, blocked["id"]))
                conn.execute("UPDATE agent_plans SET status='active',last_error=NULL,updated_at=? WHERE id=?", (_now(), plan_id))
                conn.execute("COMMIT")
            return self.get_plan(plan_id), type("PlanDecision", (), {
                "allowed": True, "requires_approval": False, "risk": blocked["risk"],
                "reason": "Exact blocked step approval supplied", "approval_id": approval_id,
            })()
        params = {"plan_hash": plan["plan_hash"], "risk": plan["risk"], "budget": plan["budget"]}
        decision = policy.decide_plan(params, approval_id=approval_id)
        if not decision.allowed:
            return plan, decision
        policy.grant_plan_step_scopes(plan["steps"])
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE agent_plans SET status='active',approval_id=?,started_at=COALESCE(started_at,?),updated_at=? "
                "WHERE id=? AND plan_hash=? AND status IN ('ready','paused')",
                (approval_id, now, now, plan_id, plan["plan_hash"]),
            )
        return self.get_plan(plan_id), decision

    def patch_plan(self, plan_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        plan = self.get_plan(plan_id)
        if not plan:
            return None
        if set(changes) - {"status", "steps", "budget"} or not changes:
            raise ValueError("only status, unexecuted steps and budget may be changed")
        status = changes.get("status")
        if status:
            allowed = {"active": {"paused", "cancelled"}, "paused": {"cancelled"}, "draft": {"cancelled"}, "ready": {"cancelled"}}
            if status not in allowed.get(plan["status"], set()):
                raise ValueError("invalid plan status transition")
            with self._connect() as conn:
                conn.execute("UPDATE agent_plans SET status=?,updated_at=? WHERE id=?", (status, _now(), plan_id))
            return self.get_plan(plan_id)
        if plan["status"] not in {"draft", "ready", "paused"}:
            raise ValueError("only a non-running plan can be corrected")
        executed = [step for step in plan["steps"] if step["status"] == "completed"]
        replacement = normalize_steps(changes.get("steps", [
            {"action": step["action"], "params": step["params"], "expected_change": step["expected_change"]}
            for step in plan["steps"]
        ]))
        if len(replacement) < len(executed):
            raise ValueError("executed steps cannot be removed")
        for current, new in zip(executed, replacement):
            if current["action"] != new["action"] or current["params"] != new["params"]:
                raise ValueError("executed steps are immutable")
        budget = validate_budget(changes.get("budget", plan["budget"]), len(replacement))
        corrections = plan["corrections"] + 1
        if corrections > plan["budget"]["max_corrections"] or corrections > HARD_BUDGET["max_corrections"]:
            raise ValueError("correction budget exhausted")
        risks = [self._risk(step["action"], step["params"]) for step in replacement]
        risk = max(risks, key=lambda item: RISK_ORDER.get(item, 4))
        revision = plan["revision"] + 1
        assessment = assess_plan(replacement, risks)
        new_hash = _hash_plan(plan["goal"], replacement, budget, revision, assessment)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM agent_plan_steps WHERE plan_id=? AND status!='completed'", (plan_id,))
            for position, (step, step_risk) in enumerate(zip(replacement[len(executed):], risks[len(executed):]), start=len(executed) + 1):
                conn.execute(
                    "INSERT INTO agent_plan_steps(id,plan_id,position,action,params,expected_change,risk,status,idempotency_key) "
                    "VALUES(?,?,?,?,?,?,?,'pending',?)",
                    (uuid.uuid4().hex, plan_id, position, step["action"], _canonical(step["params"]),
                     step["expected_change"], step_risk, hashlib.sha256(f"{new_hash}:{position}".encode()).hexdigest()),
                )
            conn.execute(
                "UPDATE agent_plans SET status='draft',revision=?,plan_hash=?,risk=?,budget=?,corrections=?,"
                "dry_run_at=NULL,approval_id=NULL,updated_at=?,last_error=NULL,assessment=? WHERE id=?",
                (revision, new_hash, risk, _canonical(budget), corrections, _now(), _canonical(assessment), plan_id),
            )
            conn.execute("UPDATE agent_plan_corrections SET status='applied' WHERE plan_id=? AND status='proposed'", (plan_id,))
            conn.execute("COMMIT")
        return self.get_plan(plan_id)

    def run_one_step(
        self, policy: Any, dispatch: Callable[[str, dict[str, Any], str, str | None], dict[str, Any]],
        task_store: Any, audit: Any, improvement_registry: Any | None = None,
    ) -> dict[str, Any]:
        if not phase4_enabled() or not enabled("MICA_SELF_PLANNING_ENABLED"):
            return {"status": "disabled"}
        if policy.is_emergency_stopped():
            self.set_presence("idle", "emergency-stop")
            return {"status": "stopped"}
        now = datetime.now(UTC)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            interrupted = conn.execute(
                "SELECT p.id,s.id,s.risk FROM agent_plans p JOIN agent_plan_steps s ON s.plan_id=p.id "
                "WHERE p.status='active' AND s.status='running' ORDER BY p.created_at,s.position LIMIT 1"
            ).fetchone()
            if interrupted:
                if interrupted[2] in {RISK_READ, RISK_SENSITIVE_READ, RISK_REVERSIBLE}:
                    conn.execute("UPDATE agent_plan_steps SET status='pending' WHERE id=?", (interrupted[1],))
                else:
                    conn.execute("UPDATE agent_plan_steps SET status='blocked' WHERE id=?", (interrupted[1],))
                    conn.execute(
                        "UPDATE agent_plans SET status='paused',last_error='uncertain_outcome',updated_at=? WHERE id=?",
                        (_now(), interrupted[0]),
                    )
            row = conn.execute(
                "SELECT p.id,s.id,s.action,s.params,s.idempotency_key,p.started_at,p.budget,p.tool_calls,s.approval_id "
                "FROM agent_plans p JOIN agent_plan_steps s ON s.plan_id=p.id "
                "WHERE p.status='active' AND s.status='pending' ORDER BY p.created_at,s.position LIMIT 1"
            ).fetchone()
            if not row:
                conn.execute("COMMIT")
                self.set_presence("approval_required" if interrupted and interrupted[2] == RISK_DESTRUCTIVE else "idle", "agent-plan")
                return {"status": "idle"}
            budget = json.loads(row[6])
            if row[7] >= budget["max_tool_calls"] or now - datetime.fromisoformat(row[5]) > timedelta(minutes=budget["max_minutes"]):
                conn.execute("UPDATE agent_plans SET status='paused',last_error='budget_exhausted',updated_at=? WHERE id=?", (_now(), row[0]))
                conn.execute("COMMIT")
                self.set_presence("error", "agent-plan")
                return {"status": "paused", "plan_id": row[0], "reason": "budget_exhausted"}
            conn.execute("UPDATE agent_plan_steps SET status='running' WHERE id=? AND status='pending'", (row[1],))
            conn.execute("COMMIT")
        plan_id, step_id, action, params_text, idem = row[:5]
        step_approval_id = row[8]
        params = json.loads(params_text)
        self.set_presence("executing", "agent-plan")
        preapproved_destructive = bool(step_approval_id and policy.approved(step_approval_id, action, params))
        decision = None if preapproved_destructive else policy.decide(action, params)
        if decision is not None and not decision.allowed:
            with self._connect() as conn:
                conn.execute("UPDATE agent_plan_steps SET status='blocked' WHERE id=?", (step_id,))
                conn.execute("UPDATE agent_plans SET status='paused',last_error=?,updated_at=? WHERE id=?", (decision.reason, _now(), plan_id))
            audit.append("agent_plan.step_blocked", {"plan_id": plan_id, "step_id": step_id, "risk": decision.risk})
            self.set_presence("approval_required", "agent-plan")
            return {"status": "blocked", "plan_id": plan_id, "step_id": step_id, "approval_id": decision.approval_id}
        try:
            with self._connect() as conn:
                conn.execute("UPDATE agent_plans SET tool_calls=tool_calls+1,updated_at=? WHERE id=?", (_now(), plan_id))
            result = dispatch(action, params, idem, step_approval_id)
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("UPDATE agent_plan_steps SET status='completed',result=?,executed_at=? WHERE id=?", (_canonical(result), _now(), step_id))
                left = conn.execute("SELECT COUNT(*) FROM agent_plan_steps WHERE plan_id=? AND status!='completed'", (plan_id,)).fetchone()[0]
                if not left:
                    conn.execute("UPDATE agent_plans SET status='completed',updated_at=? WHERE id=?", (_now(), plan_id))
                conn.execute("COMMIT")
            audit.append("agent_plan.step_completed", {"plan_id": plan_id, "step_id": step_id, "risk": self._risk(action, params), "status": "completed"})
            self.set_presence("idle", "agent-plan")
            return {"status": "completed", "plan_id": plan_id, "step_id": step_id}
        except Exception as error:
            correction_id = None
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("UPDATE agent_plan_steps SET status='failed',result=? WHERE id=?", (_canonical({"error_type": type(error).__name__}), step_id))
                current = conn.execute("SELECT revision,corrections,budget FROM agent_plans WHERE id=?", (plan_id,)).fetchone()
                if current and current[1] < json.loads(current[2])["max_corrections"]:
                    correction_id = uuid.uuid4().hex
                    replacement = [{"action": step["action"], "params": step["params"], "expected_change": step["expected_change"]}
                                   for step in self._steps(plan_id)]
                    conn.execute(
                        "INSERT OR IGNORE INTO agent_plan_corrections(id,plan_id,revision,replacement_steps,reason,status,created_at) "
                        "VALUES(?,?,?,?,?,'proposed',?)",
                        (correction_id, plan_id, current[0] + 1, _canonical(replacement), type(error).__name__, _now()),
                    )
                conn.execute("UPDATE agent_plans SET status='paused',last_error=?,updated_at=? WHERE id=?", (type(error).__name__, _now(), plan_id))
                conn.execute("COMMIT")
            task = task_store.create_task("Agentenplan prüfen", f"Plan {plan_id} wurde nach einem lokalen Fehler pausiert.", "high")
            if improvement_registry is not None:
                self.maybe_propose_improvement(type(error).__name__, f"agent-plan:{action}", improvement_registry)
            audit.append("agent_plan.step_failed", {
                "plan_id": plan_id, "step_id": step_id, "task_id": task["id"],
                "risk": self._risk(action, params), "status": "failed",
            })
            self.set_presence("error", "agent-plan")
            return {"status": "failed", "plan_id": plan_id, "step_id": step_id, "task_id": task["id"], "correction_id": correction_id}

    def record_server_observation(self, target_id: str, snapshot: dict[str, Any], task_store: Any) -> dict[str, Any]:
        targets = {item.strip() for item in os.getenv("MICA_SERVER_AGENT_TARGETS", "zimaos-local").split(",") if item.strip()}
        if target_id not in targets:
            raise ValueError("target is not in the local server allowlist")
        numeric = {key: float(snapshot.get(key, 0) or 0) for key in ("cpu_percent", "memory_percent", "load_percent", "disk_percent")}
        containers = snapshot.get("containers", [])
        if not isinstance(containers, list):
            raise ValueError("containers must be a list")
        unhealthy = sum(1 for item in containers if str(item.get("health", "healthy")).lower() not in {"healthy", "running"})
        restarts = sum(max(0, int(item.get("restart_count", 0))) for item in containers)
        mica_containers = [item for item in containers if str(item.get("name", "")).startswith("mica-")]
        mica_ok = bool(mica_containers) and all(
            bool(item.get("running", False)) and str(item.get("health", "healthy")).lower() in {"healthy", "running"}
            for item in mica_containers
        )
        observation_id, now = uuid.uuid4().hex, _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO server_observations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (observation_id, target_id, now, numeric["cpu_percent"], numeric["memory_percent"], numeric["load_percent"],
                 numeric["disk_percent"], len(containers), unhealthy, restarts, 1 if mica_ok else 0),
            )
            cutoff = (datetime.now(UTC) - timedelta(days=30)).isoformat()
            conn.execute("DELETE FROM server_observations WHERE observed_at<?", (cutoff,))
        with self._connect() as conn:
            trend_rows = conn.execute(
                "SELECT observed_at,cpu_percent,memory_percent,load_percent,disk_percent FROM server_observations "
                "WHERE target_id=? AND observed_at>=?",
                (target_id, (datetime.now(UTC) - timedelta(days=7)).isoformat()),
            ).fetchall()
        trends: dict[str, dict[str, float | None]] = {}
        day_cutoff = datetime.now(UTC) - timedelta(hours=24)
        for position, key in enumerate(("cpu_percent", "memory_percent", "load_percent", "disk_percent"), start=1):
            week_values = [float(row[position]) for row in trend_rows]
            day_values = [float(row[position]) for row in trend_rows if datetime.fromisoformat(row[0]) >= day_cutoff]
            trends[key] = {
                "avg_24h": round(sum(day_values) / len(day_values), 2) if day_values else None,
                "avg_7d": round(sum(week_values) / len(week_values), 2) if week_values else None,
            }
        problems: list[tuple[str, str]] = []
        for key, threshold in (("cpu_percent", 90), ("memory_percent", 90), ("load_percent", 95), ("disk_percent", 85)):
            if numeric[key] >= threshold:
                problems.append(("warning" if numeric[key] < 95 else "critical", key.replace("_percent", "_high")))
        if unhealthy:
            problems.append(("critical", "container_unhealthy"))
        if restarts >= 3:
            problems.append(("warning", "container_restart_trend"))
        if not mica_ok:
            problems.append(("critical", "mica_service_down"))
        for key, values in trends.items():
            average = values["avg_7d"]
            if average is not None and len(trend_rows) >= 3 and numeric[key] >= average + 20:
                problems.append(("warning", key.replace("_percent", "_trend")))
        diagnostic_ids = []
        for severity, code in problems:
            diagnostic_id = uuid.uuid4().hex
            task = task_store.create_task(f"ZimaOS prüfen: {code}", f"Deterministische Diagnose für {target_id}; Messwert {observation_id}.", "high")
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO server_diagnostics(id,target_id,observation_id,severity,code,status,task_id,created_at) "
                    "VALUES(?,?,?,?,?,'open',?,?)",
                    (diagnostic_id, target_id, observation_id, severity, code, task["id"], now),
                )
            diagnostic_ids.append(diagnostic_id)
        return {"id": observation_id, "target_id": target_id, "observed_at": now, **numeric,
                "containers_total": len(containers), "unhealthy_count": unhealthy, "restart_count": restarts,
                "mica_services_ok": mica_ok, "trends": trends, "diagnostics": diagnostic_ids}

    def server_observations(self, target_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT id,target_id,observed_at,cpu_percent,memory_percent,load_percent,disk_percent,containers_total,unhealthy_count,restart_count,mica_services_ok FROM server_observations"
        values: tuple[Any, ...] = ()
        if target_id:
            query += " WHERE target_id=?"
            values = (target_id,)
        query += " ORDER BY observed_at DESC LIMIT 500"
        with self._connect() as conn:
            rows = conn.execute(query, values).fetchall()
        keys = ("id", "target_id", "observed_at", "cpu_percent", "memory_percent", "load_percent", "disk_percent", "containers_total", "unhealthy_count", "restart_count", "mica_services_ok")
        return [{**dict(zip(keys, row)), "mica_services_ok": bool(row[-1])} for row in rows]

    def server_diagnostics(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id,target_id,observation_id,severity,code,status,task_id,plan_id,created_at FROM server_diagnostics ORDER BY created_at DESC LIMIT 500").fetchall()
        keys = ("id", "target_id", "observation_id", "severity", "code", "status", "task_id", "plan_id", "created_at")
        return [dict(zip(keys, row)) for row in rows]

    def confirm_server_diagnostic(
        self, diagnostic_id: str, registry: Any | None = None,
    ) -> dict[str, Any] | None:
        """Confirm a deterministic diagnosis and optionally feed the safe improvement loop."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id,target_id,observation_id,severity,code,status,task_id,plan_id,created_at "
                "FROM server_diagnostics WHERE id=?", (diagnostic_id,),
            ).fetchone()
            if not row:
                return None
            transitioned = row[5] == "open"
            conn.execute(
                "UPDATE server_diagnostics SET status='confirmed' WHERE id=? AND status='open'",
                (diagnostic_id,),
            )
        keys = ("id", "target_id", "observation_id", "severity", "code", "status", "task_id", "plan_id", "created_at")
        result = dict(zip(keys, row))
        result["status"] = "confirmed"
        if registry is not None and transitioned:
            result["improvement"] = self.maybe_propose_improvement(
                f"server.{result['code']}", f"confirmed-diagnostic:{result['target_id']}", registry,
            )
        return result

    def link_diagnostic_plan(self, diagnostic_id: str, plan_id: str) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                "UPDATE server_diagnostics SET plan_id=? WHERE id=? AND status='confirmed' AND plan_id IS NULL",
                (plan_id, diagnostic_id),
            )
        return result.rowcount == 1

    def twin_settings(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT enabled,cloud_opt_in,updated_at FROM digital_twin_settings WHERE id=1").fetchone()
        return {"enabled": bool(row[0]), "cloud_opt_in": bool(row[1]), "updated_at": row[2]}

    def update_twin_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        if not changes or set(changes) - {"enabled", "cloud_opt_in"}:
            raise ValueError("unsupported digital twin setting")
        current = self.twin_settings()
        current.update(changes)
        with self._connect() as conn:
            conn.execute("UPDATE digital_twin_settings SET enabled=?,cloud_opt_in=?,updated_at=? WHERE id=1", (bool(current["enabled"]), bool(current["cloud_opt_in"]), _now()))
        return self.twin_settings()

    def observe_twin(
        self, fact_key: str, value: str, category: str, source_type: str, source_id: str, confidence: float,
    ) -> dict[str, Any] | None:
        if not phase4_enabled() or not enabled("MICA_DIGITAL_TWIN_ENABLED") or not self.twin_settings()["enabled"]:
            return None
        if source_type not in SAFE_TWIN_SOURCES or category in EXCLUDED_TWIN_CATEGORIES:
            return None
        if not fact_key.strip() or not source_id.strip() or not value.strip() or not 0 <= confidence <= 1:
            raise ValueError("invalid twin observation")
        if any(word in value.lower() for word in SECRET_MARKERS):
            return None
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO digital_twin_evidence(id,fact_key,source_type,source_id,value,confidence,category,observed_at) VALUES(?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, fact_key[:120], source_type, source_id[:160], value[:1000], float(confidence), category[:80], now),
            )
            rows = conn.execute(
                "SELECT value,confidence,category FROM digital_twin_evidence WHERE fact_key=? ORDER BY observed_at DESC",
                (fact_key[:120],),
            ).fetchall()
            if not rows:
                return None
            count, averaged = len(rows), sum(row[1] for row in rows) / len(rows)
            sensitive = category in SENSITIVE_TWIN_CATEGORIES
            explicitly_confirmed = source_type == "confirmed_profile"
            active = explicitly_confirmed or (count >= 3 and averaged >= 0.8 and not sensitive)
            fact_id = hashlib.sha256(fact_key.encode()).hexdigest()[:32]
            rationale = f"{count} unabhängige sichere Beobachtungen; Konfidenz {averaged:.2f}"
            conn.execute(
                "INSERT INTO digital_twin_facts(id,fact_key,value,category,confidence,observation_count,active,confirmed,revoked,rationale,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,0,?,?,?) ON CONFLICT(fact_key) DO UPDATE SET value=excluded.value,category=excluded.category,"
                "confidence=excluded.confidence,observation_count=excluded.observation_count,active=CASE WHEN digital_twin_facts.revoked=1 THEN 0 ELSE excluded.active END,"
                "confirmed=MAX(digital_twin_facts.confirmed,excluded.confirmed),rationale=excluded.rationale,updated_at=excluded.updated_at",
                (fact_id, fact_key[:120], rows[0][0], category[:80], averaged, count, 1 if active else 0,
                 1 if explicitly_confirmed else 0, rationale, now, now),
            )
        return self.get_twin_fact(fact_id)

    def get_twin_fact(self, fact_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT id,fact_key,value,category,confidence,observation_count,active,confirmed,revoked,rationale,created_at,updated_at FROM digital_twin_facts WHERE id=?", (fact_id,)).fetchone()
        if not row:
            return None
        keys = ("id", "key", "value", "category", "confidence", "observation_count", "active", "confirmed", "revoked", "rationale", "created_at", "updated_at")
        item = dict(zip(keys, row))
        for key in ("active", "confirmed", "revoked"):
            item[key] = bool(item[key])
        return item

    def twin_facts(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            ids = [row[0] for row in conn.execute("SELECT id FROM digital_twin_facts ORDER BY updated_at DESC").fetchall()]
        return [fact for item in ids if (fact := self.get_twin_fact(item))]

    def twin_prompt(self, limit: int = 12) -> str:
        """Return bounded, user-visible context only; never policy or tool authority."""
        settings = self.twin_settings()
        if not settings["enabled"]:
            return ""
        facts = [item for item in self.twin_facts() if item["active"] and not item["revoked"]][:max(1, min(limit, 20))]
        return "\n".join(f"- {item['key']}: {item['value']}" for item in facts)

    def patch_twin_fact(self, fact_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        if not changes or set(changes) - {"value", "confirmed", "revoked"}:
            raise ValueError("unsupported twin fact field")
        fact = self.get_twin_fact(fact_id)
        if not fact:
            return None
        value = str(changes.get("value", fact["value"])).strip()[:1000]
        if not value or any(marker in value.lower() for marker in SECRET_MARKERS):
            raise ValueError("secret-shaped or empty values are excluded from the digital twin")
        confirmed = bool(changes.get("confirmed", fact["confirmed"]))
        revoked = bool(changes.get("revoked", fact["revoked"]))
        active = bool(not revoked and (confirmed or (fact["observation_count"] >= 3 and fact["confidence"] >= .8 and fact["category"] not in SENSITIVE_TWIN_CATEGORIES)))
        with self._connect() as conn:
            conn.execute("UPDATE digital_twin_facts SET value=?,confirmed=?,revoked=?,active=?,updated_at=? WHERE id=?", (value, confirmed, revoked, active, _now(), fact_id))
        return self.get_twin_fact(fact_id)

    def delete_twin_fact(self, fact_id: str) -> bool:
        fact = self.get_twin_fact(fact_id)
        if not fact:
            return False
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM digital_twin_evidence WHERE fact_key=?", (fact["key"],))
            result = conn.execute("DELETE FROM digital_twin_facts WHERE id=?", (fact_id,))
            conn.execute("COMMIT")
        return result.rowcount == 1

    def presence(self, emergency_stopped: bool = False) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT state,source,updated_at FROM presence_state WHERE id=1").fetchone()
        return {"state": "offline" if emergency_stopped else row[0], "day_state": day_state_for(), "source": row[1], "updated_at": row[2]}

    def set_presence(self, state: str, source: str = "runtime") -> dict[str, Any]:
        if state not in PRESENCE_STATES:
            raise ValueError("invalid presence state")
        with self._connect() as conn:
            conn.execute("UPDATE presence_state SET state=?,source=?,updated_at=? WHERE id=1", (state, source[:80], _now()))
        return self.presence()

    def improvement_signal(self, error_type: str, context: str) -> dict[str, Any]:
        signature = hashlib.sha256(f"{error_type}:{context}".encode()).hexdigest()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO improvement_signals(signature,error_type,occurrences,last_seen_at) VALUES(?,?,1,?) "
                "ON CONFLICT(signature) DO UPDATE SET occurrences=occurrences+1,last_seen_at=excluded.last_seen_at",
                (signature, error_type[:120], _now()),
            )
            row = conn.execute("SELECT signature,error_type,occurrences,suggestion_id,quarantined,last_seen_at FROM improvement_signals WHERE signature=?", (signature,)).fetchone()
        return {"signature": row[0], "error_type": row[1], "occurrences": row[2], "suggestion_id": row[3], "quarantined": bool(row[4]), "last_seen_at": row[5]}

    def maybe_propose_improvement(self, error_type: str, context: str, registry: Any) -> dict[str, Any]:
        signal = self.improvement_signal(error_type, context)
        threshold = self._proposal_threshold(registry)
        if not enabled("MICA_SELF_IMPROVEMENT_ENABLED") or signal["occurrences"] < threshold:
            return {**signal, "proposed": False}
        if signal["suggestion_id"] or signal["quarantined"]:
            return {**signal, "proposed": False, "deduplicated": True}
        kind = "config" if "server" in context or error_type.startswith("server.") else "prompt"
        content = (
            _canonical({
                "diagnostic": error_type[:120],
                "context": context[:500],
                "recommendation": "review local thresholds before an explicitly approved change",
            })
            if kind == "config" else
            f"Fehlerklasse: {error_type}\n\nSicherer lokaler Kontext: {context[:500]}\n\n"
            "Vor einer Änderung reproduzieren, Ursache belegen und nur eine kleine Prompt-Anpassung vorschlagen."
        )
        # Local System-1 triage (Laya when enabled, deterministic heuristic
        # otherwise). It enriches the evidence; the occurrences gate stays
        # authoritative so behaviour never depends on model availability.
        from .laya_scorer import triage_signal

        try:
            triage = triage_signal(error_type, context, int(signal["occurrences"]))
        except Exception:
            triage = {"engine": "heuristic", "priority": None, "worth_proposing": None}
        candidate = registry.propose(
            f"recovery-{signal['signature'][:12]}", kind,
            content,
            f"Drei oder mehr gleichartige lokale Fehler; Signatur {signal['signature']}; "
            f"Triage({triage.get('engine')})={triage.get('priority')}",
        )
        try:
            from .dream_rsi import tag_improvement_signature

            tag_improvement_signature(registry, str(candidate["id"]), signal["signature"])
        except Exception:
            pass
        with self._connect() as conn:
            conn.execute("UPDATE improvement_signals SET suggestion_id=? WHERE signature=?", (candidate["id"], signal["signature"]))
        return {**signal, "suggestion_id": candidate["id"], "proposed": True}

    @staticmethod
    def _proposal_threshold(registry: Any) -> int:
        """Read the promoted Dream-RSI exploration policy when available.

        This is the Dream-RSI 'redeploy online' step: a promoted policy
        artifact (data-only, checksum-verified) steers how eagerly the online
        loop proposes. Falls back to the original fixed threshold of 3.
        """
        try:
            from .dream_rsi import POLICY_ARTIFACT_NAME

            artifact = registry.runtime_artifact(POLICY_ARTIFACT_NAME)
            if artifact and artifact.get("kind") == "config":
                value = json.loads(str(artifact.get("content", ""))).get("propose_after_occurrences")
                if isinstance(value, int) and 1 <= value <= 20:
                    return value
        except Exception:
            pass
        return 3

    def quarantine_improvement(self, improvement_id: str) -> bool:
        """Prevent a failed shadow candidate from being proposed again for the same signal."""
        with self._connect() as conn:
            result = conn.execute(
                "UPDATE improvement_signals SET quarantined=1 WHERE suggestion_id=?",
                (improvement_id,),
            )
        return result.rowcount > 0
