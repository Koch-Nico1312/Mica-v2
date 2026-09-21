from __future__ import annotations

import os
import time
import uuid

import httpx

from services.common.audit import AuditLog
from services.common.brain import MarkdownBrain
from services.common.health import reset, touch
from services.common.learning import DomainRegistry, LearningService
from services.common.improvements import ImprovementRegistry
from services.common.dream_rsi import attach_dream_rsi
from services.common.policy import PolicyEngine
from services.common.phase4 import Phase4Store, enabled, phase4_enabled
from services.common.scheduler_store import ScheduleStore
from services.common.task_automation import TaskAutomationStore, evaluate_automations


def _dispatch_plan_step(action: str, params: dict, idempotency_key: str, approval_id: str | None = None) -> dict:
    response = httpx.post(
        os.getenv("TOOL_BROKER_URL", "http://tool-broker:8093") + "/v1/tools/call",
        json={"task_id": uuid.uuid4().hex, "action": action, "params": params,
              "idempotency_key": idempotency_key, "approval_id": approval_id, "audit_mode": "ids_only"},
        timeout=httpx.Timeout(60.0, connect=5.0),
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("dispatched", False):
        raise RuntimeError("tool broker did not dispatch the approved plan step")
    return payload


def run_cycle(audit, brain, learning, schedules, tasks, policy, phase4=None, dispatch_plan_step=None, improvements=None, ambient_monitor=None, dream=None) -> dict[str, int | str]:
    """Run one bounded scheduler pass so startup and safety behavior are testable."""
    emergency_stopped = policy.is_emergency_stopped()
    due = [] if emergency_stopped else schedules.claim_due()
    processed = failed = 0
    for schedule in due:
        audit.append("scheduler.due", {
            "schedule_id": schedule["id"], "action": schedule["action"],
            "status": schedule["status"], "task_id": schedule.get("task_id"),
        })
        try:
            if schedule["action"] == "brain.reindex":
                brain.reindex()
            elif schedule["action"] == "learning.monitor":
                result = learning.monitor(
                    str(schedule["params"].get("query", "")),
                    str(schedule["params"].get("domain_id", "")),
                    int(schedule["params"].get("max_sources", 3)),
                )
                audit.append("learning.monitor_completed", {
                    "schedule_id": schedule["id"], "status": result["status"],
                    "brain_document": result.get("draft_id"),
                    "source_count": len(result.get("sources", [])),
                })
            elif schedule["action"] == "reminder.create":
                brain.write(
                    "tasks", f"Erinnerung: {schedule['name']}",
                    "Die verknüpfte lokale Erinnerung ist fällig.",
                    {"schedule_id": schedule["id"], "task_id": schedule.get("task_id"), "reminder": True},
                )
            elif schedule["action"] == "server.scan":
                if phase4 is None or not phase4_enabled() or not enabled("MICA_SERVER_AGENT_ENABLED"):
                    raise RuntimeError("Phase-4 server agent is disabled")
                target_id = str(schedule["params"].get("target_id", ""))
                system_reply = (dispatch_plan_step or _dispatch_plan_step)(
                    "system.status", {"target_id": target_id}, f"{schedule['id']}:system", None,
                )
                docker_reply = (dispatch_plan_step or _dispatch_plan_step)(
                    "docker.status", {"target_id": target_id}, f"{schedule['id']}:docker", None,
                )
                system = system_reply.get("result", system_reply)
                docker = docker_reply.get("result", docker_reply)
                observation = phase4.record_server_observation(
                    target_id, {**system, "containers": docker.get("containers", [])}, tasks,
                )
                audit.append("server_agent.scanned", {
                    "schedule_id": schedule["id"], "observation_id": observation["id"],
                    "status": "diagnostic" if observation["diagnostics"] else "healthy",
                })
            elif schedule["action"] == "dream.rsi":
                if dream is None:
                    raise RuntimeError("Dream-RSI engine is not wired")
                cycle = dream.run_cycle(max_candidates=3, min_pool=3)
                audit.append("dream_rsi.cycle", {
                    "schedule_id": schedule["id"], "status": cycle["status"], "reason": cycle["reason"],
                    "pool_size": int(cycle.get("pool_size", 0)), "candidates": int(cycle.get("candidates", 0)),
                    "proposal_id": str(cycle.get("proposal_id", "") or ""),
                })
            else:
                # Delivery schedules stop at awaiting_approval. The API passes
                # them through the same policy and broker path as immediate delivery.
                brain.write(
                    "tasks", f"Geplant: {schedule['name']}",
                    f"Die Aufgabe ist fällig. Action: `{schedule['action']}`\n\nStatus: `{schedule['status']}`",
                    {"schedule_id": schedule["id"], "task_id": schedule.get("task_id")},
                )
            if schedule["status"] == "due":
                schedules.finish_due(schedule["id"], True)
            processed += 1
        except Exception as error:
            if schedule["status"] == "due":
                schedules.finish_due(schedule["id"], False)
            audit.append("scheduler.failed", {
                "schedule_id": schedule["id"], "error_type": type(error).__name__,
            })
            failed += 1
    automation = evaluate_automations(
        tasks, schedules, brain, audit, emergency_stopped=policy.is_emergency_stopped(),
    )
    ambient_events_count = 0
    if ambient_monitor is not None and not emergency_stopped:
        if phase4 is not None:
            try:
                obs = phase4.server_observations()
                s_events = ambient_monitor.evaluate_server_state(obs)
                ambient_events_count += len(s_events)
            except Exception:
                pass
        try:
            pending_scheds = schedules.list("pending")
            sched_events = ambient_monitor.evaluate_schedules(pending_scheds)
            ambient_events_count += len(sched_events)
        except Exception:
            pass

    plan_result = {"status": "disabled"}
    if phase4 is not None:
        plan_result = phase4.run_one_step(policy, dispatch_plan_step or _dispatch_plan_step, tasks, audit, improvements)
    brain.reindex()
    return {
        "status": "stopped" if emergency_stopped else "completed",
        "processed": processed, "failed": failed,
        "automations_executed": int(automation["executed"]),
        "automations_failed": int(automation["failed"]),
        "ambient_events": ambient_events_count,
        "plan_status": str(plan_result["status"]),
    }


if __name__ == "__main__":
    audit, brain = AuditLog(), MarkdownBrain()
    learning = LearningService(brain, DomainRegistry(), lambda _prompt: "")
    schedules = ScheduleStore(os.getenv("SCHEDULE_DB", "/data/scheduler.sqlite3"))
    tasks = TaskAutomationStore(os.getenv("SCHEDULE_DB", "/data/scheduler.sqlite3"))
    policy = PolicyEngine(os.getenv("APPROVAL_DB", "/data/approvals.sqlite3"))
    phase4 = Phase4Store(os.getenv("MICA_STATE_DB", os.getenv("SCHEDULE_DB", "/data/scheduler.sqlite3")))
    improvements = ImprovementRegistry(os.getenv("IMPROVEMENT_DB", "/data/improvements.sqlite3"), brain)
    # Dream-RSI records every improvement lifecycle event into the discovery
    # tree and provides the dream engine for scheduled dream.rsi cycles. This
    # process has no LLM, so the engine gets no summarizer (a stub returning ""
    # would only spend one useless candidate call per cycle) — and it still
    # honours the emergency stop even if a due schedule slipped through.
    dream = attach_dream_rsi(
        improvements, brain,
        summarizer=None,
        emergency_stopped=policy.is_emergency_stopped,
    )
    reset("scheduler")
    audit.append("scheduler.started", {"mode": "local", "poll_seconds": 30})
    while True:
        try:
            run_cycle(audit, brain, learning, schedules, tasks, policy, phase4, improvements=improvements, dream=dream)
            # This proves a complete scheduling/index pass rather than only PID 1.
            touch("scheduler")
        except Exception as error:
            # One bad local item must not terminate the long-running scheduler.
            try:
                audit.append("scheduler.cycle_failed", {"error_type": type(error).__name__})
            except Exception:
                pass
        time.sleep(30)
