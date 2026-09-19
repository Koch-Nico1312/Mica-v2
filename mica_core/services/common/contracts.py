"""Versioned public request/result contracts shared by MICA clients."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .persona import ConversationMode, normalize_conversation_mode


class ExecutionRequest(BaseModel):
    schema_version: Literal[1] = 1
    turn_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    task_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    action: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    params: dict[str, Any] = Field(default_factory=dict, max_length=64)
    dry_run: bool = False
    approval_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    idempotency_key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.:-]{8,128}$")


class ExecutionResult(BaseModel):
    schema_version: Literal[1] = 1
    turn_id: str | None = None
    task_id: str
    status: Literal["succeeded", "failed", "not_dispatched", "dry_run"]
    action: str
    output: Any = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    undo: Any = None
    audit_id: str | None = None
    error_class: str | None = None


class VoiceControl(BaseModel):
    schema_version: Literal[1] = 1
    command: Literal["start", "finalize", "cancel"]
    input_mode: Literal["push_to_talk", "wake_word", "pwa"]
    state: Literal[
        "idle", "listening", "transcribing", "planning", "approval_required",
        "speaking", "failed", "cancelled",
    ]
    conversation_mode: ConversationMode = "personal"

    @field_validator("conversation_mode", mode="before")
    @classmethod
    def fallback_to_default_mode(cls, value: object) -> ConversationMode:
        return normalize_conversation_mode(value)
