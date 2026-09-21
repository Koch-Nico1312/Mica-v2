from __future__ import annotations

import os
import json
import re
import ssl
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from services.common.audit import AuditIntegrityError, AuditLog
from services.common.brain import MarkdownBrain
from services.common.capabilities import RISK_READ, RISK_REVERSIBLE, capability_for
from services.common.connectors import ConnectorRegistry
from services.common.idempotency import IdempotencyConflict, IdempotencyStore
from services.common.orchestrator import Orchestrator
from services.common.operations import OperationLedger
from services.common.policy import PolicyEngine, is_destructive
from services.common.turn_budget import TurnBudget, TurnBudgetExceeded

app = FastAPI(title="MICA tool broker")
policy = PolicyEngine(os.getenv("APPROVAL_DB", "/data/approvals.sqlite3"))
audit = AuditLog()
brain = MarkdownBrain()
connectors = ConnectorRegistry(os.getenv("CONNECTOR_DB", "/data/connectors.sqlite3"))
orchestrator = Orchestrator(brain, audit, policy)
idempotency = IdempotencyStore(os.getenv("IDEMPOTENCY_DB", "/data/idempotency.sqlite3"))
operations = OperationLedger(os.getenv(
    "OPERATIONS_DB", str(Path(os.getenv("AUDIT_PATH", "/data/audit/events.jsonl")).parent / "operations.sqlite3"),
))
turn_budget = TurnBudget(os.getenv(
    "TURN_BUDGET_DB", str(Path(os.getenv("AUDIT_PATH", "/data/audit/events.jsonl")).parent / "turn-budget.sqlite3"),
))
HOST_AGENT_REQUEST_TTL = max(30, min(int(os.getenv("MICA_HOST_AGENT_REQUEST_TTL_SECONDS", "120")), 300))


class ToolCall(BaseModel):
    schema_version: int = Field(default=1, ge=1, le=1)
    turn_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    task_id: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern=r"^[a-f0-9]{32}$")
    action: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    params: dict[str, Any] = Field(default_factory=dict, max_length=64)
    approval_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    idempotency_key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.:-]{8,128}$")
    dry_run: bool = False
    audit_mode: Literal["default", "ids_only"] = "default"


class HostAgentStop(BaseModel):
    active: bool


class HostAgentConfigurationError(ValueError):
    pass


class HostAgentClient:
    """Outbound-only mTLS client for a separately deployed, scoped host agent."""

    def __init__(self, base_url: str):
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise HostAgentConfigurationError("MICA_HOST_AGENT_URL must be an https URL")
        self.base_url = base_url.rstrip("/")
        self.ca_file = Path(os.getenv("MICA_HOST_AGENT_CA_FILE", ""))
        self.cert_file = Path(os.getenv("MICA_HOST_AGENT_CERT_FILE", ""))
        self.key_file = Path(os.getenv("MICA_HOST_AGENT_KEY_FILE", ""))
        if not all(str(item) and item.is_file() for item in (self.ca_file, self.cert_file, self.key_file)):
            raise HostAgentConfigurationError("Host-agent CA, client certificate, and key must be mounted as files")

    @classmethod
    def from_environment(cls) -> HostAgentClient | None:
        base_url = os.getenv("MICA_HOST_AGENT_URL", "").strip()
        return cls(base_url) if base_url else None

    def _ssl_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context(cafile=str(self.ca_file))
        context.load_cert_chain(certfile=str(self.cert_file), keyfile=str(self.key_file))
        return context

    def execute(self, action: str, params: dict[str, Any], approval_id: str | None) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        expires_at = (datetime.now(UTC) + timedelta(seconds=HOST_AGENT_REQUEST_TTL)).isoformat()
        payload = {
            "request_id": request_id,
            "scope": action,
            "params": params,
            "approval_id": approval_id,
            "expires_at": expires_at,
        }
        try:
            with httpx.Client(
                verify=self._ssl_context(),
                trust_env=False,
                timeout=httpx.Timeout(15.0, connect=5.0),
            ) as client:
                response = client.post(self.base_url + "/v1/execute", json=payload)
                response.raise_for_status()
                result = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise HTTPException(502, "Scoped host agent rejected or could not complete the request") from error
        if not isinstance(result, dict):
            raise HTTPException(502, "Host agent returned an invalid response")
        return result

    def set_emergency_stop(self, active: bool) -> dict[str, Any]:
        try:
            with httpx.Client(
                verify=self._ssl_context(),
                trust_env=False,
                timeout=httpx.Timeout(10.0, connect=5.0),
            ) as client:
                response = client.post(self.base_url + "/v1/emergency-stop", json={"active": active})
                response.raise_for_status()
                result = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise HTTPException(502, "Host-agent emergency control failed") from error
        return result if isinstance(result, dict) else {"active": active}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "authority": "allowlisted-only"}


@app.post("/v1/emergency-stop")
def emergency_stop(control: HostAgentStop) -> dict[str, Any]:
    if control.active:
        policy.set_emergency_stop(True)
    try:
        host_agent = HostAgentClient.from_environment()
    except HostAgentConfigurationError as error:
        raise HTTPException(503, "Host-agent mTLS is not configured") from error
    remote = host_agent.set_emergency_stop(control.active) if host_agent else {"configured": False, "active": control.active}
    if not control.active:
        policy.set_emergency_stop(False)
    audit.append("broker.emergency_stop", {"active": control.active, "host_agent": remote})
    return {"active": control.active, "host_agent": remote}


def _request_approval_error(reason: str, approval_id: str | None) -> HTTPException:
    detail: dict[str, str] = {"reason": reason}
    if approval_id:
        detail["approval_id"] = approval_id
    return HTTPException(status_code=403, detail=detail)


def _dispatch_connector(params: dict[str, Any]) -> dict[str, Any]:
    connector = str(params.get("connector", "")).strip().lower()
    message = str(params.get("message", params.get("text", ""))).strip()
    if not message or len(message) > 16000:
        raise HTTPException(422, "An external message of at most 16000 characters is required")
    if not connectors.enabled(connector):
        raise HTTPException(409, "Connector is disabled")
    try:
        if connector == "telegram":
            token = os.getenv("MICA_TELEGRAM_BOT_TOKEN", "").strip()
            chat_id = str(params.get("chat_id") or os.getenv("MICA_TELEGRAM_CHAT_ID", "")).strip()
            if not token or not chat_id:
                raise HTTPException(409, "Telegram token or chat id is not configured")
            response = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": message}, timeout=20)
        elif connector == "whatsapp":
            token = os.getenv("MICA_WHATSAPP_ACCESS_TOKEN", "").strip()
            phone_id = os.getenv("MICA_WHATSAPP_PHONE_NUMBER_ID", "").strip()
            recipient = str(params.get("to", "")).strip()
            if not token or not phone_id or not re.fullmatch(r"\+?[0-9]{7,18}", recipient):
                raise HTTPException(422, "WhatsApp credentials and a valid recipient are required")
            response = httpx.post(
                f"https://graph.facebook.com/v23.0/{phone_id}/messages",
                headers={"Authorization": f"Bearer {token}"},
                json={"messaging_product": "whatsapp", "to": recipient, "type": "text", "text": {"body": message}}, timeout=20,
            )
        elif connector == "push":
            endpoint = connectors.endpoint(connector).rstrip("/")
            topic = str(params.get("topic") or os.getenv("MICA_PUSH_TOPIC", "mica")).strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", topic):
                raise HTTPException(422, "Invalid push topic")
            headers = {"Title": str(params.get("title", "MICA"))[:120]}
            push_token = os.getenv("MICA_PUSH_TOKEN", "").strip()
            if push_token:
                headers["Authorization"] = f"Bearer {push_token}"
            response = httpx.post(f"{endpoint}/{topic}", content=message.encode("utf-8"), headers=headers, timeout=20)
        else:  # Asterisk ARI, opt-in and normally LAN-only.
            endpoint = connectors.endpoint(connector).rstrip("/")
            ari_user, ari_password = os.getenv("MICA_SIP_ARI_USER", ""), os.getenv("MICA_SIP_ARI_PASSWORD", "")
            destination = str(params.get("destination", "")).strip()
            allowed_destinations = {item.strip() for item in os.getenv("MICA_SIP_ALLOWED_DESTINATIONS", "").split(",") if item.strip()}
            if not re.fullmatch(r"SIP/[A-Za-z0-9+_.-]{1,80}", destination) or destination not in allowed_destinations:
                raise HTTPException(422, "SIP destination must be an allowlisted SIP/channel endpoint")
            response = httpx.post(
                endpoint + "/channels", auth=(ari_user, ari_password),
                params={"endpoint": destination, "extension": str(params.get("extension", "mica"))[:40],
                        "context": str(params.get("context", "mica-outbound"))[:40], "priority": 1,
                        "callerId": str(params.get("caller_id", "MICA"))[:40]}, timeout=20,
            )
        response.raise_for_status()
    except HTTPException:
        raise
    except httpx.HTTPError as error:
        raise HTTPException(502, "External connector rejected the message") from error
    return {"connector": connector, "external": True, "status_code": response.status_code}


def _retrieval_influence(retrieval: list[dict[str, Any]]) -> dict[str, Any]:
    """Expose exactly how local recall constrained a dispatch decision.

    Recall may never silently rewrite approved parameters.  Instead prior
    Lessons are carried into the authorization record and caller response, so
    a repeated operation remains explicit while its known failure evidence is
    visible before the host-agent call is made.
    """
    lessons = [str(item["id"]) for item in retrieval if item.get("kind") == "lessons"]
    return {
        "retrieval_before_dispatch": True,
        "prior_lesson_ids": lessons,
        "parameter_mutation": "none; approved parameters remain exact",
        "effect": "prior failure evidence was attached to this authorization" if lessons else "no matching prior lesson",
    }


@app.post("/v1/tools/call")
def call_tool(call: ToolCall) -> dict[str, Any]:
    """Authorize a named operation; never execute a model-supplied shell string."""
    if call.dry_run:
        raise HTTPException(409, "Dry-run requests must remain in the planning endpoint")
    try:
        effective_turn_id = turn_budget.claim_tool_call(call.task_id, call.turn_id)
    except TurnBudgetExceeded as error:
        raise HTTPException(429, str(error)) from error
    # Retrieval is part of the broker boundary, rather than an optional caller
    # convention.  Consequently even direct broker clients receive the same
    # runbook/error recall before policy evaluation and dispatch.
    retrieval_query = f"{call.action} {json.dumps(call.params, ensure_ascii=False, sort_keys=True)}"
    retrieval = brain.search(retrieval_query, limit=5)
    retrieval_ids = [item["id"] for item in retrieval]
    retrieval_influence = _retrieval_influence(retrieval)
    capability = capability_for(call.action)
    risk = capability.risk_for(call.params) if capability is not None else None
    # Keep the established direct destructive-call contract compatible: its
    # exact single-use approval is already replay protection. Reversible
    # mutations may be retried and therefore require an idempotency key.
    if capability is not None and risk == RISK_REVERSIBLE and not call.idempotency_key:
        # Validate before a one-shot approval can be consumed.
        raise HTTPException(422, "This capability requires an idempotency key")
    # A destructive confirmation is intentionally consumed before dispatch.
    # Do this before `decide`: calling `decide` first would create a needless
    # second pending approval for an already confirmed request.
    if is_destructive(call.action, call.params) and call.approval_id:
        if policy.is_emergency_stopped():
            raise HTTPException(status_code=403, detail="Emergency stop is active")
        if policy.consume_approval(call.approval_id, call.action, call.params):
            decision = None
        else:
            decision = policy.decide(call.action, call.params)
    else:
        decision = policy.decide(call.action, call.params)
    if decision and decision.requires_approval:
        # A supplied id was absent, expired, mismatched, or already consumed.
        # Return the newly created exact approval rather than silently reusing
        # the stale one.
        raise _request_approval_error(decision.reason, decision.approval_id)
    elif decision and not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)
    authorized_risk = risk or (decision.risk if decision is not None else "destructive")

    if call.idempotency_key:
        try:
            cached = idempotency.begin(call.idempotency_key, call.action, call.params)
        except IdempotencyConflict as error:
            raise HTTPException(409, str(error)) from error
        if cached is not None:
            return {**cached, "idempotent_replay": True}

    try:
        host_agent = HostAgentClient.from_environment()
    except HostAgentConfigurationError as error:
        if call.idempotency_key:
            idempotency.abandon(call.idempotency_key)
        raise HTTPException(503, "Host-agent mTLS is not configured") from error

    try:
        authorized_event = {
            "turn_id": effective_turn_id, "task_id": call.task_id,
            "risk": authorized_risk,
            "status": "authorized",
        } if call.audit_mode == "ids_only" else {
            "turn_id": effective_turn_id,
            "task_id": call.task_id,
            "action": call.action,
            "params": call.params,
            "approval_id": call.approval_id,
            "host_agent_configured": bool(host_agent),
            "brain_references": retrieval_ids,
            "retrieval_influence": retrieval_influence,
        }
        audit.append("tool.authorized", authorized_event)
    except AuditIntegrityError as error:
        if call.idempotency_key:
            idempotency.abandon(call.idempotency_key)
        # Failing closed is important: an operation must not proceed if it
        # cannot be represented in the tamper-evident audit trail.
        raise HTTPException(503, "Audit integrity check failed; operation was not dispatched") from error

    if call.action == "message.send":
        started = time.monotonic()
        try:
            result = _dispatch_connector(call.params)
        except HTTPException as error:
            operations.record(
                action=call.action, provider=str(call.params.get("connector", "unknown")),
                turn_id=effective_turn_id, task_id=call.task_id, duration_ms=round((time.monotonic() - started) * 1000),
                error_class=f"http_{error.status_code}", external=True,
            )
            orchestrator.record_outcome(call.task_id, call.action, False, str(error.detail), "Retry the same connector call after verifying opt-in, endpoint and local approval.")
            raise
        operations.record(
            action=call.action, provider=str(result.get("connector", "unknown")),
            turn_id=effective_turn_id, task_id=call.task_id,
            duration_ms=round((time.monotonic() - started) * 1000), external=True,
        )
        audit.append("connector.dispatched", result)
        orchestrator.record_outcome(call.task_id, call.action, True, json.dumps(result, ensure_ascii=False, sort_keys=True))
        response = {"task_id": call.task_id, "authorized": True, "action": call.action, "dispatched": True, "result": result, "retrieval": retrieval, "retrieval_influence": retrieval_influence}
        if call.idempotency_key:
            idempotency.complete(call.idempotency_key, response)
        return response

    if host_agent is None:
        if call.idempotency_key:
            idempotency.abandon(call.idempotency_key)
        if call.audit_mode != "ids_only":
            orchestrator.record_outcome(call.task_id, call.action, False, "No scoped host agent is configured.", "Retry the same call with mTLS host-agent configuration and the identical parameters.")
        operations.record(
            action=call.action, provider="windows_host", task_id=call.task_id,
            turn_id=effective_turn_id, duration_ms=0, error_class="unavailable",
        )
        return {"task_id": call.task_id, "authorized": True, "action": call.action, "dispatched": False, "retrieval": retrieval, "retrieval_influence": retrieval_influence}

    started = time.monotonic()
    try:
        result = host_agent.execute(call.action, call.params, call.approval_id)
        dispatched_event = {
            "task_id": call.task_id, "request_id": result.get("request_id", ""),
            "risk": authorized_risk, "status": "dispatched",
        } if call.audit_mode == "ids_only" else {"action": call.action, "request_id": result.get("request_id", "")}
        audit.append("tool.dispatched", dispatched_event)
        if call.audit_mode != "ids_only":
            orchestrator.record_outcome(call.task_id, call.action, True, json.dumps(result, ensure_ascii=False, sort_keys=True))
    except HTTPException as error:
        operations.record(
            action=call.action, provider="windows_host", task_id=call.task_id,
            turn_id=effective_turn_id, duration_ms=round((time.monotonic() - started) * 1000),
            error_class=f"http_{error.status_code}",
        )
        if call.audit_mode != "ids_only":
            orchestrator.record_outcome(call.task_id, call.action, False, str(error.detail), "Retry the identical request after inspecting the host-agent health and scoped configuration.")
        raise
    except AuditIntegrityError as error:
        raise HTTPException(503, "Audit integrity check failed after host-agent response") from error
    operations.record(
        action=call.action, provider="windows_host", task_id=call.task_id,
        turn_id=effective_turn_id, duration_ms=round((time.monotonic() - started) * 1000),
    )
    response = {"task_id": call.task_id, "authorized": True, "action": call.action, "dispatched": True, "result": result, "retrieval": retrieval, "retrieval_influence": retrieval_influence}
    if call.idempotency_key:
        idempotency.complete(call.idempotency_key, response)
    return response
