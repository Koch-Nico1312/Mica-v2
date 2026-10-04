from __future__ import annotations
import os
from datetime import datetime
from fastapi import HTTPException
from typing import Any
from backend.services.api.schemas import (
    AutomationRuleCreate,
    AutomationRuleUpdate,
    ImprovementPromotion,
    ScheduleRequest,
)


class SchedulesRoutes:
    def list_automation_rules(self) -> dict[str, Any]:
        self._require_phase3()
        return {
            "phase3_enabled": True,
            "automations_enabled": self.automations_enabled(),
            "rules": self.task_store.list_rules(),
        }

    def create_automation_rule(self, request: AutomationRuleCreate) -> dict[str, Any]:
        self._require_phase3()
        try:
            rule = self.task_store.create_rule(
                request.name,
                request.trigger,
                request.action,
                request.cooldown_seconds,
                request.max_runs,
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        self.audit.append(
            "automation_rule.created",
            {
                "rule_id": rule["id"],
                "trigger": rule["trigger"],
                "action": rule["action"],
            },
        )
        return rule

    def update_automation_rule(
        self, rule_id: str, request: AutomationRuleUpdate
    ) -> dict[str, Any]:
        self._require_phase3()
        current = self.task_store.get_rule(rule_id)
        if not current:
            raise HTTPException(404, "Automation rule not found")
        changes = request.model_dump(exclude_unset=True)
        if changes.get("enabled") is True and (not current["enabled"]):
            if not self.automations_enabled():
                raise HTTPException(
                    409, "Automations are disabled; set MICA_AUTOMATIONS_ENABLED=1"
                )
            decision = self.policy.decide(
                "automation.enable", {"rule_id": rule_id, "enabled": True}
            )
            if not decision.allowed:
                raise HTTPException(
                    403,
                    detail={
                        "reason": decision.reason,
                        "approval_id": decision.approval_id,
                    },
                )
        try:
            rule = self.task_store.update_rule(rule_id, changes)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        self.audit.append(
            "automation_rule.updated",
            {
                "rule_id": rule_id,
                "fields": sorted(changes),
                "enabled": bool(rule and rule["enabled"]),
            },
        )
        return rule or {}

    def preview_automation_rule(self, rule_id: str) -> dict[str, Any]:
        self._require_phase3()
        preview = self.dry_run_rule(self.task_store, self.schedule_store, rule_id)
        if not preview:
            raise HTTPException(404, "Automation rule not found")
        self.audit.append(
            "automation_rule.previewed",
            {"rule_id": rule_id, "candidate_count": preview["candidate_count"]},
        )
        return preview

    def list_schedules(self, status: str | None = None) -> dict[str, Any]:
        return {"schedules": self.schedule_store.list(status)}

    def create_schedule(self, request: ScheduleRequest) -> dict[str, Any]:
        if request.task_id:
            self._require_phase3()
            if not self.task_store.get_task(request.task_id):
                raise HTTPException(404, "Task item not found")
        if request.action in {"reminder.create", "reminder.dispatch"}:
            creation_params = {
                "name": request.name,
                "run_at": request.run_at,
                "action": request.action,
                "params": request.params,
                "recurrence": request.recurrence.model_dump()
                if request.recurrence
                else None,
                "task_id": request.task_id,
            }
            decision = self.policy.decide("reminder.create", creation_params)
            if not decision.allowed:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "reason": decision.reason,
                        "approval_id": decision.approval_id,
                    },
                )
        try:
            schedule = self.schedule_store.create(
                request.name,
                request.run_at,
                request.action,
                request.params,
                request.recurrence.model_dump() if request.recurrence else None,
                request.task_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        self.audit.append(
            "schedule.created",
            {
                "schedule_id": schedule["id"],
                "action": schedule["action"],
                "has_recurrence": bool(schedule["recurrence"]),
                "task_id": schedule.get("task_id"),
            },
        )
        hour = datetime.fromisoformat(schedule["run_at"]).hour
        period = (
            "morning"
            if 5 <= hour < 11
            else "day"
            if 11 <= hour < 18
            else "evening"
            if 18 <= hour < 23
            else "night"
        )
        self.phase4_store.observe_twin(
            "schedules.preferred_period",
            period,
            "preference",
            "schedule",
            schedule["id"],
            0.85,
        )
        self.brain.write(
            "tasks",
            f"Geplant: {schedule['name']}",
            f"Fällig: {schedule['run_at']}\n\nAction: `{schedule['action']}`",
            {"schedule_id": schedule["id"]},
        )
        return schedule

    def cancel_schedule(self, schedule_id: str) -> dict[str, bool]:
        cancelled = self.schedule_store.cancel(schedule_id)
        if cancelled:
            self.audit.append("schedule.cancelled", {"schedule_id": schedule_id})
        return {"cancelled": cancelled}

    def dispatch_due_schedule(
        self, schedule_id: str, request: ImprovementPromotion
    ) -> dict[str, Any]:
        schedule = self.schedule_store.get(schedule_id)
        if (
            not schedule
            or schedule["status"] != "awaiting_approval"
            or schedule["action"] not in {"message.send", "reminder.dispatch"}
        ):
            raise HTTPException(
                409, "Schedule is not awaiting an external-message approval"
            )
        dispatch_action = "message.send"
        try:
            response = self.httpx.post(
                os.getenv("TOOL_BROKER_URL", "http://tool-broker:8093")
                + "/v1/tools/call",
                json={
                    "task_id": schedule_id,
                    "action": dispatch_action,
                    "params": schedule["params"],
                    "approval_id": request.approval_id,
                },
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
            self.schedule_store.finish_delivery(schedule_id, False)
            raise HTTPException(
                503, "Scheduled delivery failed and was recorded"
            ) from error
        completed = self.schedule_store.finish_delivery(
            schedule_id, bool(result.get("dispatched"))
        )
        self.audit.append(
            "schedule.dispatched",
            {
                "schedule_id": schedule_id,
                "action": dispatch_action,
                "completed": completed,
            },
        )
        return {"completed": completed, "result": result}


ROUTES = [
    ("/v1/automations/rules", "get", "list_automation_rules"),
    ("/v1/automations/rules", "post", "create_automation_rule"),
    ("/v1/automations/rules/{rule_id}", "patch", "update_automation_rule"),
    ("/v1/automations/rules/{rule_id}/dry-run", "post", "preview_automation_rule"),
    ("/v1/schedules", "get", "list_schedules"),
    ("/v1/schedules", "post", "create_schedule"),
    ("/v1/schedules/{schedule_id}", "delete", "cancel_schedule"),
    ("/v1/schedules/{schedule_id}/dispatch", "post", "dispatch_due_schedule"),
]
