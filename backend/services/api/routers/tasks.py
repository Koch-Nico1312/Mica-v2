from __future__ import annotations

import os
import uuid
from fastapi import HTTPException
from typing import Any, Literal
from fastapi import Header, Request
from backend.services.api.schemas import (
    ExecutionResume,
    OutcomeRequest,
    TaskExecution,
    TaskItemCreate,
    TaskItemUpdate,
    TaskRequest,
)


class TasksRoutes:
    def create_task(self, request: TaskRequest) -> dict[str, Any]:
        turn_id = uuid.uuid4().hex
        plan = self.orchestrator.plan(
            request.message,
            request.action,
            request.params,
            request.dry_run,
            turn_id=turn_id,
        )
        self.turn_budget.register_plan(turn_id, plan["task_id"])
        return plan

    def execute_task(self, request: TaskExecution) -> dict[str, Any]:
        if request.dry_run:
            return self._dispatch_task(request)
        task_id = request.task_id or (
            uuid.uuid5(
                uuid.NAMESPACE_URL, "mica-execution:" + request.idempotency_key
            ).hex
            if request.idempotency_key
            else uuid.uuid4().hex
        )
        key = request.idempotency_key or f"task:{task_id}"
        request = request.model_copy(
            update={"task_id": task_id, "idempotency_key": key}
        )
        try:
            cached = self.execution_history.begin(
                key, task_id, request.action, request.params
            )
        except self.IdempotencyConflict as error:
            raise HTTPException(409, str(error)) from error
        if cached is not None:
            return cached
        try:
            result = self._dispatch_task(request)
        except HTTPException as error:
            status = "approval_required" if error.status_code == 403 else "uncertain"
            self.execution_history.finish(key, status, detail=str(error.detail))
            raise
        except Exception:
            self.execution_history.finish(
                key, "uncertain", detail="Ausgang unbekannt; vor Fortsetzung prüfen."
            )
            raise
        self.execution_history.finish(key, result["status"], result)
        return result

    def task_activity(self) -> dict[str, Any]:
        """Read status independently of optional execution feature gates."""
        return {
            "executions": self.execution_history.list(),
            "tasks": self.task_store.list_tasks(),
            "plans": self.phase4_store.list_plans(),
            "presence": {
                **self.phase4_store.presence(
                    emergency_stopped=self.policy.is_emergency_stopped()
                ),
                "emergency_stopped": self.policy.is_emergency_stopped(),
            },
        }

    def host_action_history(self, request: Request):
        self._memory_confirmation(request, "confirm")
        try:
            response = self.httpx.get(
                os.getenv("TOOL_BROKER_URL", "http://tool-broker:8093")
                + "/v1/tools/history",
                timeout=self.httpx.Timeout(15, connect=3),
                trust_env=False,
            )
            response.raise_for_status()
            return response.json()
        except (self.httpx.HTTPError, ValueError) as error:
            raise HTTPException(
                503, "Windows-Aktionsverlauf nicht erreichbar"
            ) from error

    def resume_execution(
        self,
        key: str,
        update: ExecutionResume,
        request: Request,
        x_mica_approval_intent: str | None = Header(default=None),
    ):
        self._memory_confirmation(request, x_mica_approval_intent)
        try:
            saved = self.execution_history.retry_request(key)
        except self.IdempotencyConflict as error:
            raise HTTPException(409, str(error)) from error
        return self.execute_task(
            self.TaskExecution(**saved, approval_id=update.approval_id)
        )

    def reconcile_execution(
        self,
        key: str,
        request: Request,
        x_mica_approval_intent: str | None = Header(default=None),
    ) -> dict[str, Any]:
        self._memory_confirmation(request, x_mica_approval_intent)
        item = next(
            (item for item in self.execution_history.list(500) if item["key"] == key),
            None,
        )
        if not item:
            raise HTTPException(404, "Ausführung nicht gefunden")
        cached = self._broker_execution(key)
        result = cached.get("result")
        if (
            cached.get("status") != "completed"
            or not isinstance(result, dict)
            or (not result.get("dispatched"))
        ):
            return {
                "resolved": False,
                "status": "uncertain",
                "detail": "Kein bestätigtes Ergebnis vorhanden. Die Aktion wird nicht erneut ausgeführt.",
            }
        host = result.get("result") if isinstance(result.get("result"), dict) else {}
        output = host.get("result") if isinstance(host.get("result"), dict) else host
        confirmed = self.ExecutionResult(
            task_id=item["task_id"],
            action=item["action"],
            status="succeeded",
            output=output.get("output", output),
            undo=output.get("undo", host.get("undo")),
        ).model_dump()
        resolved = self.execution_history.reconcile(
            key, cached.get("fingerprint", ""), confirmed
        )
        if resolved:
            self.audit.append(
                "task.reconciled",
                {"task_id": item["task_id"], "action": item["action"]},
            )
        return {
            "resolved": resolved,
            "status": "succeeded" if resolved else item["status"],
        }

    def record_outcome(self, request: OutcomeRequest) -> dict[str, str]:
        return self.orchestrator.record_outcome(
            request.task_id,
            request.action,
            request.success,
            request.evidence,
            request.reproduction,
        )

    def list_task_items(
        self,
        status: Literal["open", "in_progress", "completed", "cancelled"] | None = None,
        priority: Literal["low", "normal", "high"] | None = None,
        overdue: bool = False,
    ) -> dict[str, Any]:
        self._require_phase3()
        return {
            "phase3_enabled": True,
            "tasks": self.task_store.list_tasks(
                status=status, priority=priority, overdue=overdue
            ),
        }

    def create_task_item(self, request: TaskItemCreate) -> dict[str, Any]:
        self._require_phase3()
        try:
            task = self.task_store.create_task(
                request.title, request.description, request.priority, request.due_at
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        self.audit.append(
            "task_item.created",
            {
                "task_id": task["id"],
                "priority": task["priority"],
                "has_due_at": bool(task["due_at"]),
            },
        )
        return task

    def get_task_item(self, task_id: str) -> dict[str, Any]:
        self._require_phase3()
        task = self.task_store.get_task(task_id)
        if not task:
            raise HTTPException(404, "Task item not found")
        return task

    def update_task_item(self, task_id: str, request: TaskItemUpdate) -> dict[str, Any]:
        self._require_phase3()
        changes = request.model_dump(exclude_unset=True)
        try:
            task = self.task_store.update_task(task_id, changes)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        if not task:
            raise HTTPException(404, "Task item not found")
        self.audit.append(
            "task_item.updated",
            {"task_id": task_id, "fields": sorted(changes), "status": task["status"]},
        )
        if task["status"] == "completed":
            self.phase4_store.observe_twin(
                "tasks.preferred_priority",
                task["priority"],
                "preference",
                "task",
                task_id,
                0.9,
            )
        return task

    def _dispatch_task(self, request: TaskExecution) -> dict[str, Any]:
        """Pass execution through the broker; the API itself has no host authority."""
        payload = request.model_dump()
        payload["task_id"] = request.task_id or uuid.uuid4().hex
        if request.dry_run:
            return self.ExecutionResult(
                turn_id=request.turn_id,
                task_id=payload["task_id"],
                status="dry_run",
                action=request.action,
                output="Dry-run: no action was dispatched.",
            ).model_dump()
        preflight = self._windows_preflight_evidence()
        if not preflight.get("ok"):
            self.audit.append(
                "task.preflight_blocked",
                {
                    "turn_id": request.turn_id,
                    "task_id": payload["task_id"],
                    "action": request.action,
                    "error_class": "unavailable",
                },
            )
            return self.ExecutionResult(
                turn_id=request.turn_id,
                task_id=payload["task_id"],
                status="not_dispatched",
                action=request.action,
                output="Phase-0-Preflight ist nicht aktuell und vollstaendig gruen.",
                evidence=[
                    {
                        "type": "phase0_preflight",
                        "fresh": bool(preflight.get("fresh")),
                        "reason": preflight.get("reason", "preflight_not_ready"),
                    }
                ],
                error_class="unavailable",
            ).model_dump()
        try:
            response = self.httpx.post(
                os.getenv("TOOL_BROKER_URL", "http://tool-broker:8093")
                + "/v1/tools/call",
                json=payload,
                timeout=self.httpx.Timeout(30.0, connect=5.0),
            )
            if response.status_code == 403:
                raise HTTPException(
                    403, detail=response.json().get("detail", "Approval required")
                )
            response.raise_for_status()
            result = response.json()
        except HTTPException:
            raise
        except (self.httpx.HTTPError, ValueError) as error:
            raise HTTPException(503, "Local tool broker is unavailable") from error
        audit_event = self.audit.append(
            "task.executed",
            {
                "turn_id": request.turn_id,
                "task_id": result.get("task_id", payload["task_id"]),
                "action": request.action,
                "dispatched": bool(result.get("dispatched")),
            },
        )
        host_response = (
            result.get("result") if isinstance(result.get("result"), dict) else {}
        )
        action_result = (
            host_response.get("result")
            if isinstance(host_response.get("result"), dict)
            else host_response
        )
        return self.ExecutionResult(
            **{
                "schema_version": 1,
                "turn_id": request.turn_id,
                "task_id": result.get("task_id", payload["task_id"]),
                "status": "succeeded" if result.get("dispatched") else "not_dispatched",
                "action": request.action,
                "output": action_result.get("output", action_result),
                "undo": action_result.get("undo", host_response.get("undo")),
                "audit_id": audit_event.get("hash"),
                "error_class": None,
                "evidence": result.get("retrieval", []),
            }
        ).model_dump()

    def _broker_execution(self, key: str) -> dict[str, Any]:
        try:
            response = self.httpx.get(
                os.getenv("TOOL_BROKER_URL", "http://tool-broker:8093")
                + "/v1/tools/execution",
                params={"key": key},
                timeout=self.httpx.Timeout(10, connect=3),
            )
            response.raise_for_status()
            return response.json()
        except (self.httpx.HTTPError, ValueError) as error:
            raise HTTPException(
                503, "Ausführungsergebnis beim Aktionsdienst nicht erreichbar"
            ) from error


ROUTES = [
    ("/v1/tasks", "post", "create_task"),
    ("/v1/tasks/execute", "post", "execute_task"),
    ("/v1/tasks/activity", "get", "task_activity"),
    ("/v1/actions/history", "get", "host_action_history"),
    ("/v1/tasks/executions/{key}/resume", "post", "resume_execution"),
    ("/v1/tasks/executions/{key}/reconcile", "post", "reconcile_execution"),
    ("/v1/tasks/outcome", "post", "record_outcome"),
    ("/v1/task-items", "get", "list_task_items"),
    ("/v1/task-items", "post", "create_task_item"),
    ("/v1/task-items/{task_id}", "get", "get_task_item"),
    ("/v1/task-items/{task_id}", "patch", "update_task_item"),
]
