"""Versioned public request/result contracts shared by MICA clients."""
from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .persona import ConversationMode, normalize_conversation_mode

# Structured payloads stay well below the transport body limit so a single
# mapping cannot pin arbitrary memory before dispatch or policy checks.
MAX_STRUCTURED_BYTES = 256 * 1024


def bounded_mapping(value: dict[str, Any]) -> dict[str, Any]:
    """Reject mappings whose canonical JSON form exceeds the documented bound."""
    if not isinstance(value, dict):
        raise ValueError("structured payload must be a mapping")
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("structured payload must be JSON-serializable") from error
    if len(encoded) > MAX_STRUCTURED_BYTES:
        raise ValueError(f"structured payload exceeds {MAX_STRUCTURED_BYTES} bytes")
    return value


class ExecutionRequest(BaseModel):
    schema_version: Literal[1] = 1
    turn_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    task_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    action: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    params: dict[str, Any] = Field(default_factory=dict, max_length=64)
    dry_run: bool = False
    approval_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    idempotency_key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.:-]{8,128}$")

    @field_validator("params")
    @classmethod
    def params_stay_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        return bounded_mapping(value)


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
    remember: bool = True
    session_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    native_commands: bool = False
    response_style: Literal["brief", "normal", "detailed"] = "normal"
    name_aliases: list[dict[str, str]] = Field(default_factory=list, max_length=32)

    @field_validator("name_aliases")
    @classmethod
    def validate_names(cls, value):
        from mica_shared.voice_names import validate_aliases
        return validate_aliases(value)

    @field_validator("conversation_mode", mode="before")
    @classmethod
    def fallback_to_default_mode(cls, value: object) -> ConversationMode:
        return normalize_conversation_mode(value)
