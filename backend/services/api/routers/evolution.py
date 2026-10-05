from __future__ import annotations

from typing import Any
from fastapi import Header, HTTPException, Request
from pydantic import BaseModel, Field


class QualityCase(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    input: dict[str, Any]
    expected: Any


class QualitySuiteCreate(BaseModel):
    goal: str = Field(min_length=1, max_length=2000)
    source: str = Field(min_length=1, max_length=160)
    cases: list[QualityCase] = Field(min_length=3, max_length=12)


class WorkshopRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    suite_id: str = Field(pattern="^[a-f0-9]{32}$")
    gap_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    intent: str = Field(default="forge", pattern="^(forge|repair)$")
    code: str | None = Field(default=None, min_length=1, max_length=12000)


class RevisionObservation(BaseModel):
    task_id: str = Field(min_length=1, max_length=160)
    success: bool
    duration_ms: float = Field(ge=0, le=86400000, allow_inf_nan=False)
    provider_cost: float = Field(ge=0, le=1000, allow_inf_nan=False)
    user_corrections: int = Field(ge=0, le=1000)
    source: str = Field(min_length=1, max_length=160)


class PreferenceConfirmation(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=1000)
    scope: str = Field(default="global", pattern="^(global|technical|personal|monitoring)$")
    source: str = Field(min_length=1, max_length=160)


class EvolutionRoutes:
    def learned_preferences(self, include_history: bool = False) -> dict[str, Any]:
        return {"preferences": self.evolution.preferences(include_history)}

    def confirm_preference(self, update: PreferenceConfirmation, request: Request,
                           x_mica_approval_intent: str | None = Header(default=None)) -> dict[str, Any]:
        self._memory_confirmation(request, x_mica_approval_intent)
        try:
            rule = self.evolution.confirm(update.key, update.value, update.scope, update.source)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        self.audit.append("evolution.preference_confirmed", {"id": rule["id"], "scope": rule["scope"], "supersedes": rule["supersedes"]})
        return {"preference": rule}

    def forget_preference(self, preference_id: str, request: Request,
                          x_mica_approval_intent: str | None = Header(default=None)) -> dict[str, bool]:
        self._memory_confirmation(request, x_mica_approval_intent)
        deleted = self.evolution.forget(preference_id)
        if not deleted:
            raise HTTPException(404, "Preference not found")
        self.audit.append("evolution.preference_forgotten", {"id": preference_id})
        return {"deleted": deleted}

    def capability_gaps(self) -> dict[str, Any]:
        return {"gaps": self.evolution.gaps()}

    def quality_suites(self) -> dict[str, Any]:
        return {"suites": self.workshop.suites()}

    def create_quality_suite(self, update: QualitySuiteCreate, request: Request,
                             x_mica_approval_intent: str | None = Header(default=None)) -> dict[str, Any]:
        self._memory_confirmation(request, x_mica_approval_intent)
        try:
            suite = self.workshop.create_suite(update.goal, [case.model_dump() for case in update.cases], update.source)
        except (ValueError, TypeError) as error:
            raise HTTPException(422, str(error)) from error
        self.audit.append("evolution.suite_created", {"suite_id": suite["id"], "cases": len(suite["cases"])})
        return {"suite": suite}

    def workshop_jobs(self) -> dict[str, Any]:
        improvements = {item["id"]: item for item in self.improvements.list()}
        return {"jobs": [{**job, "improvement": improvements.get(job["improvement_id"]),
                          "quality": self.workshop.report(job["improvement_id"]),
                          "observations": {"baseline": self.workshop.metrics(job["baseline_id"]),
                                           "candidate": self.workshop.metrics(job["improvement_id"])}}
                         for job in self.workshop.jobs()]}

    def observe_revision(self, improvement_id: str, update: RevisionObservation, request: Request,
                         x_mica_approval_intent: str | None = Header(default=None)) -> dict[str, Any]:
        self._memory_confirmation(request, x_mica_approval_intent)
        try:
            metrics = self.workshop.observe(improvement_id, **update.model_dump())
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        self.audit.append("evolution.revision_observed", {"improvement_id": improvement_id})
        return {"metrics": metrics}

    def stage_workshop(self, update: WorkshopRequest, request: Request,
                       x_mica_approval_intent: str | None = Header(default=None)) -> dict[str, Any]:
        self._memory_confirmation(request, x_mica_approval_intent)
        if self.policy.is_emergency_stopped():
            raise HTTPException(409, "Not-Aus ist aktiv")
        try:
            if update.code is not None:
                result = self.workshop.stage(update.name, update.suite_id, update.code,
                                             gap_id=update.gap_id, intent=update.intent)
            else:
                if self.configured_cloud_provider() and not self.cloud_private_context_allowed():
                    raise HTTPException(403, "Skill-Erzeugung mit privatem Kontext benötigt Cloud-Opt-in")
                result = self.workshop.generate(
                    update.name, update.suite_id,
                    lambda prompt: self._local_completion(prompt, 2048, 0.1, system_prompt="Du erstellst begrenzte MICA-Skills als JSON."),
                    gap_id=update.gap_id, intent=update.intent,
                )
        except (ValueError, TypeError) as error:
            raise HTTPException(422, str(error)) from error
        self.audit.append("evolution.candidate_staged", {"improvement_id": result["proposal"]["id"], "intent": update.intent})
        return result


ROUTES = [
    ("/v1/evolution/preferences", "get", "learned_preferences"),
    ("/v1/evolution/preferences", "post", "confirm_preference"),
    ("/v1/evolution/preferences/{preference_id}", "delete", "forget_preference"),
    ("/v1/evolution/gaps", "get", "capability_gaps"),
    ("/v1/evolution/suites", "get", "quality_suites"),
    ("/v1/evolution/suites", "post", "create_quality_suite"),
    ("/v1/evolution/workshop", "get", "workshop_jobs"),
    ("/v1/evolution/workshop", "post", "stage_workshop"),
    ("/v1/evolution/revisions/{improvement_id}/observations", "post", "observe_revision"),
]
