"""
Local-first LLM client for MICA.

Backends are selected explicitly with ``MICA_LLM_PROVIDER`` (or the legacy
``llm_provider`` config value):

  "llm_provider": "ollama"   (default)
        Uses Ollama's native /api/chat endpoint.
        Download: https://ollama.com
        Default port: 11434

  "llm_provider": "openai"
        Uses any OpenAI-compatible server: LM Studio, Jan, LocalAI,
        llama.cpp server, vLLM, etc.
        LM Studio download: https://lmstudio.ai   (default port: 1234)
        Set  "llm_url": "http://localhost:1234"  in config.
        Note: tool-calling support depends on the model; use a model that
        supports function/tool calls (e.g. Qwen2.5, Llama-3.1, Mistral).

  MICA_LLM_PROVIDER=openai_api
        Uses OpenAI's Responses API. Requires ``OPENAI_API_KEY`` and always
        sends ``store: false``. The key is read from the process environment.

  MICA_LLM_PROVIDER=gemini
        Uses Gemini's generateContent REST API. Requires ``GEMINI_API_KEY`` or
        ``GOOGLE_API_KEY``. The key is read from the process environment.

Cloud providers are opt-in. Missing/unknown configuration safely selects the
local Ollama backend; the presence of an API key never changes the provider.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Generator

import requests

# Matches a sentence boundary: [.!?] followed by whitespace, or a blank line.
# Avoids splitting on decimals (3.5) because those have no space after the dot.
_SENT_END = re.compile(r'(?<=[.!?])\s+|(?<=\n)\s*\n')

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR    = get_base_dir()
CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

_DEFAULTS = {
    "llm_url":      "http://localhost:11434",
    "llm_model":    "llama3.2",
    "llm_provider": "ollama",
    "openai_url":   "https://api.openai.com",
    "openai_model": "gpt-4.1-mini",
    "gemini_url":   "https://generativelanguage.googleapis.com",
    "gemini_model": "gemini-2.5-flash",
}


def get_llm_provider() -> str:
    """Return a supported provider, defaulting safely to local Ollama."""
    raw = os.environ.get("MICA_LLM_PROVIDER") or _load_config().get("llm_provider", "ollama")
    raw = raw.strip().lower()
    if raw in ("openai", "openai_compatible", "lmstudio", "localai", "jan", "llamacpp"):
        return "openai"
    if raw in ("openai_api", "openai-cloud", "openai_cloud"):
        return "openai_api"
    if raw in ("gemini", "google", "google_gemini"):
        return "gemini"
    return "ollama"


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def ensure_ollama_running(timeout: int = 15) -> bool:
    """
    For Ollama: ping /api/tags; auto-launch 'ollama serve' if not running.
    For OpenAI-compatible providers: just ping /v1/models (server must be started manually).
    Returns True if the LLM server is reachable.
    """
    url, _   = get_llm_settings()
    provider = get_llm_provider()

    if provider in ("openai_api", "gemini"):
        # Cloud backends do not have a local process to start. Validate only;
        # never turn a startup health check into a billable network request.
        try:
            _get_cloud_api_key(provider)
            return True
        except RuntimeError:
            return False

    if provider == "openai":
        # OpenAI-compatible servers (LM Studio, LocalAI, etc.) must be started
        # by the user — we just check if they're reachable.
        health = f"{url}/v1/models"
        try:
            ok = requests.get(health, timeout=5).status_code == 200
            if ok:
                print(f"[LLM] OpenAI-compatible server reachable at {url}")
            else:
                print(f"[LLM] Server at {url} returned non-200.  Is it running?")
            return ok
        except Exception as e:
            print(
                f"[LLM] Cannot reach OpenAI-compatible server at {url}.\n"
                "      Make sure LM Studio / LocalAI / Jan is running and the server is started."
            )
            return False

    # ── Ollama ──────────────────────────────────────────────────────────────
    health = f"{url}/api/tags"

    def _is_up() -> bool:
        try:
            return requests.get(health, timeout=3).status_code == 200
        except Exception:
            return False

    if _is_up():
        return True

    print("[LLM] Ollama not running — launching 'ollama serve'…")
    try:
        kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        ollama_cmd = shutil.which("ollama")
        if not ollama_cmd and sys.platform == "win32":
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            candidates = [
                Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe",
                Path(local_app_data) / "Ollama" / "ollama.exe",
            ]
            ollama_cmd = next((str(path) for path in candidates if path.is_file()), None)
        if not ollama_cmd:
            raise FileNotFoundError("ollama executable not found")
        subprocess.Popen([ollama_cmd, "serve"], **kwargs)
    except FileNotFoundError:
        print("[LLM] 'ollama' command not found. Install Ollama from https://ollama.com")
        return False
    except Exception as e:
        print(f"[LLM] Could not launch Ollama: {e}")
        return False

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1.0)
        if _is_up():
            print("[LLM] Ollama started successfully.")
            return True

    print("[LLM] Ollama did not respond within the timeout.")
    return False


def warmup_model(system_prompt: str | None = None) -> bool:
    """
    Pre-load the model AND prime Ollama's KV prefix cache.

    Why the system_prompt matters
    ─────────────────────────────
    Ollama caches the KV attention state of the prompt prefix across requests.
    If warmup includes the same system prompt that real requests will use, Ollama
    evaluates those tokens ONCE at startup.  Every subsequent request only needs
    to evaluate the small delta (user message ± time context) instead of the full
    300-500 token system prompt → drops first-token latency from ~17 s to <1 s.

    Pass the *static* part of the system prompt (the JARVIS protocol text, without
    timestamps or per-minute context) so the prefix stays valid across calls.
    """
    url, model = get_llm_settings()
    provider   = get_llm_provider()
    print(f"[LLM] Warming up '{model}' ({provider})…")

    if provider in ("openai_api", "gemini"):
        # A cloud "warmup" has no local model to load and would cost money.
        return True

    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": "hi"})

    if provider == "openai":
        # OpenAI-compatible: just fire a minimal request to ensure the model is loaded.
        # No keep_alive or KV-cache priming available — server manages this internally.
        payload = {
            "model":      model,
            "messages":   messages,
            "stream":     False,
            "max_tokens": 1,
        }
        try:
            resp = requests.post(f"{url}/v1/chat/completions", json=payload, timeout=180)
            resp.raise_for_status()
            print(f"[LLM] '{model}' ready (OpenAI-compatible server).")
            return True
        except Exception as e:
            print(f"[LLM] Warmup failed (non-fatal): {e}")
            return False

    # ── Ollama ──────────────────────────────────────────────────────────────
    payload = {
        "model":      model,
        "messages":   messages,
        "stream":     False,
        "keep_alive": -1,
        # num_gpu:99 → push ALL transformer layers to GPU (Ollama caps at available)
        # This is safe even without a GPU — Ollama silently ignores if n_gpu_layers=0
        "options":    {"num_predict": 1, "num_gpu": 99},
    }
    try:
        resp = requests.post(f"{url}/api/chat", json=payload, timeout=180)
        resp.raise_for_status()
        print(f"[LLM] '{model}' loaded and KV cache primed.")
        return True
    except Exception as e:
        print(f"[LLM] Warmup failed (non-fatal): {e}")
        return False


def check_model_available(log: Callable | None = None) -> bool:
    """
    Returns True if the configured model is already pulled in Ollama.
    Logs an actionable warning (to console + optional UI callback) if not.
    Always returns True for non-Ollama providers (cannot inspect their model list).
    """
    if get_llm_provider() != "ollama":
        return True

    url, model = get_llm_settings()
    try:
        resp = requests.get(f"{url}/api/tags", timeout=5)
        resp.raise_for_status()
        pulled = [m.get("name", "") for m in resp.json().get("models", [])]
        model_base = model.split(":")[0]
        found = any(
            m == model or m == model_base or m.startswith(model_base + ":")
            for m in pulled
        )
        if not found:
            available = ", ".join(pulled) if pulled else "none"
            warn = (
                f"WRN: Model '{model}' is not pulled in Ollama.\n"
                f"     Available: {available}\n"
                f"     Fix: ollama pull {model}"
            )
            print(warn)
            if log:
                log(f"WRN: '{model}' not found — run: ollama pull {model}")
        return found
    except Exception:
        return True   # Ollama might still be starting up; non-blocking


def get_llm_settings() -> tuple[str, str]:
    """Returns (base_url, model_name)."""
    cfg = _load_config()
    provider = get_llm_provider()
    if provider == "openai_api":
        # Keep credentials pinned to the official origin. In particular, do
        # not accept a configurable URL that could receive an API key.
        url = _DEFAULTS["openai_url"]
        model = (
            os.environ.get("MICA_OPENAI_MODEL")
            or os.environ.get("MICA_LLM_MODEL")
            or cfg.get("openai_model")
            or _DEFAULTS["openai_model"]
        )
    elif provider == "gemini":
        url = _DEFAULTS["gemini_url"]
        model = (
            os.environ.get("MICA_GEMINI_MODEL")
            or os.environ.get("MICA_LLM_MODEL")
            or cfg.get("gemini_model")
            or _DEFAULTS["gemini_model"]
        )
    else:
        url = (os.environ.get("MICA_LLM_URL") or cfg.get("llm_url") or _DEFAULTS["llm_url"]).rstrip("/")
        model = os.environ.get("MICA_LLM_MODEL") or cfg.get("llm_model") or _DEFAULTS["llm_model"]
    return url, model


def _get_cloud_api_key(provider: str) -> str:
    """Read a cloud credential from the environment without logging it."""
    if provider == "openai_api":
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        env_hint = "OPENAI_API_KEY"
    elif provider == "gemini":
        key = (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or "").strip()
        env_hint = "GEMINI_API_KEY or GOOGLE_API_KEY"
    else:
        raise RuntimeError("Cloud credential requested for a local provider.")
    if not key:
        raise RuntimeError(f"{provider} is selected but {env_hint} is not set.")
    return key


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                chunks.append(item["text"])
        return "\n".join(chunks)
    return str(content or "")


def _openai_tools(tools: list | None) -> list[dict]:
    converted: list[dict] = []
    for tool in tools or []:
        function = tool.get("function", {}) if isinstance(tool, dict) else {}
        name = function.get("name")
        if not name:
            continue
        converted.append({
            "type": "function",
            "name": name,
            "description": function.get("description", ""),
            "parameters": function.get("parameters", {"type": "object", "properties": {}}),
        })
    return converted


def _gemini_tools(tools: list | None) -> list[dict]:
    declarations: list[dict] = []
    for tool in tools or []:
        function = tool.get("function", {}) if isinstance(tool, dict) else {}
        if function.get("name"):
            declarations.append({
                "name": function["name"],
                "description": function.get("description", ""),
                "parameters": function.get("parameters", {"type": "object", "properties": {}}),
            })
    return [{"functionDeclarations": declarations}] if declarations else []


def _post_cloud_json(
    provider: str,
    endpoint: str,
    headers: dict[str, str],
    payload: dict,
    timeout: int,
) -> dict:
    """POST JSON while keeping credentials and remote response bodies out of errors."""
    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("response is not an object")
        return data
    except requests.exceptions.Timeout:
        raise RuntimeError(f"{provider} request timed out.") from None
    except requests.exceptions.ConnectionError:
        raise RuntimeError(f"Could not connect to {provider}.") from None
    except requests.exceptions.HTTPError as exc:
        status = getattr(exc.response, "status_code", "unknown")
        raise RuntimeError(f"{provider} request failed with HTTP {status}.") from None
    except (ValueError, json.JSONDecodeError):
        raise RuntimeError(f"{provider} returned an invalid response.") from None
    except requests.exceptions.RequestException:
        raise RuntimeError(f"{provider} request failed.") from None


def _call_openai_api(messages: list, tools: list | None, timeout: int, model: str | None = None) -> dict:
    url, configured_model = get_llm_settings()
    key = _get_cloud_api_key("openai_api")
    payload: dict = {
        "model": model or configured_model,
        "input": messages,
        "store": False,
        "max_output_tokens": 600 if model else 150,
    }
    converted_tools = _openai_tools(tools)
    if converted_tools:
        payload["tools"] = converted_tools
        payload["tool_choice"] = "auto"
    data = _post_cloud_json(
        "OpenAI API",
        f"{url}/v1/responses",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        payload,
        timeout,
    )
    content_parts: list[str] = []
    tool_calls: list[dict] = []
    for item in data.get("output", []):
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for part in item.get("content", []):
                if isinstance(part, dict) and part.get("type") == "output_text":
                    content_parts.append(part.get("text") or "")
        elif item.get("type") == "function_call":
            arguments = item.get("arguments") or "{}"
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    pass
            tool_calls.append({
                "id": item.get("call_id") or item.get("id", ""),
                "function": {"name": item.get("name", ""), "arguments": arguments},
            })
    content = "".join(content_parts).strip()
    if not content and not tool_calls:
        raise RuntimeError("OpenAI API returned no text or tool call.")
    return {"content": content, "tool_calls": tool_calls}


def _call_gemini(messages: list, tools: list | None, timeout: int, model: str | None = None) -> dict:
    from urllib.parse import quote

    url, configured_model = get_llm_settings()
    selected_model = (model or configured_model).removeprefix("models/")
    key = _get_cloud_api_key("gemini")
    system_chunks: list[str] = []
    contents: list[dict] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        text = _message_text(message.get("content"))
        if message.get("role") in ("system", "developer"):
            system_chunks.append(text)
            continue
        role = "model" if message.get("role") == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": text}]})
    payload: dict = {
        "contents": contents,
        "generationConfig": {"maxOutputTokens": 600 if model else 150},
    }
    if system_chunks:
        payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_chunks)}]}
    converted_tools = _gemini_tools(tools)
    if converted_tools:
        payload["tools"] = converted_tools
    data = _post_cloud_json(
        "Gemini API",
        f"{url}/v1beta/models/{quote(selected_model, safe='')}:generateContent",
        {"x-goog-api-key": key, "Content-Type": "application/json"},
        payload,
        timeout,
    )
    candidates = data.get("candidates") or []
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    content_parts: list[str] = []
    tool_calls: list[dict] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if isinstance(part.get("text"), str):
            content_parts.append(part["text"])
        function_call = part.get("functionCall")
        if isinstance(function_call, dict):
            tool_calls.append({
                "id": "",
                "function": {
                    "name": function_call.get("name", ""),
                    "arguments": function_call.get("args") or {},
                },
            })
    content = "".join(content_parts).strip()
    if not content and not tool_calls:
        raise RuntimeError("Gemini API returned no text or tool call.")
    return {"content": content, "tool_calls": tool_calls}


def call_llm(
    messages: list,
    tools:    list | None = None,
    timeout:  int = 120,
) -> dict:
    """
    Non-streaming chat request.  Routes to Ollama or OpenAI-compatible backend.

    Returns:
        {"content": str, "tool_calls": list}
    """
    url, model = get_llm_settings()
    provider   = get_llm_provider()

    if provider == "openai_api":
        return _call_openai_api(messages, tools, timeout)

    if provider == "gemini":
        return _call_gemini(messages, tools, timeout)

    if provider == "openai":
        endpoint = f"{url}/v1/chat/completions"
        payload: dict = {
            "model":      model,
            "messages":   messages,
            "stream":     False,
            "max_tokens": 150,
        }
        if tools:
            payload["tools"]       = tools
            payload["tool_choice"] = "auto"
        try:
            resp = requests.post(endpoint, json=payload, timeout=timeout)
            resp.raise_for_status()
            choice = resp.json().get("choices", [{}])[0]
            msg    = choice.get("message", {})
            # OpenAI tool_calls format → normalise to Ollama-style
            raw_tc  = msg.get("tool_calls") or []
            tc_list = [
                {
                    "id":       t.get("id", ""),
                    "function": {
                        "name":      t["function"]["name"],
                        "arguments": (
                            json.loads(t["function"]["arguments"])
                            if isinstance(t["function"].get("arguments"), str)
                            else t["function"].get("arguments", {})
                        ),
                    },
                }
                for t in raw_tc
            ]
            return {
                "content":    (msg.get("content") or "").strip(),
                "tool_calls": tc_list,
            }
        except Exception as e:
            raise RuntimeError(f"OpenAI-compatible LLM call failed: {e}")

    # ── Ollama ──────────────────────────────────────────────────────────────
    endpoint = f"{url}/api/chat"
    payload = {
        "model":      model,
        "messages":   messages,
        "stream":     False,
        "keep_alive": -1,
        "options":    {"num_predict": 150, "num_gpu": 99},
    }
    if tools:
        payload["tools"] = tools

    try:
        resp = requests.post(endpoint, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        msg  = data.get("message", {})
        return {
            "content":    (msg.get("content") or "").strip(),
            "tool_calls": msg.get("tool_calls") or [],
        }
    except requests.exceptions.ConnectionError as e:
        print(f"[LLM] ConnectionError — trying to restart Ollama… ({e})")
        if ensure_ollama_running():
            try:
                resp = requests.post(endpoint, json=payload, timeout=timeout)
                resp.raise_for_status()
                data = resp.json()
                msg  = data.get("message", {})
                return {
                    "content":    (msg.get("content") or "").strip(),
                    "tool_calls": msg.get("tool_calls") or [],
                }
            except Exception:
                pass
        raise RuntimeError(
            f"Cannot connect to Ollama at {url}. "
            "Make sure Ollama is installed and run: ollama serve"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError("Ollama request timed out after 120 s.")
    except requests.exceptions.HTTPError as e:
        print(f"[LLM] HTTPError: {e.response.status_code} — {e.response.text[:200]}")
        raise RuntimeError(f"Ollama HTTP error: {e.response.status_code}")
    except Exception as e:
        print(f"[LLM] Unexpected error: {type(e).__name__}: {e}")
        raise RuntimeError(f"LLM call failed: {e}")


def call_llm_text(
    prompt:  str,
    system:  str | None = None,
    model:   str | None = None,
    timeout: int = 120,
) -> str:
    """
    Simple text-only generation (no tools).
    Used by planner, executor, error_handler, code_helper, dev_agent.
    """
    url, default_model = get_llm_settings()
    endpoint = f"{url}/api/chat"
    m        = model or default_model

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    provider = get_llm_provider()
    if provider == "openai_api":
        return _call_openai_api(messages, None, timeout, model=m)["content"]
    if provider == "gemini":
        return _call_gemini(messages, None, timeout, model=m)["content"]

    payload = {"model": m, "messages": messages, "stream": False, "keep_alive": -1, "options": {"num_predict": 600}}

    try:
        resp = requests.post(endpoint, json=payload, timeout=timeout)
        resp.raise_for_status()
        return (resp.json().get("message", {}).get("content") or "").strip()
    except requests.exceptions.ConnectionError:
        if ensure_ollama_running():
            try:
                resp = requests.post(endpoint, json=payload, timeout=timeout)
                resp.raise_for_status()
                return (resp.json().get("message", {}).get("content") or "").strip()
            except Exception:
                pass
        raise RuntimeError(
            f"Cannot connect to Ollama at {url}. "
            "Make sure Ollama is installed and run: ollama serve"
        )
    except Exception as e:
        raise RuntimeError(f"LLM text call failed: {e}")


def _stream_openai(
    messages: list,
    tools:    list | None,
    timeout:  int,
) -> Generator[dict, None, None]:
    """
    Streaming backend for OpenAI-compatible servers (LM Studio, LocalAI, Jan…).

    Parses Server-Sent Events (SSE) and accumulates streaming tool-call fragments
    so the output format is identical to the Ollama backend.
    """
    url, model = get_llm_settings()
    endpoint   = f"{url}/v1/chat/completions"

    payload: dict = {
        "model":      model,
        "messages":   messages,
        "stream":     True,
        "max_tokens": 150,
    }
    if tools:
        payload["tools"]       = tools
        payload["tool_choice"] = "auto"

    try:
        with requests.post(endpoint, json=payload, timeout=timeout, stream=True) as resp:
            resp.raise_for_status()
            full_content = ""
            buf          = ""
            # tool_call fragments: index → {"id", "function": {"name", "arguments"}}
            tc_fragments: dict[int, dict] = {}

            for raw in resp.iter_lines():
                if not raw:
                    continue
                # SSE lines look like: b"data: {...}" or b"data: [DONE]"
                line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue

                choice = chunk.get("choices", [{}])[0]
                delta  = choice.get("delta", {})
                text   = delta.get("content") or ""

                full_content += text
                buf          += text

                # Accumulate sentence boundaries for streaming TTS
                while True:
                    m = _SENT_END.search(buf)
                    if not m:
                        break
                    sentence = buf[: m.start() + 1].strip()
                    buf      = buf[m.end():]
                    if sentence:
                        yield {"type": "sentence", "text": sentence}

                # Accumulate streaming tool-call fragments
                for tc in (delta.get("tool_calls") or []):
                    idx = tc.get("index", 0)
                    if idx not in tc_fragments:
                        tc_fragments[idx] = {"id": "", "function": {"name": "", "arguments": ""}}
                    frag = tc_fragments[idx]
                    frag["id"] = frag["id"] or tc.get("id", "")
                    fn = tc.get("function", {})
                    frag["function"]["name"]      += fn.get("name") or ""
                    frag["function"]["arguments"] += fn.get("arguments") or ""

                finish = choice.get("finish_reason")
                if finish in ("stop", "tool_calls", "length"):
                    break

            # Flush any trailing content
            if buf.strip():
                yield {"type": "sentence", "text": buf.strip()}

            # Parse accumulated tool-call argument strings → dicts
            tool_calls: list = []
            for idx in sorted(tc_fragments):
                frag = tc_fragments[idx]
                args = frag["function"]["arguments"]
                try:
                    args = json.loads(args)
                except Exception:
                    pass   # leave as raw string; _execute_tool handles it
                tool_calls.append({
                    "id":       frag["id"],
                    "function": {"name": frag["function"]["name"], "arguments": args},
                })

            yield {
                "type":       "done",
                "content":    full_content.strip(),
                "tool_calls": tool_calls,
            }

    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Cannot reach OpenAI-compatible server at {url}.\n"
            "Make sure LM Studio / LocalAI / Jan is running and the server is started."
        )
    except requests.exceptions.Timeout:
        raise RuntimeError("OpenAI-compatible stream timed out.")
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"OpenAI-compatible HTTP error: {e.response.status_code}")
    except Exception as e:
        raise RuntimeError(f"OpenAI-compatible stream failed: {e}")


def call_llm_stream(
    messages: list,
    tools:    list | None = None,
    timeout:  int = 120,
) -> Generator[dict, None, None]:
    """
    Streaming chat request.  Routes to Ollama or OpenAI-compatible backend.

    Yields:
        {"type": "sentence", "text": str}   — each complete sentence as it arrives
        {"type": "done", "content": str, "tool_calls": list}  — when stream ends

    Sentences are split on [.!?] + whitespace so TTS can start immediately.
    Tool calls always appear in the final "done" event.
    """
    provider = get_llm_provider()
    if provider in ("openai_api", "gemini"):
        result = (
            _call_openai_api(messages, tools, timeout)
            if provider == "openai_api"
            else _call_gemini(messages, tools, timeout)
        )
        content = result["content"]
        for sentence in _SENT_END.split(content):
            if sentence.strip():
                yield {"type": "sentence", "text": sentence.strip()}
        yield {"type": "done", "content": content, "tool_calls": result["tool_calls"]}
        return
    if provider == "openai":
        yield from _stream_openai(messages, tools, timeout)
        return

    url, model = get_llm_settings()
    endpoint   = f"{url}/api/chat"

    payload: dict = {
        "model":      model,
        "messages":   messages,
        "stream":     True,
        "keep_alive": -1,
        # 150 tokens ≈ 100 words ≈ 3-4 sentences — enough for any voice reply.
        # num_gpu:99 pushes all layers to GPU; num_thread removed (Ollama auto-tunes).
        "options":    {"num_predict": 150, "num_gpu": 99},
    }
    if tools:
        payload["tools"] = tools

    def _do_stream() -> Generator[dict, None, None]:
        with requests.post(endpoint, json=payload, timeout=timeout, stream=True) as resp:
            resp.raise_for_status()
            full_content = ""
            tool_calls:  list = []
            buf          = ""

            for raw in resp.iter_lines():
                if not raw:
                    continue
                try:
                    chunk = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg   = chunk.get("message", {})
                delta = msg.get("content") or ""

                full_content += delta
                buf          += delta

                # Yield complete sentences as they accumulate
                while True:
                    m = _SENT_END.search(buf)
                    if not m:
                        break
                    sentence = buf[: m.start() + 1].strip()
                    buf      = buf[m.end() :]
                    if sentence:
                        yield {"type": "sentence", "text": sentence}

                tc = msg.get("tool_calls")
                if tc:
                    tool_calls.extend(tc)

                if chunk.get("done"):
                    if buf.strip():
                        yield {"type": "sentence", "text": buf.strip()}

                    yield {
                        "type":       "done",
                        "content":    full_content.strip(),
                        "tool_calls": tool_calls,
                    }
                    return

    try:
        yield from _do_stream()
    except requests.exceptions.ConnectionError as e:
        print(f"[LLM] Stream ConnectionError — trying to restart Ollama… ({e})")
        if ensure_ollama_running():
            yield from _do_stream()
            return
        raise RuntimeError(
            f"Cannot connect to Ollama at {url}. "
            "Make sure Ollama is installed and run: ollama serve"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError("Ollama stream timed out.")
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"Ollama HTTP error: {e.response.status_code}")
    except Exception as e:
        print(f"[LLM] Stream error: {type(e).__name__}: {e}")
        raise RuntimeError(f"LLM stream failed: {e}")
