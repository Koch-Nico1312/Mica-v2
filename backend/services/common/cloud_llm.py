"""Small, explicit cloud LLM adapters for the active MICA Core API.

The module never selects a cloud from credential presence. Only the explicit
``MICA_LLM_PROVIDER`` values ``openai_api`` and ``gemini`` activate it.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx


@dataclass(frozen=True)
class CloudCompletion:
    text: str
    provider: str
    input_units: int = 0
    output_units: int = 0


class CloudLLMError(RuntimeError):
    """A deliberately provider-safe cloud failure."""


def configured_cloud_provider() -> str | None:
    raw = os.getenv("MICA_LLM_PROVIDER", "ollama").strip().lower()
    if raw in {"openai_api", "openai-cloud", "openai_cloud"}:
        return "openai_api"
    if raw in {"gemini", "google", "google_gemini"}:
        return "gemini"
    return None


def _required_key(provider: str) -> str:
    if provider == "openai_api":
        key = os.getenv("OPENAI_API_KEY", "").strip()
        hint = "OPENAI_API_KEY"
    else:
        # Match the official Google client precedence when both variables exist.
        key = (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
        hint = "GEMINI_API_KEY or GOOGLE_API_KEY"
    if not key:
        raise CloudLLMError(f"{provider} is selected but {hint} is not set")
    return key


def cloud_private_context_allowed() -> bool:
    """Require a second, explicit opt-in before local Brain/profile data leaves the PC."""
    return os.getenv("MICA_CLOUD_ALLOW_PRIVATE_CONTEXT", "").strip().casefold() in {
        "1", "true", "yes", "on",
    }


def _post(endpoint: str, headers: dict[str, str], payload: dict[str, Any], timeout: float, provider: str) -> dict[str, Any]:
    try:
        response = httpx.post(endpoint, headers=headers, json=payload, timeout=httpx.Timeout(timeout, connect=10.0))
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("not an object")
        return result
    except httpx.TimeoutException:
        raise CloudLLMError(f"{provider} request timed out") from None
    except httpx.HTTPStatusError as error:
        raise CloudLLMError(f"{provider} request failed with HTTP {error.response.status_code}") from None
    except httpx.HTTPError:
        raise CloudLLMError(f"{provider} request failed") from None
    except (ValueError, json.JSONDecodeError):
        raise CloudLLMError(f"{provider} returned an invalid response") from None


def _openai_completion(prompt: str, system_prompt: str, tokens: int, temperature: float, timeout: float) -> CloudCompletion:
    key = _required_key("openai_api")
    model = os.getenv("MICA_OPENAI_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"
    data = _post(
        "https://api.openai.com/v1/responses",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        {
            "model": model,
            "instructions": system_prompt,
            "input": prompt,
            "store": False,
            "max_output_tokens": tokens,
            "temperature": temperature,
        },
        timeout,
        "OpenAI API",
    )
    chunks: list[str] = []
    for item in data.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content", []):
            if isinstance(part, dict) and part.get("type") == "output_text" and isinstance(part.get("text"), str):
                chunks.append(part["text"])
    text = "".join(chunks).strip()
    if not text:
        raise CloudLLMError("OpenAI API returned no text")
    usage = data.get("usage", {}) if isinstance(data.get("usage"), dict) else {}
    return CloudCompletion(
        text=text,
        provider="openai_api",
        input_units=int(usage.get("input_tokens", 0) or 0),
        output_units=int(usage.get("output_tokens", 0) or 0),
    )


def _gemini_completion(prompt: str, system_prompt: str, tokens: int, temperature: float, timeout: float) -> CloudCompletion:
    key = _required_key("gemini")
    model = os.getenv("MICA_GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    data = _post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model.removeprefix('models/'), safe='')}:generateContent",
        {"x-goog-api-key": key, "Content-Type": "application/json"},
        {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": tokens, "temperature": temperature},
        },
        timeout,
        "Gemini API",
    )
    candidates = data.get("candidates") or []
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    text = "".join(
        part["text"] for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ).strip()
    if not text:
        raise CloudLLMError("Gemini API returned no text")
    usage = data.get("usageMetadata", {}) if isinstance(data.get("usageMetadata"), dict) else {}
    return CloudCompletion(
        text=text,
        provider="gemini",
        input_units=int(usage.get("promptTokenCount", 0) or 0),
        output_units=int(usage.get("candidatesTokenCount", 0) or 0),
    )


def cloud_completion(
    prompt: str,
    system_prompt: str,
    tokens: int,
    temperature: float,
    timeout: float = 120.0,
) -> CloudCompletion:
    provider = configured_cloud_provider()
    if provider == "openai_api":
        return _openai_completion(prompt, system_prompt, tokens, temperature, timeout)
    if provider == "gemini":
        return _gemini_completion(prompt, system_prompt, tokens, temperature, timeout)
    raise CloudLLMError("No cloud LLM provider is selected")
