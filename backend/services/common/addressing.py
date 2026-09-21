"""Voice addressability detection (Proactive Audio) for MICA Phase 4.5.

Distinguishes speech directly addressed to MICA from background conversations,
television, or phone calls without requiring a rigid wake-word.
Essential for continuous listening / room-presence satellites.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Assistant names and vocatives (case-insensitive)
NAME_VOCATIVES = {
    "mica", "mika", "jarvis", "friday", "computer", "system",
}

# Direct imperative or request starters in German and English
DIRECT_STARTERS = (
    # German
    "kannst du", "könntest du", "kannst du bitte", "bitte", "sag mal", "sage mir",
    "sag mir", "zeig mir", "zeige mir", "mach", "mache", "mach mal", "schalte",
    "starte", "öffne", "prüfe", "wie spät", "wie viel uhr", "wie ist das wetter",
    "wetterbericht", "status", "wie steht es um", "gibt es", "hast du", "schreib",
    "erstelle", "beende", "stopp", "pause", "abbrechen", "not-aus", "notaus",
    "guten morgen", "guten abend", "gute nacht",
    # English
    "can you", "could you", "please", "tell me", "show me", "open", "turn on",
    "turn off", "check", "what time", "how is the weather", "stop", "pause",
    "cancel", "emergency stop", "good morning",
)

# Third-party / ambient conversation markers that indicate background chatter
BACKGROUND_CONVERSATION_MARKERS = (
    # Third-person dialogues
    "er hat gesagt", "sie hat gesagt", "sie meinte", "er meinte", "und dann sind wir",
    "wir haben gestern", "ich habe ihm", "ich habe ihr", "haben die gesagt",
    # Phone call markers
    "ich ruf dich später an", "hallo mama", "hallo papa", "hallo schatz", "bis gleich",
    "tschüss", "ja ich bin gerade da", "hörst du mich",
    # Media / TV / Broadcast markers
    "in den nachrichten", "willkommen zu den themen", "im fernsehen", "das wetter morgen",
    "tor für", "spielminute", "unser sponsor",
)


@dataclass(frozen=True)
class AddressDecision:
    is_addressed: bool
    confidence: float
    category: str  # "direct_name", "direct_command", "direct_query", "ambient_chatter", "unaddressed"
    reason: str
    cleaned_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_addressed": self.is_addressed,
            "confidence": self.confidence,
            "category": self.category,
            "reason": self.reason,
            "cleaned_text": self.cleaned_text,
        }


class AddressingDetector:
    """Detects whether spoken input is addressed to MICA or ambient noise/chatter."""

    def __init__(self, confidence_threshold: float = 0.65):
        self.confidence_threshold = confidence_threshold

    def evaluate(
        self,
        text: str,
        acoustic_energy: float | None = None,
        snr_db: float | None = None,
    ) -> AddressDecision:
        normalized = (text or "").strip()
        if not normalized:
            return AddressDecision(
                is_addressed=False,
                confidence=0.0,
                category="unaddressed",
                reason="Leere Spracheingabe",
                cleaned_text="",
            )

        lower = normalized.lower()
        # Remove punctuation for matching
        words = re.findall(r"\b\w+\b", lower)
        if not words:
            return AddressDecision(
                is_addressed=False,
                confidence=0.0,
                category="unaddressed",
                reason="Keine Wörter erkannt",
                cleaned_text="",
            )

        # 1. Direct Vocative / Name Trigger
        first_few_words = set(words[:3])
        matching_vocative = first_few_words.intersection(NAME_VOCATIVES)
        if matching_vocative:
            # Strip vocative for cleaner command execution
            vocative = list(matching_vocative)[0]
            cleaned = re.sub(rf"^\s*{vocative}\b[,:\s]*", "", normalized, flags=re.IGNORECASE).strip()
            return AddressDecision(
                is_addressed=True,
                confidence=0.98,
                category="direct_name",
                reason=f"Direkte Namensadressierung ('{vocative}')",
                cleaned_text=cleaned or normalized,
            )

        # 2. Check for explicit background conversation markers (negative signals)
        for marker in BACKGROUND_CONVERSATION_MARKERS:
            if marker in lower:
                return AddressDecision(
                    is_addressed=False,
                    confidence=0.15,
                    category="ambient_chatter",
                    reason=f"Hintergrundgespräch / Medien erkannt ('{marker}')",
                    cleaned_text=normalized,
                )

        # 3. Direct Request / Imperative Starters
        for starter in DIRECT_STARTERS:
            if lower.startswith(starter) or f", {starter}" in lower:
                return AddressDecision(
                    is_addressed=True,
                    confidence=0.88,
                    category="direct_command",
                    reason=f"Direkte Befehls-/Frageformulierung ('{starter}')",
                    cleaned_text=normalized,
                )

        # 4. Check for second-person questions directed at an agent ("was machst du", "bist du da")
        if any(w in words for w in ("du", "dir", "dein", "deine")):
            if any(w in words for w in ("wer", "wie", "wo", "was", "wann", "warum", "kannst")):
                return AddressDecision(
                    is_addressed=True,
                    confidence=0.78,
                    category="direct_query",
                    reason="Direkte Frage mit persönlicher Anrede (2. Person)",
                    cleaned_text=normalized,
                )

        # 5. Acoustic SNR / Proximity boost or penalty if provided
        confidence = 0.35
        if acoustic_energy is not None and acoustic_energy < 0.05:
            confidence -= 0.20
        if snr_db is not None and snr_db < 3.0:
            confidence -= 0.15

        is_addressed = confidence >= self.confidence_threshold
        return AddressDecision(
            is_addressed=is_addressed,
            confidence=max(0.0, min(1.0, confidence)),
            category="direct_query" if is_addressed else "ambient_chatter",
            reason="Keine Anrede oder Steuerbefehl erkannt (diffuses Gespräch)",
            cleaned_text=normalized,
        )
