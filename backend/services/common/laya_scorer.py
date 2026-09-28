"""Optional local System-1 judgments for MICA.

Laya supplies semantic scores only. Deterministic replay scores, capability
rules, approvals, and execution remain authoritative. The package and model
weights are optional; public entry points keep the original result when Laya
is disabled, unavailable, uncertain, or returns an invalid response.
"""

from __future__ import annotations

import hashlib
import math
import os
import threading
from typing import Any

from .dream_rsi import _canonical

LAYA_AVAILABLE: bool | None = None
_SCORER: "LayaScorer | None" = None
_SCORER_LOCK = threading.Lock()


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return max(minimum, min(maximum, value))


def laya_enabled() -> bool:
    return os.getenv("MICA_LAYA_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def _probe_laya() -> bool:
    global LAYA_AVAILABLE
    if LAYA_AVAILABLE is None:
        try:
            import laya  # noqa: F401
            LAYA_AVAILABLE = True
        except Exception:
            LAYA_AVAILABLE = False
    return LAYA_AVAILABLE


class LayaScorer:
    """Long-lived, lazy Laya adapter for low-risk ranking and triage."""

    MAX_BATCH = 8

    def __init__(self, router: Any = None) -> None:
        self._router: Any = router
        self._router_failed = False
        self._router_lock = threading.Lock()

    @property
    def min_confidence(self) -> float:
        # This is application policy, not a claim that the base checkpoint is
        # calibrated for MICA. Representative MICA cases must still be measured.
        return _env_float("MICA_LAYA_MIN_CONFIDENCE", 0.40, 0.0, 1.0)

    def _ensure_router(self) -> Any:
        if self._router is not None:
            return self._router
        if self._router_failed:
            return None
        if not laya_enabled() or not _probe_laya():
            return None
        with self._router_lock:
            if self._router is not None:
                return self._router
            try:
                from laya import Router
                # German is MICA's primary language. The default matters for
                # short Latin-script inputs with too little detection evidence.
                model_dir = os.getenv("MICA_LAYA_MODEL_DIR", "").strip()
                models = None
                if model_dir:
                    if not os.path.isdir(model_dir):
                        raise FileNotFoundError("Configured local Laya model directory is missing")
                    models = {
                        "english": model_dir,
                        "multilingual": (model_dir, "multilingual"),
                    }
                self._router = Router(models=models, default="multilingual", preload=False)
            except Exception:
                self._router = None
                self._router_failed = True
        return self._router

    def _score(self, answer: Any, levels: int) -> tuple[float, float] | None:
        if not isinstance(answer, dict) or levels < 2:
            return None
        try:
            raw_score = float(answer["score"])
            # Laya's `confidence` is entropy concentration for score questions;
            # `answer_confidence` is the probability of the reported answer.
            confidence = float(answer.get("answer_confidence", answer.get("confidence")))
        except (KeyError, TypeError, ValueError):
            return None
        if not math.isfinite(raw_score) or not math.isfinite(confidence):
            return None
        if confidence < self.min_confidence:
            return None
        normalized = max(0.0, min(1.0, raw_score / float(levels - 1)))
        return normalized, max(0.0, min(1.0, confidence))

    def rerank(self, evaluations: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        """Advisory Dream-RSI ordering; deterministic replay stays authoritative."""
        router = self._ensure_router()
        batch = evaluations[: self.MAX_BATCH]
        if router is None or len(batch) < 2:
            return None
        try:
            state = {
                "evaluations": [
                    {
                        "replay_score": item["score"],
                        "expected_reward": item["expected_reward"],
                        "expected_cost": item["expected_cost"],
                        "wasted_fraction": item["wasted_fraction"],
                        "source": item["source"],
                        "policy": _canonical(item["policy"])[:400],
                    }
                    for item in batch
                ]
            }
            criteria = [
                "ungeeignet oder riskanter als die Alternativen",
                "brauchbar, aber ohne klaren Vorteil",
                "klarer konservativer Vorteil bei Reward, Kosten und Fehlversuchen",
            ]
            questions = {
                f"candidate_{index}": {
                    "type": "score",
                    "instructions": (
                        f"Bewerte ausschließlich `evaluations[{index}]` als Explorations-Policy. "
                        "Der Replay-Score bleibt die harte Entscheidungsgrundlage; bewerte hier nur "
                        "die semantische Plausibilität und Konservativität relativ zu den übrigen "
                        "Einträgen in `evaluations`."
                    ),
                    "criteria": criteria,
                }
                for index in range(len(batch))
            }
            answers = router.predict(state, questions)["answers"]
            scored: list[dict[str, Any]] = []
            for index, item in enumerate(batch):
                parsed = self._score(answers.get(f"candidate_{index}"), len(criteria))
                if parsed is None:
                    return None
                relevance, confidence = parsed
                scored.append({
                    **item,
                    "laya_score": round(relevance, 4),
                    "laya_confidence": round(confidence, 4),
                })
            weight = _env_float("MICA_LAYA_RERANK_WEIGHT", 0.15, 0.0, 0.5)
            scored.sort(key=lambda item: (
                -(float(item["score"]) + weight * (float(item["laya_score"]) - 0.5)),
                _canonical(item["policy"]),
            ))
            return scored + evaluations[self.MAX_BATCH:]
        except Exception:
            return None

    def rerank_retrieval(
        self, query: str, results: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        """Rerank a small Brain shortlist without changing its contents."""
        router = self._ensure_router()
        batch = results[: self.MAX_BATCH]
        if router is None or len(batch) < 2 or not str(query).strip():
            return None
        try:
            state = {
                "query": str(query)[:800],
                "candidates": [
                    {
                        "id": str(item.get("id", "")),
                        "title": str(item.get("title", ""))[:200],
                        "kind": str(item.get("kind", ""))[:80],
                        "snippet": str(item.get("snippet", ""))[:600],
                    }
                    for item in batch
                ],
            }
            criteria = [
                "nicht relevant für die Anfrage",
                "teilweise hilfreich oder nur Hintergrund",
                "direkt relevant und wahrscheinlich nützlich für die Antwort",
            ]
            questions = {
                f"document_{index}": {
                    "type": "score",
                    "instructions": (
                        f"Wie relevant ist ausschließlich `candidates[{index}]` für `query`? "
                        "Bewerte nur den belegten Inhalt aus Titel und Ausschnitt."
                    ),
                    "criteria": criteria,
                }
                for index in range(len(batch))
            }
            answers = router.predict(state, questions)["answers"]
            scored: list[tuple[float, int, dict[str, Any]]] = []
            for index, item in enumerate(batch):
                parsed = self._score(answers.get(f"document_{index}"), len(criteria))
                if parsed is None:
                    return None
                relevance, confidence = parsed
                scored.append((relevance, index, {
                    **item,
                    "laya_relevance": round(relevance, 4),
                    "laya_confidence": round(confidence, 4),
                }))
            scored.sort(key=lambda row: (-row[0], row[1]))
            return [row[2] for row in scored] + results[self.MAX_BATCH:]
        except Exception:
            return None

    def triage(self, error_type: str, context: str, occurrences: int) -> dict[str, Any] | None:
        """Classify a recurring improvement signal; None means no safe opinion."""
        router = self._ensure_router()
        if router is None:
            return None
        try:
            state = {
                "error_type": str(error_type)[:160],
                "context": str(context)[:600],
                "occurrences": int(occurrences),
            }
            criteria = ["ignorieren", "beobachten", "zeitnah untersuchen"]
            questions = {
                "priority": {
                    "type": "score",
                    "instructions": (
                        "Wie dringend sollte dieser wiederkehrende lokale Fehler untersucht werden? "
                        "Diese Bewertung darf keine Änderung freigeben oder ausführen."
                    ),
                    "criteria": criteria,
                },
                "worth_proposing": {
                    "type": "noul",
                    "instructions": (
                        "Ist der Kontext ausreichend, um eine kleine, reversible Prompt- oder "
                        "Konfigurationsanpassung lediglich zur menschlichen Prüfung vorzuschlagen?"
                    ),
                },
            }
            answers = router.predict(state, questions)["answers"]
            priority = self._score(answers.get("priority"), len(criteria))
            if priority is None:
                return None
            probability = float(answers["worth_proposing"]["noul"])
            if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
                return None
            threshold = _env_float("MICA_LAYA_PROPOSAL_THRESHOLD", 0.65, 0.5, 1.0)
            return {
                "priority": round(priority[0], 4),
                "worth_proposing": probability >= threshold,
                "proposal_probability": round(probability, 4),
                "confidence": round(priority[1], 4),
                "engine": "laya",
            }
        except Exception:
            return None


class HeuristicTriage:
    """Deterministic fallback: stable, explainable, dependency-free."""

    @staticmethod
    def triage(error_type: str, context: str, occurrences: int) -> dict[str, Any]:
        digest = hashlib.sha256(f"{error_type}:{context}".encode()).hexdigest()
        priority = int(digest[:8], 16) % 100 / 100
        return {
            "priority": round(0.3 + 0.7 * priority * min(occurrences, 10) / 10, 4),
            "worth_proposing": occurrences >= 3 and priority >= 0.2,
            "engine": "heuristic",
        }


def build_scorer() -> LayaScorer:
    """Return one lazy scorer per process so loaded checkpoints are reused."""
    global _SCORER
    if _SCORER is None:
        with _SCORER_LOCK:
            if _SCORER is None:
                _SCORER = LayaScorer()
    return _SCORER


def rerank_retrieval(query: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Public fail-open Brain reranker preserving the original shortlist."""
    if not laya_enabled():
        return results
    reranked = build_scorer().rerank_retrieval(query, results)
    return reranked if reranked is not None else results


def triage_signal(error_type: str, context: str, occurrences: int) -> dict[str, Any]:
    """Public entry point: Laya when confident, deterministic heuristic otherwise."""
    if laya_enabled():
        laya_result = build_scorer().triage(error_type, context, occurrences)
        if laya_result is not None:
            return laya_result
    return HeuristicTriage.triage(error_type, context, occurrences)
