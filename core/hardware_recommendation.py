"""Small, advisory-only LLM recommendation for constrained desktop hardware."""
from __future__ import annotations

import os


LOCAL_PROVIDERS = {"", "ollama", "openai", "openai_compatible", "lmstudio", "localai", "jan", "llamacpp"}


def provider_recommendation(
    *,
    cpu_logical: int | None,
    memory_bytes: int | None,
    configured_provider: str,
) -> dict[str, object] | None:
    """Recommend Gemini without ever changing the configured provider."""
    provider = (configured_provider or "ollama").strip().lower()
    if provider not in LOCAL_PROVIDERS:
        return None
    reasons: list[str] = []
    if isinstance(cpu_logical, int) and cpu_logical < 4:
        reasons.append("weniger als vier logische CPU-Kerne")
    if isinstance(memory_bytes, int) and memory_bytes < 16 * 1024**3:
        reasons.append("weniger als 16 GiB Arbeitsspeicher")
    if not reasons:
        return None
    return {
        "recommended_provider": "gemini",
        "recommended_voice": "gemini_tts",
        "reason": " und ".join(reasons),
        "requires_explicit_opt_in": True,
        "sends_reply_text_to_cloud": True,
        "display_message": (
            "TIPP: Diese Hardware ist für lokale KI knapp ("
            + " und ".join(reasons)
            + "). Gemini ist meist schneller; bei Auswahl wird automatisch die passende "
            "Google-Stimme genutzt. Cloud-Nutzung bleibt freiwillig und kann Kosten verursachen."
        ),
    }


def current_provider_recommendation() -> dict[str, object] | None:
    cpu_logical = os.cpu_count()
    memory_bytes: int | None = None
    try:
        import psutil  # type: ignore[import-not-found]

        cpu_logical = psutil.cpu_count()
        memory_bytes = int(psutil.virtual_memory().total)
    except (ImportError, OSError, ValueError):
        pass
    return provider_recommendation(
        cpu_logical=cpu_logical,
        memory_bytes=memory_bytes,
        configured_provider=os.getenv("MICA_LLM_PROVIDER", "ollama"),
    )
