"""Laya as a local System-1 scorer for the Dream-RSI loop.

Laya (https://github.com/NandhaKishorM/laya) is a small, non-autoregressive
decision engine: typed questions (choice / score / yes-no) over a state in a
single forward pass, ~33 ms on CPU, multilingual including German. Nothing is
generated, so nothing can be hallucinated.

This integration is deliberately optional:

- ``laya`` is never imported at module scope; the scorer degrades to a
  deterministic heuristic fallback when the package or its checkpoints are
  unavailable (cold model builds cost seconds and a download, so they only
  happen when MICA_LAYA_ENABLED=1).
- The scorer may only *reorder* Dream-RSI replay evaluations and triage
  improvement signals. It never grants authority, never executes anything,
  and its failure never breaks the pipeline.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

from .dream_rsi import _canonical

LAYA_AVAILABLE: bool | None = None  # tri-state cache: None = not probed yet


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
    """Rank Dream-RSI policy evaluations with typed, local decisions."""

    MAX_BATCH = 8

    def __init__(self) -> None:
        self._router: Any = None

    def _ensure_router(self) -> Any:
        if self._router is not None:
            return self._router
        if not laya_enabled() or not _probe_laya():
            return None
        try:
            from laya import Router

            # English and multilingual checkpoints only; preload=False keeps
            # startup cheap — the first predict builds lazily on CPU.
            self._router = Router(preload=False)
        except Exception:
            self._router = None
        return self._router

    # ── Ranking replay evaluations ───────────────────────────────────────────

    def rerank(self, evaluations: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        """Reorder replay evaluations by Laya's score-type decisions.

        Returns None whenever Laya is unavailable, the batch is trivial, or
        anything goes wrong — callers then keep the deterministic order.
        """
        router = self._ensure_router()
        if router is None or len(evaluations) < 2:
            return None
        try:
            state = {
                "evaluations": [
                    {
                        "score": item["score"],
                        "expected_reward": item["expected_reward"],
                        "expected_cost": item["expected_cost"],
                        "wasted_fraction": item["wasted_fraction"],
                        "source": item["source"],
                        "policy": _canonical(item["policy"])[:400],
                    }
                    for item in evaluations[: self.MAX_BATCH]
                ]
            }
            questions = {
                "ranking": {
                    "type": "score",
                    "instructions": (
                        "Wie vielversprechend ist diese Explorations-Policy für einen "
                        "Selbstverbesserungs-Loop? Berücksichtige erwarteten Reward pro Kosten, "
                        "verschwendete Wiederholungen und Konservativität."
                    ),
                    "criteria": ["unbrauchbar", "durchschnittlich", "klar besser als die Alternative"],
                }
            }
            result = router.predict(state, questions)
            scores = result["answers"]["ranking"]["scores"]
            ranked = [
                {**item, "laya_score": round(float(score), 4)}
                for item, score in zip(evaluations[: self.MAX_BATCH], scores)
            ]
            ranked.sort(
                key=lambda item: (-(item["score"] + item.get("laya_score", 0.0)), _canonical(item["policy"]))
            )
            remaining = evaluations[self.MAX_BATCH:]
            if remaining:
                ranked = ranked + remaining
            return ranked
        except Exception:
            return None

    # ── Triage of improvement signals ────────────────────────────────────────

    def triage(self, error_type: str, context: str, occurrences: int) -> dict[str, Any] | None:
        """Classify a recurring improvement signal; None means "no opinion"."""
        router = self._ensure_router()
        if router is None:
            return None
        try:
            state = {
                "error_type": str(error_type)[:160],
                "context": str(context)[:600],
                "occurrences": int(occurrences),
            }
            questions = {
                "priority": {
                    "type": "score",
                    "instructions": (
                        "Wie dringend sollte ein wiederkehrender lokaler Fehler eine "
                        "Verbesserungs-Policy-Anpassung auslösen?"
                    ),
                    "criteria": ["ignorieren", "beobachten", "sofort anpassen"],
                },
                "worth_proposing": {
                    "type": "noul",
                    "instructions": (
                        "Ist der Kontext ausreichend, um eine kleine, gutartige "
                        "Prompt- oder Konfigurationsanpassung vorzuschlagen?"
                    ),
                },
            }
            result = router.predict(state, questions)
            priority_scores = result["answers"]["priority"]["scores"]
            return {
                "priority": round(float(priority_scores[-1]), 4),
                "worth_proposing": bool(result["answers"]["worth_proposing"]["answer"]),
                "engine": "laya",
            }
        except Exception:
            return None


class HeuristicTriage:
    """Deterministic fallback: stable, explainable, dependency-free."""

    @staticmethod
    def triage(error_type: str, context: str, occurrences: int) -> dict[str, Any]:
        digest = hashlib.sha256(f"{error_type}:{context}".encode()).hexdigest()
        # Bounded, deterministic pseudo-score in [0, 1) from the signature so
        # behaviour is reproducible for tests and audits.
        priority = int(digest[:8], 16) % 100 / 100
        return {
            "priority": round(0.3 + 0.7 * priority * min(occurrences, 10) / 10, 4),
            "worth_proposing": occurrences >= 3 and priority >= 0.2,
            "engine": "heuristic",
        }


def build_scorer() -> LayaScorer:
    return LayaScorer()


def triage_signal(error_type: str, context: str, occurrences: int) -> dict[str, Any]:
    """Public entry point: Laya when enabled, heuristic otherwise."""
    if laya_enabled():
        laya_result = LayaScorer().triage(error_type, context, occurrences)
        if laya_result is not None:
            return laya_result
    return HeuristicTriage.triage(error_type, context, occurrences)
