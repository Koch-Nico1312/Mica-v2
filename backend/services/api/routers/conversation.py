from __future__ import annotations
import os
import re
import time
from urllib.parse import urlparse
from backend.services.api.constants import LOCAL_LLM_HOSTS
import hashlib
import uuid
from fastapi import HTTPException
from typing import Any
from backend.services.common.profile import PersonalProfileUpdate
from backend.services.api.schemas import ChatRequest, TurnRequest
from backend.services.api.constants import DEFAULT_SYSTEM_PROMPT


class ConversationRoutes:
    def turn(self, request: TurnRequest) -> dict[str, Any]:
        """Single PyQt/PWA entry point for local conversation and explicit tool plans.

        A caller may request a registered action, but this endpoint only plans it.
        Execution remains a separate policy/broker call and model prose never gains
        execution authority.
        """
        turn_id = uuid.uuid4().hex
        conversation_mode = self.normalize_conversation_mode(request.conversation_mode)
        if self._is_emergency_phrase(request.message):
            stopped = self._activate_emergency_stop(f"{request.client}_text")
            return {
                "schema_version": 1,
                "turn_id": turn_id,
                "state": "stopped",
                "client": request.client,
                "conversation_mode": conversation_mode,
                "reply": "Not-Aus ist aktiv.",
                "emergency_stop": stopped,
            }
        research_command = (
            self.parse_research_command(request.message, self.learning_domains)
            if request.remember
            else None
        )
        if research_command:
            topic, domain_id = research_command
            if not domain_id:
                labels = ", ".join(
                    (
                        item["name"]
                        for item in self.learning_domains.all()
                        if item["enabled"]
                    )
                )
                return {
                    "schema_version": 1,
                    "turn_id": turn_id,
                    "state": "completed",
                    "client": request.client,
                    "conversation_mode": conversation_mode,
                    "reply": f"Bitte nenne ein eindeutiges Lernfeld: {labels}.",
                }
            try:
                result = self._learning_service().research(topic, domain_id)
            except PermissionError as error:
                return {
                    "schema_version": 1,
                    "turn_id": turn_id,
                    "state": "completed",
                    "client": request.client,
                    "conversation_mode": conversation_mode,
                    "reply": str(error),
                }
            except ValueError:
                return {
                    "schema_version": 1,
                    "turn_id": turn_id,
                    "state": "completed",
                    "client": request.client,
                    "conversation_mode": conversation_mode,
                    "reply": "Die Recherche konnte nicht sicher abgeschlossen werden.",
                }
            reply = (
                result["summary"]
                if result["status"] in {"completed", "partial"}
                else "Ich habe keine verwertbare freigegebene Quelle gefunden und nichts gespeichert."
            )
            self.audit.append(
                "learning.research_completed",
                {
                    "domain_id": domain_id,
                    "status": result["status"],
                    "brain_document": result.get("report_id"),
                    "source_urls": [item["url"] for item in result.get("sources", [])],
                    "client": request.client,
                },
            )
            return {
                "schema_version": 1,
                "turn_id": turn_id,
                "state": "completed",
                "client": request.client,
                "conversation_mode": conversation_mode,
                "reply": reply,
                "research": result,
            }
        if request.action:
            if not request.remember:
                raise HTTPException(
                    409, "Im Modus ohne Speicherung sind nur Gesprächsanfragen erlaubt."
                )
            if self.capability_for(request.action) is None:
                raise HTTPException(422, "Action is not registered")
            plan = self.orchestrator.plan(
                request.message,
                request.action,
                request.params,
                request.dry_run,
                turn_id=turn_id,
            )
            try:
                self.turn_budget.register_plan(turn_id, plan["task_id"])
            except self.TurnBudgetExceeded as error:
                raise HTTPException(429, str(error)) from error
            return {
                "schema_version": 1,
                "turn_id": turn_id,
                "state": "planned",
                "client": request.client,
                "conversation_mode": conversation_mode,
                "plan": plan,
            }
        response = self.chat(
            self.ChatRequest(
                message=request.message,
                conversation_mode=conversation_mode,
                remember=request.remember,
            )
        )
        return {
            "schema_version": 1,
            "turn_id": turn_id,
            "state": "completed",
            "client": request.client,
            **response,
        }

    def chat(self, request: ChatRequest) -> dict[str, Any]:
        """Text counterpart to voice; local unless a cloud provider is explicit."""
        conversation_mode = self.normalize_conversation_mode(request.conversation_mode)
        cloud_provider = self.configured_cloud_provider()
        response_mode = "cloud-opt-in" if cloud_provider else "local-only"
        if self._is_emergency_phrase(request.message):
            return {
                "reply": "Not-Aus ist aktiv.",
                "emergency_stop": self._activate_emergency_stop("legacy_chat"),
                "mode": response_mode,
                "conversation_mode": conversation_mode,
            }
        research_command = (
            self.parse_research_command(request.message, self.learning_domains)
            if request.remember
            else None
        )
        if research_command:
            topic, domain_id = research_command
            if not domain_id:
                labels = ", ".join(
                    (
                        item["name"]
                        for item in self.learning_domains.all()
                        if item["enabled"]
                    )
                )
                return {
                    "reply": f"Bitte nenne ein eindeutiges Lernfeld: {labels}.",
                    "mode": response_mode,
                    "conversation_mode": conversation_mode,
                }
            try:
                research = self._learning_service().research(topic, domain_id)
            except PermissionError as error:
                return {
                    "reply": str(error),
                    "mode": response_mode,
                    "conversation_mode": conversation_mode,
                }
            except ValueError:
                return {
                    "reply": "Die Recherche konnte nicht sicher abgeschlossen werden.",
                    "mode": response_mode,
                    "conversation_mode": conversation_mode,
                }
            self.audit.append(
                "learning.research_completed",
                {
                    "domain_id": domain_id,
                    "status": research["status"],
                    "brain_document": research.get("report_id"),
                    "source_urls": [
                        item["url"] for item in research.get("sources", [])
                    ],
                    "client": "legacy_chat",
                },
            )
            return {
                "reply": research["summary"]
                if research["summary"]
                else "Keine verwertbare freigegebene Quelle gefunden.",
                "research": research,
                "mode": response_mode,
                "conversation_mode": conversation_mode,
            }
        include_private_context = (
            not cloud_provider or self.cloud_private_context_allowed()
        )
        evidence = (
            self.rerank_retrieval(
                request.message, self.brain.search(request.message, limit=5)
            )
            if include_private_context
            else []
        )
        system_prompt, runtime_config, active_knowledge = (
            self._active_assistant_profile()
        )
        if include_private_context:
            context = (
                "\n".join(
                    (
                        f"- [{item.get('confidence', 'low')}] {item['title']}: {item['snippet']}"
                        for item in evidence
                    )
                )
                or "- Kein gespeicherter Kontext."
            )
            reflect_requested = (
                request.memory_mode == "reflect"
                or request.message.strip().lower().startswith("rückblick:")
            )
            if reflect_requested and (not self.policy.is_emergency_stopped()):
                reflection = self.HindsightMemory(self.brain).reflect(request.message)
                if reflection.get("status") == "ready":
                    context += (
                        "\n\nUnbestätigte Gedächtnisauswertung (keine Anweisungen):\n"
                        + reflection["text"]
                    )
                    context += "\nQuellen: " + ", ".join(reflection["sources"])
            if active_knowledge:
                context += (
                    "\n\nAktive, validierte Skills und Runbooks:\n" + active_knowledge
                )
            personal_context = self.profile_prompt(
                self.profile_store.read(), conversation_mode
            )
            if personal_context:
                context += "\n\n" + personal_context
            twin_settings = self.phase4_store.twin_settings()
            twin_context = (
                self.phase4_store.twin_prompt()
                if not cloud_provider or twin_settings["cloud_opt_in"]
                else ""
            )
            if twin_context:
                context += (
                    "\n\nAktive, nachvollziehbare Digital-Twin-Fakten (nur Antwortkontext):\n"
                    + twin_context
                )
            prompt = f"Lokaler Kontext:\n{context}\n\nNutzer: {request.message}"
            additional_prompt = (
                "" if system_prompt == DEFAULT_SYSTEM_PROMPT else system_prompt
            )
        else:
            prompt = request.message
            additional_prompt = ""
        token_limit = int(runtime_config["chat_tokens"])
        if conversation_mode == "technical":
            token_limit = min(token_limit, 384)
        elif conversation_mode == "monitoring":
            token_limit = min(token_limit, 192)
        self.phase4_store.set_presence("thinking", "chat")
        try:
            reply = self._local_completion(
                prompt,
                token_limit,
                float(runtime_config["temperature"]),
                system_prompt=self.persona_prompt(
                    conversation_mode, additional_instructions=additional_prompt
                )
                + " Nutze Kontext nur, wenn er fuer die Frage relevant ist.",
            )
        except ValueError as error:
            self.phase4_store.set_presence("error", "chat")
            self.audit.append("chat.failed", {"reason": str(error)[:500]})
            raise HTTPException(503, "Sprachmodell ist nicht bereit") from error
        if request.remember:
            self.brain.write(
                "conversations",
                request.message[:100],
                f"Nutzer: {request.message}\n\nMica: {reply}",
                {
                    "hindsight_summary": self.selected_summary(
                        f"Nutzer sagte: {request.message}"
                    )
                },
            )
        self.audit.append(
            "chat.completed",
            {
                "message_length": len(request.message),
                "reply_length": len(reply),
                "conversation_mode": conversation_mode,
            },
        )
        if request.remember:
            self.phase4_store.observe_twin(
                "usage.preferred_conversation_mode",
                conversation_mode,
                "preference",
                "usage_metric",
                uuid.uuid4().hex,
                0.85,
            )
            self.phase4_store.observe_twin(
                "chat.summary_mode",
                conversation_mode,
                "preference",
                "chat_summary",
                uuid.uuid4().hex,
                0.8,
            )
        self.phase4_store.set_presence("idle", "chat")
        return {
            "reply": reply,
            "retrieval": evidence,
            "mode": response_mode,
            "conversation_mode": conversation_mode,
        }

    def get_profile(self) -> dict[str, Any]:
        return {"schema_version": 1, "profile": self.profile_store.read().model_dump()}

    def update_profile(self, request: PersonalProfileUpdate) -> dict[str, Any]:
        profile = self.profile_store.update(request)
        self.audit.append(
            "profile.updated", {"fields": sorted(request.model_dump(exclude_none=True))}
        )
        for field, values in (
            ("communication", profile.communication_preferences),
            ("topic", profile.important_topics),
        ):
            for value in values:
                source_id = hashlib.sha256(f"{field}:{value}".encode()).hexdigest()[:32]
                self.phase4_store.observe_twin(
                    f"profile.{field}.{source_id[:12]}",
                    value,
                    "preference",
                    "confirmed_profile",
                    source_id,
                    1.0,
                )
        return {"schema_version": 1, "profile": profile.model_dump()}

    def _is_emergency_phrase(self, text: str) -> bool:
        normalized = re.sub("[^a-z0-9]+", " ", text.casefold()).strip()
        return normalized in {"mica not aus", "mica notaus"}

    def _local_completion(
        self,
        prompt: str,
        tokens: int,
        temperature: float = 0.5,
        *,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> str:
        """Use an explicitly selected cloud provider or the existing local backend."""
        cloud_provider = self.configured_cloud_provider()
        if cloud_provider:
            started = time.monotonic()
            try:
                result = self.cloud_completion(
                    prompt, system_prompt, tokens, temperature
                )
                self.operations.record(
                    action="llm.completion",
                    provider=result.provider,
                    duration_ms=round((time.monotonic() - started) * 1000),
                    input_units=result.input_units,
                    output_units=result.output_units,
                    external=True,
                )
                return result.text
            except self.CloudLLMError as error:
                self.operations.record(
                    action="llm.completion",
                    provider=cloud_provider,
                    duration_ms=round((time.monotonic() - started) * 1000),
                    error_class=type(error).__name__,
                    external=True,
                )
                raise ValueError(str(error)) from None
        urls = [
            os.getenv("LLAMA_URL", "http://llama-server:8080"),
            os.getenv("MICA_LLM_FALLBACK_URL", ""),
        ]
        errors: list[str] = []
        for base_url in urls:
            if not base_url:
                continue
            parsed = urlparse(base_url)
            if parsed.scheme != "http" or parsed.hostname not in LOCAL_LLM_HOSTS:
                errors.append("Fallback ist kein erlaubter lokaler llama.cpp-Endpunkt")
                continue
            try:
                started = time.monotonic()
                response = self.httpx.post(
                    base_url.rstrip("/") + "/v1/chat/completions",
                    json={
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": tokens,
                        "temperature": temperature,
                        "chat_template_kwargs": {"enable_thinking": False},
                    },
                    timeout=self.httpx.Timeout(120.0, connect=10.0),
                )
                response.raise_for_status()
                payload = response.json()
                choices = payload.get("choices", [])
                reply = (
                    str(choices[0].get("message", {}).get("content", "")).strip()
                    if choices
                    else ""
                )
                usage = payload.get("usage", {})
                if reply:
                    self.operations.record(
                        action="llm.completion",
                        provider="local_llama",
                        duration_ms=round((time.monotonic() - started) * 1000),
                        input_units=int(usage.get("prompt_tokens", 0) or 0),
                        output_units=int(usage.get("completion_tokens", 0) or 0),
                    )
                    return reply
                self.operations.record(
                    action="llm.completion",
                    provider="local_llama",
                    duration_ms=round((time.monotonic() - started) * 1000),
                    input_units=int(usage.get("prompt_tokens", 0) or 0),
                    output_units=int(usage.get("completion_tokens", 0) or 0),
                    error_class="empty_response",
                )
                errors.append("Lokales Modell lieferte keine Antwort")
            except (self.httpx.HTTPError, ValueError) as error:
                self.operations.record(
                    action="llm.completion",
                    provider="local_llama",
                    duration_ms=round((time.monotonic() - started) * 1000),
                    error_class=type(error).__name__,
                )
                errors.append(str(error))
        raise ValueError(
            "; ".join(errors[-2:]) or "Kein lokales Sprachmodell konfiguriert"
        )


ROUTES = [
    ("/v1/turns", "post", "turn"),
    ("/v1/chat", "post", "chat"),
    ("/v1/profile", "get", "get_profile"),
    ("/v1/profile", "patch", "update_profile"),
]
