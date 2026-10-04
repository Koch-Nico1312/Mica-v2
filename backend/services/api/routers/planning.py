from __future__ import annotations
import os
import uuid
from datetime import UTC, datetime, timedelta
from fastapi import HTTPException
from typing import Any
from fastapi import Header, Request
from backend.services.api.schemas import (
    AgentPlanActivation,
    AgentPlanCreate,
    AgentPlanUpdate,
    ServerDiagnosticConfirm,
    ServerScanRequest,
    TwinFactUpdate,
    TwinSettingsUpdate,
)


class PlanningRoutes:
    def reconcile_agent_plan(
        self,
        plan_id: str,
        request: Request,
        x_mica_approval_intent: str | None = Header(default=None),
    ) -> dict[str, Any]:
        self._memory_confirmation(request, x_mica_approval_intent)
        plan = self.phase4_store.get_plan(plan_id)
        if not plan:
            raise HTTPException(404, "Agentenplan nicht gefunden")
        resolved = 0
        for step in plan["steps"]:
            if step["status"] not in {"running", "failed", "blocked"}:
                continue
            cached = self._broker_execution(step["idempotency_key"])
            result = cached.get("result")
            if (
                cached.get("status") == "completed"
                and isinstance(result, dict)
                and result.get("dispatched")
                and (
                    cached.get("fingerprint")
                    == self.IdempotencyStore.fingerprint(step["action"], step["params"])
                )
            ):
                resolved += self.phase4_store.reconcile_step(
                    plan_id, step["id"], step["idempotency_key"], result
                )
        if resolved:
            self.audit.append(
                "agent_plan.reconciled", {"plan_id": plan_id, "steps": resolved}
            )
        return {"resolved_steps": resolved, "plan": self.phase4_store.get_plan(plan_id)}

    def list_agent_plans(self, status: str | None = None) -> dict[str, Any]:
        self._require_phase4("MICA_SELF_PLANNING_ENABLED")
        try:
            plans = self.phase4_store.list_plans(status)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return {"plans": plans}

    def create_agent_plan(self, request: AgentPlanCreate) -> dict[str, Any]:
        self._require_phase4("MICA_SELF_PLANNING_ENABLED")
        if request.task_id:
            self._require_phase3()
            if not self.task_store.get_task(request.task_id):
                raise HTTPException(404, "Task item not found")
        try:
            plan = self.phase4_store.create_plan(
                request.goal,
                [step.model_dump() for step in request.steps]
                if request.steps
                else self.steps_for_goal(request.goal),
                request.budget,
                request.task_id,
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        self.audit.append(
            "agent_plan.created",
            {
                "plan_id": plan["id"],
                "plan_hash": plan["plan_hash"],
                "risk": plan["risk"],
                "status": plan["status"],
            },
        )
        return plan

    def get_agent_plan(self, plan_id: str) -> dict[str, Any]:
        self._require_phase4("MICA_SELF_PLANNING_ENABLED")
        plan = self.phase4_store.get_plan(plan_id)
        if not plan:
            raise HTTPException(404, "Agent plan not found")
        return plan

    def update_agent_plan(
        self, plan_id: str, request: AgentPlanUpdate
    ) -> dict[str, Any]:
        self._require_phase4("MICA_SELF_PLANNING_ENABLED")
        changes = request.model_dump(exclude_unset=True)
        if "steps" in changes and changes["steps"] is not None:
            changes["steps"] = [
                step.model_dump() if hasattr(step, "model_dump") else step
                for step in request.steps or []
            ]
        try:
            plan = self.phase4_store.patch_plan(plan_id, changes)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        if not plan:
            raise HTTPException(404, "Agent plan not found")
        self.audit.append(
            "agent_plan.updated",
            {
                "plan_id": plan_id,
                "plan_hash": plan["plan_hash"],
                "risk": plan["risk"],
                "status": plan["status"],
            },
        )
        return plan

    def dry_run_agent_plan(self, plan_id: str) -> dict[str, Any]:
        self._require_phase4("MICA_SELF_PLANNING_ENABLED")
        try:
            preview = self.phase4_store.dry_run(plan_id, self.policy)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        if not preview:
            raise HTTPException(404, "Agent plan not found")
        self.audit.append(
            "agent_plan.previewed",
            {
                "plan_id": plan_id,
                "plan_hash": preview["plan_hash"],
                "risk": preview["risk"],
                "status": "ready",
            },
        )
        return preview

    def activate_agent_plan(
        self, plan_id: str, request: AgentPlanActivation
    ) -> dict[str, Any]:
        self._require_phase4("MICA_SELF_PLANNING_ENABLED")
        try:
            plan, decision = self.phase4_store.activate(
                plan_id, self.policy, request.approval_id
            )
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        if not plan:
            raise HTTPException(404, "Agent plan not found")
        if not decision.allowed:
            self.phase4_store.set_presence("approval_required", "agent-plan")
            raise HTTPException(
                403,
                detail={"reason": decision.reason, "approval_id": decision.approval_id},
            )
        self.audit.append(
            "agent_plan.activated",
            {
                "plan_id": plan_id,
                "plan_hash": plan["plan_hash"],
                "risk": plan["risk"],
                "status": plan["status"],
            },
        )
        return plan

    def server_agent_status(self) -> dict[str, Any]:
        self._require_phase4("MICA_SERVER_AGENT_ENABLED")
        observations = self.phase4_store.server_observations()
        diagnostics = self.phase4_store.server_diagnostics()
        return {
            "target": observations[0]["target_id"] if observations else None,
            "last_observation": observations[0] if observations else None,
            "open_diagnostics": sum(
                (1 for item in diagnostics if item["status"] == "open")
            ),
            "retention_days": 30,
        }

    def server_agent_observations(self, target_id: str | None = None) -> dict[str, Any]:
        self._require_phase4("MICA_SERVER_AGENT_ENABLED")
        return {"observations": self.phase4_store.server_observations(target_id)}

    def server_agent_diagnostics(self) -> dict[str, Any]:
        self._require_phase4("MICA_SERVER_AGENT_ENABLED")
        return {"diagnostics": self.phase4_store.server_diagnostics()}

    def confirm_server_agent_diagnostic(
        self, diagnostic_id: str, request: ServerDiagnosticConfirm
    ) -> dict[str, Any]:
        self._require_phase4("MICA_SERVER_AGENT_ENABLED")
        diagnostic = self.phase4_store.confirm_server_diagnostic(
            diagnostic_id, self.improvements
        )
        if not diagnostic:
            raise HTTPException(404, "Server diagnostic not found")
        if request.create_plan and (not diagnostic.get("plan_id")):
            plan = self.phase4_store.create_plan(
                f"Bestätigte ZimaOS-Diagnose prüfen: {diagnostic['code']}",
                [
                    {
                        "action": "system.status",
                        "params": {"target_id": diagnostic["target_id"]},
                        "expected_change": "none",
                    },
                    {
                        "action": "docker.status",
                        "params": {"target_id": diagnostic["target_id"]},
                        "expected_change": "none",
                    },
                ],
                task_id=diagnostic["task_id"],
            )
            self.phase4_store.link_diagnostic_plan(diagnostic_id, plan["id"])
            diagnostic["plan_id"] = plan["id"]
        self.audit.append(
            "server_agent.diagnostic_confirmed",
            {
                "diagnostic_id": diagnostic_id,
                "task_id": diagnostic["task_id"],
                "plan_id": diagnostic.get("plan_id"),
                "status": "confirmed",
            },
        )
        return diagnostic

    def scan_server_agent(self, request: ServerScanRequest) -> dict[str, Any]:
        self._require_phase4("MICA_SERVER_AGENT_ENABLED")
        if self.policy.is_emergency_stopped():
            raise HTTPException(409, "Emergency stop is active")
        try:
            snapshot = request.snapshot
            if snapshot is not None and (
                not self.phase4_feature_enabled("MICA_SERVER_AGENT_FIXTURES")
            ):
                raise ValueError(
                    "direct server snapshots are allowed only in the local fixture test mode"
                )
            if snapshot is None:
                system = self._server_read("system.status", request.target_id)
                docker = self._server_read("docker.status", request.target_id)
                snapshot = {**system, "containers": docker.get("containers", [])}
            observation = self.phase4_store.record_server_observation(
                request.target_id, snapshot, self.task_store
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except self.httpx.HTTPError as error:
            raise HTTPException(
                503, "ZimaOS read-only scan failed through the broker"
            ) from error
        self.audit.append(
            "server_agent.scanned",
            {
                "observation_id": observation["id"],
                "status": "diagnostic" if observation["diagnostics"] else "healthy",
            },
        )
        if request.monitor_occurrences:
            schedule = self.schedule_store.create(
                f"ZimaOS-Monitoring: {request.target_id}",
                (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                "server.scan",
                {"target_id": request.target_id},
                {"every_seconds": 300, "occurrences": request.monitor_occurrences},
            )
            observation["monitoring_schedule_id"] = schedule["id"]
            self.audit.append(
                "server_agent.monitor_scheduled",
                {"schedule_id": schedule["id"], "status": "scheduled"},
            )
        return observation

    def digital_twin_settings(self) -> dict[str, Any]:
        self._require_phase4("MICA_DIGITAL_TWIN_ENABLED")
        return self.phase4_store.twin_settings()

    def update_digital_twin_settings(
        self, request: TwinSettingsUpdate
    ) -> dict[str, Any]:
        self._require_phase4("MICA_DIGITAL_TWIN_ENABLED")
        try:
            result = self.phase4_store.update_twin_settings(
                request.model_dump(exclude_unset=True)
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        self.audit.append("digital_twin.settings_updated", {"status": "updated"})
        return result

    def digital_twin_facts(self) -> dict[str, Any]:
        self._require_phase4("MICA_DIGITAL_TWIN_ENABLED")
        return {"facts": self.phase4_store.twin_facts()}

    def update_digital_twin_fact(
        self, fact_id: str, request: TwinFactUpdate
    ) -> dict[str, Any]:
        self._require_phase4("MICA_DIGITAL_TWIN_ENABLED")
        try:
            fact = self.phase4_store.patch_twin_fact(
                fact_id, request.model_dump(exclude_unset=True)
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        if not fact:
            raise HTTPException(404, "Digital twin fact not found")
        self.audit.append(
            "digital_twin.fact_updated",
            {
                "fact_id": fact_id,
                "status": "revoked"
                if fact["revoked"]
                else "active"
                if fact["active"]
                else "pending",
            },
        )
        return fact

    def delete_digital_twin_fact(self, fact_id: str) -> dict[str, bool]:
        self._require_phase4("MICA_DIGITAL_TWIN_ENABLED")
        deleted = self.phase4_store.delete_twin_fact(fact_id)
        if not deleted:
            raise HTTPException(404, "Digital twin fact not found")
        self.audit.append(
            "digital_twin.fact_deleted", {"fact_id": fact_id, "status": "deleted"}
        )
        return {"deleted": True}

    def get_presence(self) -> dict[str, Any]:
        return {
            "phase4_enabled": self.phase4_enabled(),
            "phase45_enabled": self.phase45_enabled(),
            **self.phase4_store.presence(self.policy.is_emergency_stopped()),
        }

    def _server_read(self, action: str, target_id: str) -> dict[str, Any]:
        response = self.httpx.post(
            os.getenv("TOOL_BROKER_URL", "http://tool-broker:8093") + "/v1/tools/call",
            json={
                "task_id": uuid.uuid4().hex,
                "action": action,
                "params": {"target_id": target_id},
                "audit_mode": "ids_only",
            },
            timeout=self.httpx.Timeout(30.0, connect=5.0),
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("result", payload)


ROUTES = [
    ("/v1/agent-plans/{plan_id}/reconcile", "post", "reconcile_agent_plan"),
    ("/v1/agent-plans", "get", "list_agent_plans"),
    ("/v1/agent-plans", "post", "create_agent_plan"),
    ("/v1/agent-plans/{plan_id}", "get", "get_agent_plan"),
    ("/v1/agent-plans/{plan_id}", "patch", "update_agent_plan"),
    ("/v1/agent-plans/{plan_id}/dry-run", "post", "dry_run_agent_plan"),
    ("/v1/agent-plans/{plan_id}/activate", "post", "activate_agent_plan"),
    ("/v1/server-agent/status", "get", "server_agent_status"),
    ("/v1/server-agent/observations", "get", "server_agent_observations"),
    ("/v1/server-agent/diagnostics", "get", "server_agent_diagnostics"),
    (
        "/v1/server-agent/diagnostics/{diagnostic_id}/confirm",
        "post",
        "confirm_server_agent_diagnostic",
    ),
    ("/v1/server-agent/scan", "post", "scan_server_agent"),
    ("/v1/digital-twin/settings", "get", "digital_twin_settings"),
    ("/v1/digital-twin/settings", "patch", "update_digital_twin_settings"),
    ("/v1/digital-twin/facts", "get", "digital_twin_facts"),
    ("/v1/digital-twin/facts/{fact_id}", "patch", "update_digital_twin_fact"),
    ("/v1/digital-twin/facts/{fact_id}", "delete", "delete_digital_twin_fact"),
    ("/v1/presence", "get", "get_presence"),
]
