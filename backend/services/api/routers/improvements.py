from __future__ import annotations
import json
from backend.services.api.constants import DEFAULT_SYSTEM_PROMPT
import os
import uuid
from fastapi import HTTPException
from typing import Any
from backend.services.api.schemas import (
    DreamCycleRequest,
    ImprovementEvaluation,
    ImprovementPromotion,
    ImprovementProposal,
)


class ImprovementsRoutes:
    def list_improvements(self, name: str | None = None) -> dict[str, Any]:
        return {"improvements": self.improvements.list(name)}

    def active_improvements(self, name: str | None = None) -> dict[str, Any]:
        """Read the atomically activated, checksum-verified artifact state.

        This endpoint exposes no execution hook. Prompt, skill and allowlisted
        configuration are consumed by MICA as data. Code can run only through the
        separately approved, networkless host-agent sandbox; policy, secrets and
        host-agent authority do not live in this registry or manifest.
        """
        if name:
            artifact = self.improvements.runtime_artifact(name)
            if not artifact:
                raise HTTPException(
                    404, "No verified active improvement with that name"
                )
            return {"artifact": artifact}
        return {"state": self.improvements.runtime_state()}

    def propose_improvement(self, request: ImprovementProposal) -> dict[str, str]:
        try:
            result = self.improvements.propose(
                request.name, request.kind, request.content, request.evidence
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        self.audit.append(
            "improvement.proposed",
            {"improvement_id": result["id"], "status": result["status"]},
        )
        return result

    def evaluate_improvement(
        self, improvement_id: str, request: ImprovementEvaluation
    ) -> dict[str, bool]:
        if request.auto_promote:
            raise HTTPException(
                422,
                "Automatic promotion is disabled; use the separately approved promote endpoint",
            )
        payload = {
            "task_id": uuid.uuid4().hex,
            "action": "improvement.shadow",
            "params": {"improvement_id": improvement_id},
            "approval_id": request.approval_id,
        }
        try:
            response = self.httpx.post(
                os.getenv("TOOL_BROKER_URL", "http://tool-broker:8093")
                + "/v1/tools/call",
                json={**payload, "audit_mode": "ids_only"},
                timeout=self.httpx.Timeout(90.0, connect=5.0),
            )
            if response.status_code == 403:
                raise HTTPException(
                    403, detail=response.json().get("detail", "Approval required")
                )
            response.raise_for_status()
            broker_result = response.json()
        except HTTPException:
            raise
        except (self.httpx.HTTPError, ValueError) as error:
            restored = self.improvements.record_shadow_failure(
                improvement_id, str(error)
            )
            self.phase4_store.quarantine_improvement(improvement_id)
            self.audit.append(
                "improvement.shadow_failed",
                {
                    "improvement_id": improvement_id,
                    "status": "restored" if restored else "quarantined",
                },
            )
            raise HTTPException(
                503, "Isolated shadow evaluation failed; active revision was preserved"
            ) from error
        result = broker_result.get("result", {})
        evidence = __import__("json").dumps(result, ensure_ascii=False, sort_keys=True)
        evaluated = self.improvements.evaluate(
            improvement_id,
            bool(result.get("tests_passed")),
            bool(result.get("health_passed")),
            evidence,
            evidence,
        )
        if not evaluated:
            restored = self.improvements.record_shadow_failure(improvement_id, evidence)
            self.phase4_store.quarantine_improvement(improvement_id)
            self.audit.append(
                "improvement.shadow_failed",
                {
                    "improvement_id": improvement_id,
                    "status": "restored" if restored else "quarantined",
                },
            )
            return {"validated": False, "promoted": False, "restored": restored}
        promoted = False
        if evaluated:
            self.audit.append(
                "improvement.validated",
                {"improvement_id": improvement_id, "status": "validated"},
            )
        return {"validated": evaluated, "promoted": promoted}

    def dream_state(self) -> dict[str, Any]:
        """Dream-RSI overview: pool, active policy and recent cycles."""
        return self.dream_engine.state()

    def dream_policies(self) -> dict[str, Any]:
        """Recorded replay evaluations of candidate exploration policies."""
        return {"evaluations": self.dream_engine.store.evaluations(50)}

    def dream_cycle(self, request: DreamCycleRequest) -> dict[str, Any]:
        """Run one bounded dream cycle on demand.

        Read-only replay; the only write is the policy proposal through the fully
        validated registry. Proposing needs no approval — promotion is the gated
        step (`POST /v1/improvements/{id}/promote`), so this endpoint deliberately
        returns no approval id and accepts none.
        """
        cycle = self.dream_engine.run_cycle(
            max_candidates=request.max_candidates, min_pool=3
        )
        self.audit.append(
            "dream_rsi.manual_cycle",
            {
                "status": cycle["status"],
                "reason": cycle["reason"],
                "proposal_id": cycle.get("proposal_id", ""),
            },
        )
        return {"cycle": cycle}

    def promote_improvement(
        self, improvement_id: str, request: ImprovementPromotion
    ) -> dict[str, bool]:
        params = {"improvement_id": improvement_id}
        if request.approval_id and self.policy.consume_approval(
            request.approval_id, "improvement.promote", params
        ):
            decision = None
        else:
            decision = self.policy.decide("improvement.promote", params)
        if decision is not None and (not decision.allowed):
            raise HTTPException(
                status_code=403,
                detail={"reason": decision.reason, "approval_id": decision.approval_id},
            )
        promoted = self.improvements.promote(improvement_id)
        if promoted:
            self.audit.append(
                "improvement.promoted",
                {"improvement_id": improvement_id, "status": "promoted"},
            )
        return {"promoted": promoted}

    def rollback_improvement(
        self, name: str, request: ImprovementPromotion
    ) -> dict[str, bool]:
        params = {"name": name}
        if request.approval_id and self.policy.consume_approval(
            request.approval_id, "improvement.rollback", params
        ):
            decision = None
        else:
            decision = self.policy.decide("improvement.rollback", params)
        if decision is not None and (not decision.allowed):
            raise HTTPException(
                status_code=403,
                detail={"reason": decision.reason, "approval_id": decision.approval_id},
            )
        active_before = next(
            (
                item
                for item in self.improvements.list(name)
                if item["status"] == "active"
            ),
            None,
        )
        rolled_back = self.improvements.rollback(name)
        if rolled_back:
            self.audit.append(
                "improvement.rolled_back",
                {
                    "improvement_id": active_before["id"]
                    if active_before
                    else "unknown",
                    "status": "rolled_back",
                },
            )
        return {"rolled_back": rolled_back}

    def _dream_summarizer(self, prompt: str) -> str:
        """Lazily resolved: names below exist after full module import."""
        return self._local_completion(
            prompt,
            768,
            0.2,
            system_prompt=self.persona_prompt("technical")
            + " Du optimierst Explorations-Policies als reines JSON.",
        )

    def _active_assistant_profile(self) -> tuple[str, dict[str, Any], str]:
        """Load only checksum-verified, promoted runtime artifacts.

        Prompts and the small allowlisted generation configuration are applied to
        both text and voice immediately after promotion. Skills and runbooks are
        supplied as local context. Code artifacts remain confined to the isolated
        host-agent runner and are never imported into this policy-bearing process.
        """
        system_prompt = DEFAULT_SYSTEM_PROMPT
        config: dict[str, Any] = {
            "temperature": 0.5,
            "chat_tokens": 384,
            "voice_tokens": 256,
        }
        knowledge: list[str] = []
        prompt_artifact = self.improvements.runtime_artifact("mica-system-prompt")
        if prompt_artifact and prompt_artifact.get("kind") == "prompt":
            candidate = str(prompt_artifact.get("content", "")).strip()
            if candidate:
                system_prompt = candidate[:8000]
        config_artifact = self.improvements.runtime_artifact("mica-runtime-config")
        if config_artifact and config_artifact.get("kind") == "config":
            try:
                raw = json.loads(str(config_artifact.get("content", "")))
            except (TypeError, ValueError, json.JSONDecodeError):
                raw = {}
            if isinstance(raw, dict):
                temperature = raw.get("temperature")
                chat_tokens = raw.get("chat_tokens")
                voice_tokens = raw.get("voice_tokens")
                if (
                    isinstance(temperature, (int, float))
                    and 0.0 <= float(temperature) <= 1.0
                ):
                    config["temperature"] = float(temperature)
                if isinstance(chat_tokens, int) and 64 <= chat_tokens <= 2048:
                    config["chat_tokens"] = chat_tokens
                if isinstance(voice_tokens, int) and 64 <= voice_tokens <= 1024:
                    config["voice_tokens"] = voice_tokens
        for artifact in self.improvements.runtime_state().get("artifacts", []):
            if artifact.get("kind") not in {"skill", "runbook"}:
                continue
            active = self.improvements.runtime_artifact(str(artifact.get("name", "")))
            if active and active.get("kind") in {"skill", "runbook"}:
                content = str(active.get("content", "")).strip()
                if content:
                    knowledge.append(
                        f"[{active['kind']}: {active['name']}]\n{content[:4000]}"
                    )
            if sum((len(item) for item in knowledge)) >= 8000:
                break
        return (system_prompt, config, "\n\n".join(knowledge)[:8000])


ROUTES = [
    ("/v1/improvements", "get", "list_improvements"),
    ("/v1/improvements/active", "get", "active_improvements"),
    ("/v1/improvements", "post", "propose_improvement"),
    ("/v1/improvements/{improvement_id}/evaluate", "post", "evaluate_improvement"),
    ("/v1/dream/state", "get", "dream_state"),
    ("/v1/dream/policies", "get", "dream_policies"),
    ("/v1/dream/cycle", "post", "dream_cycle"),
    ("/v1/improvements/{improvement_id}/promote", "post", "promote_improvement"),
    ("/v1/improvements/{name}/rollback", "post", "rollback_improvement"),
]
