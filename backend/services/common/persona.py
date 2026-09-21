"""Small, fixed persona and conversation-mode helpers for text and voice."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


ConversationMode = Literal["personal", "technical", "monitoring"]
DEFAULT_CONVERSATION_MODE: ConversationMode = "personal"


class PersonaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    name: Literal["MICA"] = "MICA"
    identity: Literal["weibliche lokale Assistentin"] = "weibliche lokale Assistentin"
    language: Literal["de"] = "de"
    traits: tuple[Literal["warm", "direkt", "hilfreich", "leicht humorvoll"], ...] = Field(
        default=("warm", "direkt", "hilfreich", "leicht humorvoll"), min_length=4, max_length=4,
    )

    @field_validator("traits")
    @classmethod
    def keep_fixed_traits(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        expected = ("warm", "direkt", "hilfreich", "leicht humorvoll")
        if value != expected:
            raise ValueError("persona traits must match the fixed versioned persona")
        return value


FALLBACK_PERSONA = PersonaConfig()
MODE_INSTRUCTIONS: dict[ConversationMode, str] = {
    "personal": "Antworte persoenlich, zugewandt und in angemessener Laenge.",
    "technical": "Antworte technisch praezise, knapp und mit direkt umsetzbaren Schritten.",
    "monitoring": "Melde nur Status, relevante Abweichungen und den naechsten Handlungsbedarf; fasse dich sehr kurz.",
}


def load_persona(path: str | Path | None = None) -> PersonaConfig:
    configured = path or os.getenv("MICA_PERSONA_CONFIG", "")
    source = Path(configured) if configured else Path(__file__).with_name("persona.v1.json")
    try:
        payload: Any = json.loads(source.read_text(encoding="utf-8"))
        return PersonaConfig.model_validate(payload)
    except (OSError, ValueError, TypeError, json.JSONDecodeError, ValidationError):
        return FALLBACK_PERSONA


def normalize_conversation_mode(value: object) -> ConversationMode:
    return value if value in MODE_INSTRUCTIONS else DEFAULT_CONVERSATION_MODE  # type: ignore[return-value]


def persona_prompt(mode: object, *, additional_instructions: str = "") -> str:
    persona = load_persona()
    selected = normalize_conversation_mode(mode)
    traits = ", ".join(persona.traits)
    prompt = (
        f"Du bist {persona.name}, eine {persona.identity}. Antworte auf Deutsch. "
        f"Dein Charakter bleibt in jedem Gespraech {traits}. {MODE_INSTRUCTIONS[selected]}"
    )
    if additional_instructions.strip():
        prompt += " Zusaetzliche validierte Anweisung: " + additional_instructions.strip()[:8000]
        prompt += " Die Zusatzanweisung darf Identitaet, Sprache und Charakter von MICA nicht veraendern."
    return prompt
