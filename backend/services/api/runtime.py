from __future__ import annotations
import asyncio
import os
from pathlib import Path
import threading
import httpx
from fastapi import (
    WebSocket,
)
from backend.services.common.audit import AuditLog
from backend.services.common.approval_auth import LocalApprovalSessions
from backend.services.common.brain import MarkdownBrain
from backend.services.common.hindsight import HindsightMemory, selected_summary
from mica_shared.capabilities import CAPABILITIES, capability_for, list_capabilities
from backend.services.common.cloud_llm import (
    CloudLLMError,
    cloud_completion,
    cloud_private_context_allowed,
    configured_cloud_provider,
)
from backend.services.common.connectors import ConnectorRegistry
from backend.services.common.contracts import ExecutionRequest, ExecutionResult, VoiceControl
from backend.services.common.improvements import ImprovementRegistry
from backend.services.common.dream_rsi import attach_dream_rsi
from backend.services.common.laya_scorer import build_scorer, rerank_retrieval
from backend.services.common.learning import (
    DomainRegistry,
    LearningService,
    parse_research_command,
)
from backend.services.common.migration import migrate_legacy_memory
from backend.services.common.orchestrator import Orchestrator
from backend.services.common.operations import OperationLedger
from backend.services.common.execution_history import ExecutionHistory
from backend.services.common.diagnostics import service_diagnostics
from backend.services.common.storage_lock import StorageLease, StorageBusy
from backend.services.common.idempotency import IdempotencyConflict, IdempotencyStore
from backend.services.common.policy import PolicyEngine
from backend.services.common.phase4 import (
    Phase4Store,
    enabled as phase4_feature_enabled,
    phase4_enabled,
    steps_for_goal,
)
from backend.services.common.persona import normalize_conversation_mode, persona_prompt
from backend.services.common.profile import (
    LocalProfileStore,
    PersonalProfileUpdate,
    profile_prompt,
)
from backend.services.common.scheduler_store import ScheduleStore
from backend.services.common.task_automation import (
    TaskAutomationStore,
    automations_enabled,
    dry_run_rule,
    phase3_enabled,
)
from backend.services.common.turn_budget import TurnBudget, TurnBudgetExceeded
from backend.services.common.vision import VisionEngine, VisionResult
from backend.services.common.ambient import AmbientMonitor
from mica_shared.addressing import AddressingDetector
from backend.services.common.satellite import SatelliteRegistry
from backend.services.common.autonomous_guard import AutonomousActionGuard
from backend.services.common.emergency import EmergencyService
from backend.services.api.schemas import (
    AddressingEvaluateRequest,
    AgentPlanActivation,
    AgentPlanCreate,
    AgentPlanStep,
    AgentPlanUpdate,
    ApprovalLogin,
    ApprovalRequest,
    AutomationRuleCreate,
    AutomationRuleUpdate,
    AutonomousPolicyUpdateRequest,
    AutonomousTicketResolveRequest,
    BrainDocumentUpdate,
    ChatRequest,
    ConnectorConfiguration,
    ConnectorEvent,
    DreamCycleRequest,
    EmergencyLoginRequest,
    EmergencyStopRequest,
    EmergencyTicketResolveRequest,
    ExecutionResume,
    ImprovementEvaluation,
    ImprovementPromotion,
    ImprovementProposal,
    LearningDomainUpdate,
    LearningMonitorRequest,
    LearningReview,
    MemoryItemCreate,
    OutcomeRequest,
    RecurrenceRequest,
    ResearchRequest,
    SatelliteAnnounceRequest,
    SatelliteHeartbeatRequest,
    SatelliteRegisterRequest,
    ScheduleRequest,
    ServerDiagnosticConfirm,
    ServerScanRequest,
    TaskExecution,
    TaskItemCreate,
    TaskItemUpdate,
    TaskRequest,
    TurnRequest,
    TwinFactUpdate,
    TwinSettingsUpdate,
    VisionAnalyzeRequest,
    VisionCaptureRequest,
)
from backend.services.api.constants import DEFAULT_SYSTEM_PROMPT, LOCAL_LLM_HOSTS
from backend.services.api.gates import RuntimeGates
from backend.services.api.routers.maintenance import MaintenanceRoutes
from backend.services.api.routers.health import HealthRoutes
from backend.services.api.routers.approvals import ApprovalsRoutes
from backend.services.api.routers.tasks import TasksRoutes
from backend.services.api.routers.planning import PlanningRoutes
from backend.services.api.routers.conversation import ConversationRoutes
from backend.services.api.routers.memory import MemoryRoutes
from backend.services.api.routers.learning import LearningRoutes
from backend.services.api.routers.connectors import ConnectorsRoutes
from backend.services.api.routers.schedules import SchedulesRoutes
from backend.services.api.routers.improvements import ImprovementsRoutes
from backend.services.api.routers.voice import VoiceRoutes
from backend.services.api.routers.perception import PerceptionRoutes
from backend.services.api.routers.emergency import EmergencyRoutes


class ApiRuntime(
    RuntimeGates,
    MaintenanceRoutes,
    HealthRoutes,
    ApprovalsRoutes,
    TasksRoutes,
    PlanningRoutes,
    ConversationRoutes,
    MemoryRoutes,
    LearningRoutes,
    ConnectorsRoutes,
    SchedulesRoutes,
    ImprovementsRoutes,
    VoiceRoutes,
    PerceptionRoutes,
    EmergencyRoutes,
):
    """One app's services, locks and sessions; no global runtime instances."""

    def __init__(self, data_dir=None, dependencies=None):
        environment = dict(os.environ)
        if data_dir is not None:
            root = Path(data_dir).resolve()
            paths = {
                "BRAIN_DIR": "brain",
                "INDEX_PATH": "index/brain.sqlite3",
                "AUDIT_PATH": "audit/events.jsonl",
                "APPROVAL_DB": "approvals.sqlite3",
                "SCHEDULE_DB": "scheduler.sqlite3",
                "MICA_STATE_DB": "scheduler.sqlite3",
                "IMPROVEMENT_DB": "improvements.sqlite3",
                "IMPROVEMENT_WORKSPACE": "improvement-workspace",
                "CONNECTOR_DB": "connectors.sqlite3",
                "OPERATIONS_DB": "operations.sqlite3",
                "TURN_BUDGET_DB": "turn-budget.sqlite3",
                "MICA_PROFILE_PATH": "profile.json",
                "LEARNING_DOMAINS_PATH": "learning/domains.json",
                "MICA_DREAM_DB": "dream.sqlite3",
            }
            environment.update({key: str(root / value) for key, value in paths.items()})
        self.environment = environment
        self.AddressingDetector = AddressingDetector
        self.AddressingEvaluateRequest = AddressingEvaluateRequest
        self.AgentPlanActivation = AgentPlanActivation
        self.AgentPlanCreate = AgentPlanCreate
        self.AgentPlanStep = AgentPlanStep
        self.AgentPlanUpdate = AgentPlanUpdate
        self.AmbientMonitor = AmbientMonitor
        self.ApprovalLogin = ApprovalLogin
        self.ApprovalRequest = ApprovalRequest
        self.AuditLog = AuditLog
        self.AutomationRuleCreate = AutomationRuleCreate
        self.AutomationRuleUpdate = AutomationRuleUpdate
        self.AutonomousActionGuard = AutonomousActionGuard
        self.AutonomousPolicyUpdateRequest = AutonomousPolicyUpdateRequest
        self.AutonomousTicketResolveRequest = AutonomousTicketResolveRequest
        self.BrainDocumentUpdate = BrainDocumentUpdate
        self.CAPABILITIES = CAPABILITIES
        self.ChatRequest = ChatRequest
        self.CloudLLMError = CloudLLMError
        self.ConnectorConfiguration = ConnectorConfiguration
        self.ConnectorEvent = ConnectorEvent
        self.ConnectorRegistry = ConnectorRegistry
        self.DEFAULT_SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT
        self.DomainRegistry = DomainRegistry
        self.DreamCycleRequest = DreamCycleRequest
        self.EmergencyLoginRequest = EmergencyLoginRequest
        self.EmergencyService = EmergencyService
        self.EmergencyStopRequest = EmergencyStopRequest
        self.EmergencyTicketResolveRequest = EmergencyTicketResolveRequest
        self.ExecutionHistory = ExecutionHistory
        self.ExecutionRequest = ExecutionRequest
        self.ExecutionResult = ExecutionResult
        self.ExecutionResume = ExecutionResume
        self.HindsightMemory = HindsightMemory
        self.IdempotencyConflict = IdempotencyConflict
        self.IdempotencyStore = IdempotencyStore
        self.ImprovementEvaluation = ImprovementEvaluation
        self.ImprovementPromotion = ImprovementPromotion
        self.ImprovementProposal = ImprovementProposal
        self.ImprovementRegistry = ImprovementRegistry
        self.LOCAL_LLM_HOSTS = LOCAL_LLM_HOSTS
        self.LearningDomainUpdate = LearningDomainUpdate
        self.LearningMonitorRequest = LearningMonitorRequest
        self.LearningReview = LearningReview
        self.LearningService = LearningService
        self.LocalApprovalSessions = LocalApprovalSessions
        self.LocalProfileStore = LocalProfileStore
        self.MarkdownBrain = MarkdownBrain
        self.MemoryItemCreate = MemoryItemCreate
        self.OperationLedger = OperationLedger
        self.Orchestrator = Orchestrator
        self.OutcomeRequest = OutcomeRequest
        self.PersonalProfileUpdate = PersonalProfileUpdate
        self.Phase4Store = Phase4Store
        self.PolicyEngine = PolicyEngine
        self.RecurrenceRequest = RecurrenceRequest
        self.ResearchRequest = ResearchRequest
        self.SatelliteAnnounceRequest = SatelliteAnnounceRequest
        self.SatelliteHeartbeatRequest = SatelliteHeartbeatRequest
        self.SatelliteRegisterRequest = SatelliteRegisterRequest
        self.SatelliteRegistry = SatelliteRegistry
        self.ScheduleRequest = ScheduleRequest
        self.ScheduleStore = ScheduleStore
        self.ServerDiagnosticConfirm = ServerDiagnosticConfirm
        self.ServerScanRequest = ServerScanRequest
        self.StorageBusy = StorageBusy
        self.StorageLease = StorageLease
        self.TaskAutomationStore = TaskAutomationStore
        self.TaskExecution = TaskExecution
        self.TaskItemCreate = TaskItemCreate
        self.TaskItemUpdate = TaskItemUpdate
        self.TaskRequest = TaskRequest
        self.TurnBudget = TurnBudget
        self.TurnBudgetExceeded = TurnBudgetExceeded
        self.TurnRequest = TurnRequest
        self.TwinFactUpdate = TwinFactUpdate
        self.TwinSettingsUpdate = TwinSettingsUpdate
        self.VisionAnalyzeRequest = VisionAnalyzeRequest
        self.VisionCaptureRequest = VisionCaptureRequest
        self.VisionEngine = VisionEngine
        self.VisionResult = VisionResult
        self.VoiceControl = VoiceControl
        self.attach_dream_rsi = attach_dream_rsi
        self.automations_enabled = automations_enabled
        self.build_scorer = build_scorer
        self.capability_for = capability_for
        self.cloud_completion = cloud_completion
        self.cloud_private_context_allowed = cloud_private_context_allowed
        self.configured_cloud_provider = configured_cloud_provider
        self.dry_run_rule = dry_run_rule
        self.httpx = httpx
        self.list_capabilities = list_capabilities
        self.migrate_legacy_memory = migrate_legacy_memory
        self.normalize_conversation_mode = normalize_conversation_mode
        self.parse_research_command = parse_research_command
        self.persona_prompt = persona_prompt
        self.phase3_enabled = phase3_enabled
        self.phase4_enabled = phase4_enabled
        self.phase4_feature_enabled = phase4_feature_enabled
        self.profile_prompt = profile_prompt
        self.rerank_retrieval = rerank_retrieval
        self.selected_summary = selected_summary
        self.service_diagnostics = service_diagnostics
        self.steps_for_goal = steps_for_goal
        for name, value in (dependencies or {}).items():
            setattr(self, name, value)
        self.brain = self.MarkdownBrain(
            environment.get("BRAIN_DIR", "/data/brain"),
            environment.get("INDEX_PATH", "/data/index/brain.sqlite3"),
        )
        self.audit = self.AuditLog(
            environment.get("AUDIT_PATH", "/data/audit/events.jsonl")
        )
        self.policy = self.PolicyEngine(
            environment.get("APPROVAL_DB", "/data/approvals.sqlite3")
        )
        self.orchestrator = self.Orchestrator(self.brain, self.audit, self.policy)
        self.schedule_store = self.ScheduleStore(
            environment.get("SCHEDULE_DB", "/data/scheduler.sqlite3")
        )
        self.task_store = self.TaskAutomationStore(
            environment.get("SCHEDULE_DB", "/data/scheduler.sqlite3")
        )
        self.execution_history = self.ExecutionHistory(
            environment.get("SCHEDULE_DB", "/data/scheduler.sqlite3")
        )
        self.phase4_store = self.Phase4Store(
            environment.get(
                "MICA_STATE_DB",
                environment.get("SCHEDULE_DB", "/data/scheduler.sqlite3"),
            )
        )
        self.improvements = self.ImprovementRegistry(
            environment.get("IMPROVEMENT_DB", "/data/improvements.sqlite3"), self.brain
        )
        self.dream_engine = self.attach_dream_rsi(
            self.improvements,
            self.brain,
            db_path=environment.get("MICA_DREAM_DB"),
            summarizer=self._dream_summarizer,
            scorer=self.build_scorer(),
            emergency_stopped=self.policy.is_emergency_stopped,
        )
        self.connectors = self.ConnectorRegistry(
            environment.get("CONNECTOR_DB", "/data/connectors.sqlite3")
        )
        self.approval_sessions = self.LocalApprovalSessions(
            environment.get("MICA_APPROVAL_SECRET", "")
        )
        self.operations = self.OperationLedger(
            environment.get(
                "OPERATIONS_DB",
                str(
                    Path(
                        environment.get("AUDIT_PATH", "/data/audit/events.jsonl")
                    ).parent
                    / "operations.sqlite3"
                ),
            )
        )
        self.turn_budget = self.TurnBudget(
            environment.get(
                "TURN_BUDGET_DB",
                str(
                    Path(
                        environment.get("AUDIT_PATH", "/data/audit/events.jsonl")
                    ).parent
                    / "turn-budget.sqlite3"
                ),
            )
        )
        self.profile_store = self.LocalProfileStore(
            environment.get("MICA_PROFILE_PATH", "/data/profile.json")
        )
        self.learning_domains = self.DomainRegistry(
            environment.get("LEARNING_DOMAINS_PATH", "/data/learning/domains.json")
        )
        self.vision_engine = self.VisionEngine()
        self.ambient_monitor = self.AmbientMonitor(
            environment.get(
                "MICA_STATE_DB",
                environment.get("SCHEDULE_DB", "/data/scheduler.sqlite3"),
            )
        )
        self.addressing_detector = self.AddressingDetector()
        self.satellite_registry = self.SatelliteRegistry(
            environment.get(
                "MICA_STATE_DB",
                environment.get("SCHEDULE_DB", "/data/scheduler.sqlite3"),
            )
        )
        self.autonomous_guard = self.AutonomousActionGuard(
            environment.get(
                "MICA_STATE_DB",
                environment.get("SCHEDULE_DB", "/data/scheduler.sqlite3"),
            )
        )
        self.emergency_service = self.EmergencyService(
            environment.get(
                "MICA_EMERGENCY_SECRET", environment.get("MICA_APPROVAL_SECRET", "")
            )
        )
        self.MAX_VOICE_BYTES = max(
            1, int(environment.get("MICA_VOICE_MAX_BYTES", str(10 * 1024 * 1024)))
        )
        self.MAX_VOICE_CONTROL_BYTES = max(
            256, int(environment.get("MICA_VOICE_CONTROL_MAX_BYTES", "8192"))
        )
        self.MAX_CONNECTOR_WEBHOOK_BYTES = max(
            1024,
            min(
                int(
                    environment.get("MICA_CONNECTOR_WEBHOOK_MAX_BYTES", str(256 * 1024))
                ),
                1024 * 1024,
            ),
        )
        self.ALLOWED_VOICE_ORIGINS = {
            origin.strip().rstrip("/")
            for origin in environment.get(
                "MICA_ALLOWED_VOICE_ORIGINS",
                "http://127.0.0.1:8088,http://localhost:8088",
            ).split(",")
            if origin.strip()
        }
        self._VOICE_LOCK = threading.RLock()
        self._VOICE_SESSIONS: dict[
            int, tuple[asyncio.AbstractEventLoop, WebSocket]
        ] = {}
