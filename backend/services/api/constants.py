from __future__ import annotations

from backend.services.common.persona import persona_prompt


LOCAL_LLM_HOSTS = {"llama-server", "llama-fallback", "localhost", "127.0.0.1"}

DEFAULT_SYSTEM_PROMPT = persona_prompt("personal")
