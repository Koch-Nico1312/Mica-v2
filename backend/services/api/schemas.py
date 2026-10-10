from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from backend.services.common.contracts import ExecutionRequest, bounded_mapping
from backend.services.common.vision import MAX_IMAGE_BYTES

# Base64 expands by 4/3 plus padding. Reject larger payloads at validation time
# so an oversized image is never decoded before the engine's own 5 MB limit.
MAX_IMAGE_BASE64_CHARS = (MAX_IMAGE_BYTES + 2) // 3 * 4


class TaskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=16000)
    action: str | None = None
    params: dict[str, Any] = Field(default_factory=dict, max_length=64)
    dry_run: bool = True

    @field_validator("params")
    @classmethod
    def params_stay_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        return bounded_mapping(value)


class TaskExecution(ExecutionRequest):
    """Compatibility name for the versioned shared execution contract."""


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=16000)
    remember: bool = True
    conversation_mode: str = Field(default="personal", max_length=32)
    memory_mode: Literal["recall", "reflect"] = "recall"
    dialog_context: str = Field(default="", max_length=90000)
    response_style: Literal["brief", "normal", "detailed"] = "normal"


class CognitiveSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    profile: Literal["low_vram", "balanced"] = "balanced"


class BrainDocumentUpdate(BaseModel):
    body: str = Field(max_length=100000)
    memory_excerpt: str | None = Field(default=None, max_length=1800)


class TurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=16000)
    remember: bool = True
    action: str | None = Field(default=None, pattern="^[a-z][a-z0-9_.-]{0,63}$")
    params: dict[str, Any] = Field(default_factory=dict, max_length=64)
    dry_run: bool = True
    client: str = Field(default="pyqt", pattern="^(pyqt|pwa|voice)$")
    conversation_mode: str = Field(default="personal", max_length=32)
    session_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    native_commands: bool = False
    response_style: Literal["brief", "normal", "detailed"] = "normal"

    @field_validator("params")
    @classmethod
    def params_stay_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        return bounded_mapping(value)


class ContextDocument(BaseModel):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(max_length=32000)
    source: Literal["text", "pdf", "screenshot"]


class DialogContextUpdate(BaseModel):
    session_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    documents: list[ContextDocument] = Field(default_factory=list, max_length=8)

    @field_validator("documents")
    @classmethod
    def bounded_documents(cls, documents):
        if sum(len(doc.body) for doc in documents) > 64000:
            raise ValueError("Ausgewählte Dokumente sind zusammen zu groß.")
        if len({doc.id for doc in documents}) != len(documents):
            raise ValueError("Dokumente dürfen nicht doppelt ausgewählt sein.")
        return documents


class TextTransformRequest(BaseModel):
    text: str = Field(min_length=1, max_length=16000)
    operation: Literal['explain', 'summarize', 'translate', 'rewrite', 'bullets']
    language: str = Field(default='Deutsch', min_length=1, max_length=80)


class DocumentDraftRequest(DialogContextUpdate):
    operation: Literal['tasks', 'cards']
    instruction: str = Field(default='', max_length=1000)


class DialogResume(DialogContextUpdate):
    task_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    next_step: str = Field(default='', max_length=2000)


class NativeCommandResult(BaseModel):
    session_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    turn_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    reply: str = Field(min_length=1, max_length=2000)


class ApprovalRequest(BaseModel):
    approved: bool


class ApprovalLogin(BaseModel):
    secret: str = Field(min_length=1, max_length=512)


class EmergencyStopRequest(BaseModel):
    active: bool


class OutcomeRequest(BaseModel):
    task_id: str
    action: str
    success: bool
    evidence: str = Field(min_length=1, max_length=16000)
    reproduction: str = ""


class RecurrenceRequest(BaseModel):
    """Finite interval recurrence; intentionally no unbounded cron expressions."""

    every_seconds: int = Field(ge=60, le=366 * 24 * 60 * 60)
    occurrences: int = Field(ge=2, le=1000)


class ScheduleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    run_at: str = Field(min_length=1, max_length=64)
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    recurrence: RecurrenceRequest | None = None
    task_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    approval_id: str | None = None


class TaskItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    priority: Literal["low", "normal", "high"] = "normal"
    due_at: str | None = Field(default=None, max_length=64)
    idempotency_key: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')


class TaskItemUpdate(BaseModel):
    expected_updated_at: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    status: Literal["open", "in_progress", "completed", "cancelled"] | None = None
    priority: Literal["low", "normal", "high"] | None = None
    due_at: str | None = Field(default=None, max_length=64)


class TaskDecomposeRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default='', max_length=4000)


class AutomationRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    trigger: Literal["task.overdue", "schedule.failed"]
    action: Literal["reminder.create", "task.create"]
    cooldown_seconds: int = Field(default=3600, ge=60, le=2592000)
    max_runs: int = Field(default=10, ge=1, le=100)


class AutomationRuleUpdate(BaseModel):
    enabled: bool | None = None
    cooldown_seconds: int | None = Field(default=None, ge=60, le=2592000)
    max_runs: int | None = Field(default=None, ge=1, le=100)


class ResearchRequest(BaseModel):
    schema_version: Literal[1] = 1
    topic: str = Field(min_length=3, max_length=500)
    domain_id: str = Field(pattern="^[a-z0-9]+(?:-[a-z0-9]+)*$")
    max_sources: int = Field(default=3, ge=1, le=5)


class LearningDomainUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None
    source_hosts: list[str] | None = Field(default=None, min_length=1, max_length=40)
    approval_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")


class LearningReview(BaseModel):
    review_status: Literal["reviewed", "rejected"]


class LearningMonitorRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    domain_id: str = Field(pattern="^[a-z0-9]+(?:-[a-z0-9]+)*$")
    every_seconds: int = Field(default=86400, ge=3600, le=366 * 24 * 60 * 60)
    occurrences: int = Field(default=30, ge=2, le=1000)
    max_sources: int = Field(default=3, ge=1, le=5)


class ImprovementProposal(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    kind: str
    content: str = Field(min_length=1, max_length=16000)
    evidence: str = Field(min_length=1, max_length=4000)


class ImprovementEvaluation(BaseModel):
    approval_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    auto_promote: bool = False


class ImprovementPromotion(BaseModel):
    approval_id: str | None = None


class DreamCycleRequest(BaseModel):
    max_candidates: int = Field(default=3, ge=1, le=5)


class AgentPlanStep(BaseModel):
    action: str = Field(pattern="^[a-z][a-z0-9_.-]{0,63}$")
    params: dict[str, Any] = Field(default_factory=dict, max_length=64)
    expected_change: str = Field(default="", max_length=500)

    @field_validator("params")
    @classmethod
    def params_stay_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        return bounded_mapping(value)


class AgentPlanCreate(BaseModel):
    goal: str = Field(min_length=1, max_length=1000)
    steps: list[AgentPlanStep] | None = Field(default=None, min_length=1, max_length=12)
    task_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    budget: dict[str, int] | None = None


class AgentPlanUpdate(BaseModel):
    status: Literal["paused", "cancelled"] | None = None
    steps: list[AgentPlanStep] | None = Field(default=None, min_length=1, max_length=12)
    budget: dict[str, int] | None = None


class AgentPlanActivation(BaseModel):
    approval_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")


class ServerScanRequest(BaseModel):
    target_id: str = Field(default="zimaos-local", pattern="^[A-Za-z0-9_.-]{1,64}$")
    snapshot: dict[str, Any] | None = None
    monitor_occurrences: int | None = Field(default=None, ge=2, le=288)

    @field_validator("snapshot")
    @classmethod
    def snapshot_stays_bounded(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return value if value is None else bounded_mapping(value)


class ServerDiagnosticConfirm(BaseModel):
    create_plan: bool = False


class TwinSettingsUpdate(BaseModel):
    enabled: bool | None = None
    cloud_opt_in: bool | None = None


class TwinFactUpdate(BaseModel):
    value: str | None = Field(default=None, min_length=1, max_length=1000)
    confirmed: bool | None = None
    revoked: bool | None = None


class ConnectorConfiguration(BaseModel):
    enabled: bool


class ConnectorEvent(BaseModel):
    event: str = Field(min_length=1, max_length=160)
    message: str = Field(default="", max_length=16000)
    action: str | None = Field(default=None, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict, max_length=64)

    @field_validator("params")
    @classmethod
    def params_stay_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        return bounded_mapping(value)


class VisionAnalyzeRequest(BaseModel):
    image_base64: str = Field(min_length=1, max_length=MAX_IMAGE_BASE64_CHARS)
    mode: str = Field(
        default="general", pattern="^(general|room_state|server_rack|object_detection)$"
    )
    prompt: str | None = Field(default=None, max_length=500)


class VisionCaptureRequest(BaseModel):
    source_id: str = Field(default="default", max_length=64)


class AddressingEvaluateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    acoustic_energy: float | None = Field(default=None, ge=0.0, le=1.0)
    snr_db: float | None = Field(default=None, ge=-20.0, le=60.0)


class SatelliteRegisterRequest(BaseModel):
    satellite_id: str = Field(min_length=1, max_length=64, pattern="^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=100)
    room: str = Field(min_length=1, max_length=100)
    ip_address: str = Field(default="", max_length=64)
    capabilities: list[str] | None = Field(default=None, max_length=32)

    @field_validator("capabilities")
    @classmethod
    def capabilities_stay_bounded(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(not item or len(item) > 64 for item in value):
            raise ValueError("capability names must be 1-64 characters")
        return value


class SatelliteHeartbeatRequest(BaseModel):
    telemetry: dict[str, Any] = Field(default_factory=dict, max_length=64)

    @field_validator("telemetry")
    @classmethod
    def telemetry_stays_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        return bounded_mapping(value)


class SatelliteAnnounceRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    satellite_id: str | None = Field(default=None, max_length=64)
    priority: str = Field(default="normal", pattern="^(normal|high|urgent)$")


class AutonomousTicketResolveRequest(BaseModel):
    approve: bool
    operator_id: str = Field(default="operator", max_length=64)


class AutonomousPolicyUpdateRequest(BaseModel):
    action: str = Field(min_length=1, max_length=64)
    auto_allow_tier1: bool
    max_auto_per_hour: int = Field(default=5, ge=1, le=60)


class EmergencyLoginRequest(BaseModel):
    secret: str = Field(min_length=1, max_length=256)


class EmergencyTicketResolveRequest(BaseModel):
    approve: bool


class ExecutionResume(BaseModel):
    approval_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")


class MemoryItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=100000)
