"""Dream-RSI: Recursive Self-Improvement through Evolving Worlds.

Adapted from Zheng et al. 2026 (https://dream-rsi.com) to MICA's data-only
improvement pipeline. The upstream codebase was not released at the time of
writing, so this module implements the paper's three-step loop directly:

1. ONLINE: every improvement lifecycle event (propose, evaluate, shadow
   failure, promote, rollback) is recorded as a node in a discovery tree.
2. WORLD MODEL: the recorded trees act as a replay simulator. Alternative
   exploration policies are evaluated off-policy by re-traversing recorded
   branches — pure reads, no execution.
3. DREAMING: candidate policies are compared over the simulator; the best one
   is proposed as a ``config`` artifact through the existing, fully validated
   ImprovementRegistry path. Promotion still requires the explicit human
   approval gate; nothing here bypasses the policy engine.

Security invariants:
- Dreaming never executes code and never touches the host.
- Policy candidates pass the registry's protected-key validation; the artifact
  name avoids protected name parts by design ("dream-exploration-config").
- The whole loop is disabled unless MICA_DREAM_RSI_ENABLED=1, respects the
  emergency stop, and is bounded by small budgets.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterator

POLICY_ARTIFACT_NAME = "dream-exploration-config"
KINDS = {"prompt", "skill", "code", "config", "runbook"}
EVENTS = {"propose", "evaluate", "shadow_failed", "promote", "rollback"}

DEFAULT_POLICY: dict[str, Any] = {
    "propose_after_occurrences": 3,
    "max_open_candidates": 10,
    "retry_backoff_factor": 1.0,
    "kind_preference": ["prompt", "config"],
    "stop_on_shadow_failure": False,
}

EVENT_REWARD = {
    "propose": 0.0,
    "shadow_failed": 0.0,
    "promote": 1.0,
    "rollback": -0.5,
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def enabled(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def dream_enabled() -> bool:
    return enabled("MICA_DREAM_RSI_ENABLED")


class PolicyConfig:
    """Validate and normalize an exploration policy candidate.

    The schema is deliberately tiny and allowlisted; every field is a bounded
    scalar so a promoted policy can only steer how often and how eagerly MICA
    proposes improvements — never what authority it has.
    """

    FIELD_LIMITS: dict[str, tuple[type, int | float, int | float]] = {
        "propose_after_occurrences": (int, 1, 20),
        "max_open_candidates": (int, 1, 25),
        "retry_backoff_factor": (float, 1.0, 10.0),
    }

    @classmethod
    def normalize(cls, raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        if set(raw) - set(DEFAULT_POLICY):
            return None
        policy = dict(DEFAULT_POLICY)
        for field, (field_type, low, high) in cls.FIELD_LIMITS.items():
            if field in raw:
                value = raw[field]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or isinstance(value, float) and field_type is int:
                    return None
                if not low <= value <= high:
                    return None
                policy[field] = field_type(value)
        if "stop_on_shadow_failure" in raw:
            if not isinstance(raw["stop_on_shadow_failure"], bool):
                return None
            policy["stop_on_shadow_failure"] = raw["stop_on_shadow_failure"]
        if "kind_preference" in raw:
            kinds = raw["kind_preference"]
            if not isinstance(kinds, list) or not kinds or not set(kinds) <= KINDS or len(set(kinds)) != len(kinds):
                return None
            policy["kind_preference"] = [str(item) for item in kinds]
        return policy


def reward_from_evaluation(tests_passed: bool, health_passed: bool) -> float:
    """Deterministic reward from shadow evaluation evidence (0..1)."""
    return round(0.6 * bool(tests_passed) + 0.4 * bool(health_passed), 3)


class DreamTreeStore:
    """SQLite-backed discovery tree over improvement lifecycle events."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.getenv("MICA_DREAM_DB", "/data/dream.sqlite3"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS dream_nodes (
                    id TEXT PRIMARY KEY, parent_id TEXT, tree_id TEXT NOT NULL,
                    improvement_id TEXT, improvement_name TEXT, kind TEXT,
                    event TEXT NOT NULL, outcome TEXT, reward REAL NOT NULL DEFAULT 0,
                    cost REAL NOT NULL DEFAULT 0, detail TEXT, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dream_cycles (
                    id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
                    pool_size INTEGER NOT NULL DEFAULT 0, candidates INTEGER NOT NULL DEFAULT 0,
                    winner_policy TEXT, winner_score REAL, proposal_id TEXT,
                    status TEXT NOT NULL, reason TEXT
                );
                CREATE TABLE IF NOT EXISTS dream_evaluations (
                    id TEXT PRIMARY KEY, cycle_id TEXT NOT NULL, policy_json TEXT NOT NULL,
                    score REAL NOT NULL, expected_reward REAL NOT NULL, expected_cost REAL NOT NULL,
                    branch_count INTEGER NOT NULL, wasted_fraction REAL NOT NULL, source TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_dream_nodes_tree ON dream_nodes(tree_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_dream_nodes_improvement ON dream_nodes(improvement_id);
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            yield conn
        finally:
            conn.close()

    def record_event(
        self, event: str, improvement_id: str = "", name: str = "", kind: str = "",
        outcome: str = "", reward: float = 0.0, cost: float = 0.0, detail: dict[str, Any] | None = None,
    ) -> None:
        if event not in EVENTS:
            raise ValueError("unknown dream event")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            tree_row = conn.execute(
                "SELECT tree_id FROM dream_nodes WHERE improvement_id = ? AND event = 'propose' LIMIT 1",
                (improvement_id,),
            ).fetchone() if improvement_id else None
            tree_id = tree_row[0] if tree_row else (improvement_id or f"event-{uuid.uuid4().hex[:16]}")
            parent_row = conn.execute(
                "SELECT id FROM dream_nodes WHERE improvement_id = ? ORDER BY created_at DESC LIMIT 1",
                (improvement_id,),
            ).fetchone() if improvement_id else None
            conn.execute(
                "INSERT INTO dream_nodes(id, parent_id, tree_id, improvement_id, improvement_name, kind, "
                "event, outcome, reward, cost, detail, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    uuid.uuid4().hex, parent_row[0] if parent_row else None, tree_id,
                    improvement_id or None, (name or "")[:160] or None, (kind or "")[:40] or None,
                    event, (outcome or "")[:40] or None, float(reward), float(cost),
                    _canonical(detail)[:2000] if detail else None, _now(),
                ),
            )
            conn.execute("COMMIT")

    def tag_tree(self, improvement_id: str, error_signature: str) -> None:
        """Attach an improvement-signal signature to the tree of a proposal."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            tree_row = conn.execute(
                "SELECT tree_id FROM dream_nodes WHERE improvement_id = ? AND event = 'propose' LIMIT 1",
                (improvement_id,),
            ).fetchone()
            if tree_row:
                conn.execute(
                    "UPDATE dream_nodes SET detail = COALESCE(detail, '{}') WHERE tree_id = ? AND event = 'propose'",
                    (tree_row[0],),
                )
            conn.execute("COMMIT")

    def trees(self) -> list[list[dict[str, Any]]]:
        """Return every discovery tree as an ordered list of nodes."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT tree_id, improvement_id, improvement_name, kind, event, outcome, reward, cost, created_at "
                "FROM dream_nodes ORDER BY created_at ASC, id ASC"
            ).fetchall()
        ordered: dict[str, list[dict[str, Any]]] = {}
        keys = ("tree_id", "improvement_id", "improvement_name", "kind", "event", "outcome", "reward", "cost", "created_at")
        for row in rows:
            ordered.setdefault(row[0], []).append(dict(zip(keys, row)))
        return list(ordered.values())

    def open_candidate_count(self) -> int:
        """Improvement candidates that are proposed/validated but not terminal."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT improvement_name FROM dream_nodes WHERE event = 'propose'"
            ).fetchall()
        names = {row[0] for row in rows if row[0]}
        return len(names)

    def record_cycle(
        self, cycle_id: str, started_at: str, status: str, reason: str = "",
        pool_size: int = 0, candidates: int = 0, winner_policy: dict[str, Any] | None = None,
        winner_score: float | None = None, proposal_id: str = "", evaluations: list[dict[str, Any]] | None = None,
    ) -> None:
        finished = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO dream_cycles(id, started_at, finished_at, pool_size, candidates, winner_policy, "
                "winner_score, proposal_id, status, reason) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    cycle_id, started_at, finished, int(pool_size), int(candidates),
                    _canonical(winner_policy) if winner_policy else None,
                    None if winner_score is None else float(winner_score),
                    proposal_id or None, status, reason[:400],
                ),
            )
            for item in evaluations or []:
                conn.execute(
                    "INSERT INTO dream_evaluations(id, cycle_id, policy_json, score, expected_reward, "
                    "expected_cost, branch_count, wasted_fraction, source) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        uuid.uuid4().hex, cycle_id, _canonical(item["policy"]), float(item["score"]),
                        float(item["expected_reward"]), float(item["expected_cost"]),
                        int(item["branch_count"]), float(item["wasted_fraction"]), item["source"][:40],
                    ),
                )
            conn.execute("COMMIT")

    def evaluations(self, limit: int = 50) -> list[dict[str, Any]]:
        """Recorded per-candidate replay evaluations, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT e.policy_json, e.score, e.expected_reward, e.expected_cost, e.branch_count, "
                "e.wasted_fraction, e.source, c.started_at FROM dream_evaluations e "
                "JOIN dream_cycles c ON c.id = e.cycle_id ORDER BY c.started_at DESC LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        result = []
        for row in rows:
            try:
                policy_json = json.loads(row[0])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            result.append({
                "policy": policy_json, "score": row[1], "expected_reward": row[2],
                "expected_cost": row[3], "branch_count": row[4], "wasted_fraction": row[5],
                "source": row[6], "cycle_started_at": row[7],
            })
        return result

    def cycles(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, started_at, finished_at, pool_size, candidates, winner_policy, winner_score, "
                "proposal_id, status, reason FROM dream_cycles ORDER BY started_at DESC LIMIT ?",
                (max(1, min(int(limit), 100)),),
            ).fetchall()
        result = []
        for row in rows:
            item = {
                "id": row[0], "started_at": row[1], "finished_at": row[2],
                "pool_size": row[3], "candidates": row[4], "winner_score": row[6],
                "proposal_id": row[7], "status": row[8], "reason": row[9],
            }
            try:
                item["winner_policy"] = json.loads(row[5]) if row[5] else None
            except (TypeError, ValueError, json.JSONDecodeError):
                item["winner_policy"] = None
            result.append(item)
        return result


class ReplaySimulator:
    """Replay recorded discovery trees under a candidate exploration policy.

    The simulator is the Dream-RSI "world model": all outcomes are already
    recorded, so evaluating a policy costs only reads. A policy earns reward
    for validated evaluations and successful promotions, loses reward on
    rollbacks, and pays a cost per simulated step. Policies that stop early
    after failed shadow evaluations avoid wasted retries — visible as a
    better reward-per-cost score.
    """

    PROMOTION_BONUS = 0.5
    WASTED_PENALTY = 0.5
    MIN_COST = 0.5

    def replay(self, trees: list[list[dict[str, Any]]], policy: dict[str, Any]) -> dict[str, Any]:
        total_reward = 0.0
        total_cost = 0.0
        promotions = 0
        wasted = 0
        for nodes in trees:
            reward, cost, tree_promotions, tree_wasted = self._replay_tree(nodes, policy)
            total_reward += reward
            total_cost += cost
            promotions += tree_promotions
            wasted += tree_wasted
        wasted_fraction = wasted / promotions if promotions else 0.0
        score = round(total_reward / max(total_cost, self.MIN_COST) - self.WASTED_PENALTY * wasted_fraction, 4)
        return {
            "score": score,
            "expected_reward": round(total_reward, 3),
            "expected_cost": round(total_cost, 3),
            "branch_count": len(trees),
            "wasted_fraction": round(wasted_fraction, 3),
        }

    def _replay_tree(
        self, nodes: list[dict[str, Any]], policy: dict[str, Any],
    ) -> tuple[float, float, int, int]:
        reward = 0.0
        cost = 0.0
        promotions = 0
        wasted = 0
        for node in nodes:
            event = node["event"]
            if event == "propose":
                cost += 1.0
            elif event == "evaluate":
                cost += 1.0
                if node["outcome"] == "validated":
                    reward += float(node["reward"])
                elif node["outcome"] == "failed" and policy.get("stop_on_shadow_failure"):
                    break
            elif event == "promote":
                cost += 1.0
                promotions += 1
                reward += self.PROMOTION_BONUS
            elif event == "rollback":
                reward += float(node["reward"])
                wasted += 1
        return reward, cost, promotions, wasted


class LLMCandidateError(ValueError):
    pass


class DreamRSIEngine:
    """The closed meta-loop: record → dream → propose the best policy."""

    MAX_LLM_CANDIDATES = 3

    def __init__(
        self, store: DreamTreeStore, registry: Any, brain: Any,
        summarizer: Callable[[str], str] | None = None, scorer: Any = None,
        emergency_stopped: Callable[[], bool] | None = None,
    ):
        self.store = store
        self.registry = registry
        self.brain = brain
        self.summarizer = summarizer
        self.scorer = scorer
        self.emergency_stopped = emergency_stopped or (lambda: False)
        self.simulator = ReplaySimulator()

    # ── Recording (the "online" loop) ────────────────────────────────────────

    def build_event_listener(self) -> Callable[[str, dict[str, Any]], None]:
        def listener(event: str, payload: dict[str, Any]) -> None:
            try:
                if event == "evaluate":
                    reward = reward_from_evaluation(
                        bool(payload.get("tests_passed")), bool(payload.get("health_passed")),
                    )
                    self.store.record_event(
                        "evaluate", improvement_id=str(payload.get("improvement_id", "")),
                        outcome="validated" if payload.get("tests_passed") and payload.get("health_passed") else "failed",
                        reward=reward, cost=1.0, detail={"evidence": str(payload.get("evidence", ""))[:600]},
                    )
                elif event in {"propose", "shadow_failed", "promote", "rollback"}:
                    self.store.record_event(
                        event,
                        improvement_id=str(payload.get("improvement_id", "")),
                        name=str(payload.get("name", "")),
                        kind=str(payload.get("kind", "")),
                        outcome=str(payload.get("outcome", "")),
                        reward=EVENT_REWARD.get(event, 0.0),
                        cost=1.0 if event == "promote" else 0.0,
                        detail=payload.get("detail"),
                    )
            except Exception:
                pass  # Recording must never break the improvement pipeline.
        return listener

    # ── Dreaming (the meta loop) ─────────────────────────────────────────────

    def active_policy(self) -> dict[str, Any]:
        artifact = getattr(self.registry, "runtime_artifact", None)
        if callable(artifact):
            try:
                active = artifact(POLICY_ARTIFACT_NAME)
            except Exception:
                active = None
            if active and active.get("kind") == "config":
                try:
                    normalized = PolicyConfig.normalize(json.loads(str(active.get("content", ""))))
                except (TypeError, ValueError, json.JSONDecodeError):
                    normalized = None
                if normalized:
                    return normalized
        return dict(DEFAULT_POLICY)

    def _grid_candidates(self, baseline: dict[str, Any], count: int, cycle_index: int) -> list[dict[str, Any]]:
        """Deterministic policy variants so dreaming works fully offline."""
        grids = [
            {"propose_after_occurrences": [2, 3, 4, 5]},
            {"max_open_candidates": [2, 3, 5]},
            {"stop_on_shadow_failure": [True, False]},
            {"retry_backoff_factor": [1.0, 2.0]},
        ]
        variants: list[dict[str, Any]] = []
        for offset in range(len(grids)):
            grid = grids[(cycle_index + offset) % len(grids)]
            field = next(iter(grid))
            for value in grid[field]:
                if value == baseline.get(field):
                    continue
                candidate = {**baseline, field: value}
                normalized = PolicyConfig.normalize(candidate)
                if normalized and normalized not in variants:
                    variants.append(normalized)
                    break
            if len(variants) >= count:
                break
        return variants[:count]

    def _llm_candidates(self, baseline: dict[str, Any], stats: dict[str, Any], count: int) -> list[dict[str, Any]]:
        if self.summarizer is None or count <= 0:
            return []
        prompt = (
            "Du optimierst die Explorations-Policy eines lokalen Selbstverbesserungs-Loop.\n"
            f"Aktuelle Policy (JSON): {_canonical(baseline)}\n"
            f"Replay-Statistik (JSON): {_canonical(stats)}\n\n"
            "Schlage bis zu zwei verbesserte Varianten vor. Antworte NUR mit einem JSON-Objekt:\n"
            '{"candidates": [{"propose_after_occurrences": 1-20, "max_open_candidates": 1-25, '
            '"retry_backoff_factor": 1.0-10.0, "kind_preference": ["prompt"|"config"|"skill"|"runbook"], '
            '"stop_on_shadow_failure": true|false}]}\n'
            "Erlaubte Schlüssel: propose_after_occurrences, max_open_candidates, retry_backoff_factor, "
            "kind_preference, stop_on_shadow_failure. Keine anderen Schlüssel, kein Text."
        )
        try:
            response = self.summarizer(prompt)
        except Exception:
            return []
        match = re.search(r"\{.*\}", str(response or ""), re.DOTALL)
        if not match:
            return []
        try:
            parsed = json.loads(match.group(0))
        except (ValueError, json.JSONDecodeError):
            return []
        candidates: list[dict[str, Any]] = []
        for raw in (parsed.get("candidates") if isinstance(parsed, dict) else None) or []:
            normalized = PolicyConfig.normalize(raw)
            if normalized and normalized not in candidates:
                candidates.append(normalized)
            if len(candidates) >= count:
                break
        return candidates

    def run_cycle(self, max_candidates: int = 3, min_pool: int = 3) -> dict[str, Any]:
        """One bounded dream cycle: replay, compare, propose the winner."""
        started_at = _now()
        cycle_id = uuid.uuid4().hex

        def finish(status: str, reason: str = "", **fields: Any) -> dict[str, Any]:
            result = {"status": status, "reason": reason, "cycle_id": cycle_id, **fields}
            try:
                self.store.record_cycle(
                    cycle_id, started_at, status, reason,
                    pool_size=int(fields.get("pool_size", 0)),
                    candidates=int(fields.get("candidates", 0)),
                    winner_policy=fields.get("winner", {}).get("policy") if fields.get("winner") else None,
                    winner_score=fields.get("winner", {}).get("score") if fields.get("winner") else None,
                    proposal_id=str(fields.get("proposal_id", "") or ""),
                    evaluations=fields.get("evaluations"),
                )
            except Exception:
                pass
            return result

        if not dream_enabled():
            return finish("skipped", "MICA_DREAM_RSI_ENABLED is off")
        if self.emergency_stopped():
            return finish("skipped", "Emergency stop is active")
        baseline = self.active_policy()
        trees = self.store.trees()
        pool_size = len(trees)
        if pool_size < min_pool:
            return finish("skipped", f"pool below minimum ({pool_size} < {min_pool})", pool_size=pool_size)
        open_candidates = self._open_candidate_count()
        if open_candidates >= baseline["max_open_candidates"]:
            return finish(
                "skipped", f"open candidates at policy limit ({open_candidates})",
                pool_size=pool_size,
            )

        candidate_budget = max(1, min(int(max_candidates), 5))
        candidates = [("baseline", baseline)]
        stats = self.simulator.replay(trees, baseline)
        for variant in self._grid_candidates(baseline, candidate_budget - 1, len(trees)):
            candidates.append(("heuristic", variant))
        llm_variants = self._llm_candidates(baseline, stats, max(0, candidate_budget - len(candidates)))
        for variant in llm_variants:
            candidates.append(("llm", variant))

        evaluations: list[dict[str, Any]] = []
        for source, policy in candidates:
            replay = self.simulator.replay(trees, policy)
            evaluations.append({"policy": policy, "source": source, **replay})
        evaluations.sort(key=lambda item: (-item["score"], _canonical(item["policy"])))

        if self.scorer is not None and len(evaluations) > 1:
            try:
                reranked = self.scorer.rerank(evaluations)
                if reranked:
                    evaluations = reranked
            except Exception:
                pass

        winner = evaluations[0]
        improved = winner["score"] > evaluations[-1]["score"] if len(evaluations) > 1 else False
        proposal_id = ""
        if winner["policy"] != baseline:
            evidence = (
                f"Dream-RSI Replay: score={winner['score']} baseline_score="
                f"{next((item['score'] for item in evaluations if item['policy'] == baseline), None)} "
                f"pool={pool_size} branches={winner['branch_count']} "
                f"wasted_fraction={winner['wasted_fraction']} source={winner['source']}"
            )
            try:
                proposal = self.registry.propose(
                    POLICY_ARTIFACT_NAME, "config", _canonical(winner["policy"]), evidence,
                )
                proposal_id = str(proposal.get("id", ""))
            except (ValueError, RuntimeError) as error:
                return finish(
                    "failed", f"proposal rejected: {error}",
                    pool_size=pool_size, candidates=len(candidates), winner=winner,
                    evaluations=evaluations,
                )
        return finish(
            "completed",
            "winner matches baseline; no proposal needed" if not proposal_id else "policy proposed",
            pool_size=pool_size, candidates=len(candidates), winner=winner,
            proposal_id=proposal_id, evaluations=evaluations,
        )

    def _open_candidate_count(self) -> int:
        list_fn = getattr(self.registry, "list", None)
        if not callable(list_fn):
            try:
                return self.store.open_candidate_count()
            except Exception:
                return 0
        try:
            return sum(1 for item in list_fn() if item.get("status") in {"proposed", "validated"})
        except Exception:
            return 0

    def state(self) -> dict[str, Any]:
        trees = self.store.trees()
        return {
            "enabled": dream_enabled(),
            "policy_artifact": POLICY_ARTIFACT_NAME,
            "active_policy": self.active_policy(),
            "pool_size": len(trees),
            "node_count": sum(len(tree) for tree in trees),
            "open_candidates": self._open_candidate_count(),
            "last_cycles": self.store.cycles(5),
        }


def attach_dream_rsi(
    registry: Any, brain: Any, db_path: str | Path | None = None,
    summarizer: Callable[[str], str] | None = None,
    emergency_stopped: Callable[[], bool] | None = None,
    scorer: Any = None,
) -> DreamRSIEngine:
    """Create the engine, hook it into the registry, and return it.

    The registry stays decoupled: it only knows an optional ``on_event``
    callback. Attaching here means both the API process and the scheduler
    process can record lifecycle events into the same discovery store.
    """
    engine = DreamRSIEngine(
        DreamTreeStore(db_path), registry, brain, summarizer=summarizer,
        scorer=scorer, emergency_stopped=emergency_stopped,
    )
    registry.on_event = engine.build_event_listener()  # type: ignore[attr-defined]
    registry._dream_engine = engine  # type: ignore[attr-defined]
    return engine


def tag_improvement_signature(registry: Any, improvement_id: str, error_signature: str) -> None:
    """Best-effort linkage of an improvement signal signature to its tree."""
    engine = getattr(registry, "_dream_engine", None)
    if engine is not None:
        try:
            engine.store.tag_tree(improvement_id, error_signature)
        except Exception:
            pass
