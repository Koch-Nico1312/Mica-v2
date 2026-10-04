from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from .brain import MarkdownBrain


class ImprovementRegistry:
    """Promote versioned, evidence-backed artifacts without granting authority.

    The improvement Git repository is deliberately separate from the MICA
    service checkout. Promotion creates an atomically published runtime
    manifest. Consumers can read artifact data, but this registry never
    imports or executes proposed code; policy, credentials, audit data and
    host-agent permissions remain outside the self-improvement boundary.
    """

    _process_locks: dict[str, threading.RLock] = {}
    _process_locks_guard = threading.Lock()
    _ALLOWED_KINDS = {"prompt", "skill", "code", "config", "runbook"}
    _EXTENSIONS = {"code": ".py", "config": ".json"}
    _PROTECTED_NAME_PARTS = {
        "approval", "audit", "capability", "credential", "host", "permission",
        "policy", "secret", "token", "password", "mtls", "certificate",
    }
    _PROTECTED_CONFIG_KEYS = _PROTECTED_NAME_PARTS | {
        "api_key", "apikey", "access_key", "private_key", "authorization", "bearer",
        "docker_socket", "docker_host", "allowed_scopes", "emergency_stop", "webhook_secret",
    }

    def __init__(self, path: str | Path, brain: MarkdownBrain):
        self.path, self.brain = Path(path), brain
        self.workspace = Path(os.getenv("IMPROVEMENT_WORKSPACE", str(self.path.parent / "improvement-workspace")))
        self.repository = self.workspace / "repository"
        self.worktrees = self.workspace / "worktrees"
        self.runtime = self.workspace / "runtime"
        self.generations = self.runtime / "generations"
        self.active_state_path = self.runtime / "active.json"
        self.lock_path = self.workspace / ".improvements.lock"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.workspace.mkdir(parents=True, exist_ok=True)
        with self._locked():
            self._init_repository()
            self.runtime.mkdir(parents=True, exist_ok=True)
            self.generations.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                self._create_schema(conn)
            if not self.active_state_path.exists():
                self._publish_state(self._empty_runtime_state())

    # Optional, externally assigned lifecycle listener (Dream-RSI discovery
    # tree). The registry stays decoupled: it never imports the listener's
    # module and a failing listener never affects the pipeline.
    on_event: Any = None

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        listener = getattr(self, "on_event", None)
        if not callable(listener):
            return
        try:
            listener(event, payload)
        except Exception:
            pass

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _sha256(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @classmethod
    def _thread_lock(cls, path: Path) -> threading.RLock:
        key = str(path.resolve())
        with cls._process_locks_guard:
            return cls._process_locks.setdefault(key, threading.RLock())

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Serialize Git and SQLite transitions across threads and processes."""
        process_lock = self._thread_lock(self.lock_path)
        with process_lock:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self.lock_path.open("a+b") as stream:
                stream.seek(0)
                if not stream.read(1):
                    stream.seek(0)
                    stream.write(b"0")
                    stream.flush()
                deadline = time.monotonic() + 30
                if os.name == "nt":
                    import msvcrt

                    while True:
                        try:
                            stream.seek(0)
                            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                            break
                        except OSError:
                            if time.monotonic() >= deadline:
                                raise TimeoutError("Timed out waiting for the improvement workflow lock")
                            time.sleep(0.05)
                    try:
                        yield
                    finally:
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    while True:
                        try:
                            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                            break
                        except BlockingIOError:
                            if time.monotonic() >= deadline:
                                raise TimeoutError("Timed out waiting for the improvement workflow lock")
                            time.sleep(0.05)
                    try:
                        yield
                    finally:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
        finally:
            connection.close()

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS improvements ("
            "id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL, "
            "status TEXT NOT NULL, parent_id TEXT, test_evidence TEXT, health_evidence TEXT, "
            "created_at TEXT NOT NULL, activated_at TEXT)"
        )
        self._ensure_column(conn, "branch", "TEXT")
        self._ensure_column(conn, "commit_sha", "TEXT")
        self._ensure_column(conn, "candidate_path", "TEXT")
        self._ensure_column(conn, "artifact_path", "TEXT")
        self._ensure_column(conn, "artifact_sha256", "TEXT")
        self._ensure_column(conn, "failure_reason", "TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_improvements_one_active "
            "ON improvements(name) WHERE status = 'active'"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_improvements_status_name ON improvements(status, name)")

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, name: str, declaration: str) -> None:
        if name not in {row[1] for row in conn.execute("PRAGMA table_info(improvements)")}:
            conn.execute(f"ALTER TABLE improvements ADD COLUMN {name} {declaration}")

    @staticmethod
    def _git(cwd: Path, *arguments: str) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(cwd), *arguments], capture_output=True, text=True,
                encoding="utf-8", errors="strict", timeout=30, check=False,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except (OSError, UnicodeError, subprocess.TimeoutExpired) as error:
            raise RuntimeError("Git is required for the isolated improvement workflow") from error
        if result.returncode:
            raise RuntimeError((result.stderr or "Git improvement operation failed")[-1000:])
        return result.stdout.strip()

    def _init_repository(self) -> None:
        self.repository.mkdir(parents=True, exist_ok=True)
        self.worktrees.mkdir(parents=True, exist_ok=True)
        if not (self.repository / ".git").exists():
            self._git(self.repository, "init", "-b", "main")
            self._git(self.repository, "config", "user.name", "MICA Improvement Worker")
            self._git(self.repository, "config", "user.email", "mica@localhost")
            readme = self.repository / "README.md"
            readme.write_text("# MICA validated improvement artifacts\n", encoding="utf-8")
            self._git(self.repository, "add", "README.md")
            self._git(self.repository, "commit", "-m", "Initialize isolated improvement repository")

    @staticmethod
    def _slug(name: str) -> str:
        return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:80] or "candidate"

    @classmethod
    def _validate_candidate(cls, name: str, kind: str, content: str) -> None:
        words = set(re.findall(r"[a-z0-9]+", name.lower()))
        if words & cls._PROTECTED_NAME_PARTS:
            raise ValueError("Improvements may not target policy, secrets, audit or host-agent authority")
        if kind == "config":
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as error:
                raise ValueError("config improvements must contain valid JSON") from error
            if not isinstance(parsed, dict):
                raise ValueError("config improvements must be a JSON object")
            runtime_config = name.strip().lower() == "mica-runtime-config"
            runtime_keys = {"temperature", "chat_tokens", "voice_tokens"}
            if runtime_config and not set(parsed).issubset(runtime_keys):
                raise ValueError("mica-runtime-config contains a key outside the runtime allowlist")

            def inspect(value: Any, top_level: bool = False) -> None:
                if isinstance(value, dict):
                    for key, child in value.items():
                        normalized = str(key).lower().replace("-", "_")
                        if not (runtime_config and top_level and normalized in runtime_keys) and any(
                            part in normalized for part in cls._PROTECTED_CONFIG_KEYS
                        ):
                            raise ValueError("config improvements may not change policy, secrets or host permissions")
                        inspect(child)
                elif isinstance(value, list):
                    for child in value:
                        inspect(child)

            inspect(parsed, top_level=True)
        elif kind == "code":
            try:
                tree = ast.parse(content)
            except SyntaxError as error:
                raise ValueError("code improvements must be valid Python") from error
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    raise ValueError("code artifacts are data-only and may not import host capabilities")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {
                    "open", "exec", "eval", "compile", "__import__",
                }:
                    raise ValueError("code artifacts are sandbox-only and may not access or execute the host")
                if isinstance(node, (ast.Attribute, ast.Name)):
                    identifier = node.attr if isinstance(node, ast.Attribute) else node.id
                    if identifier.startswith("_"):
                        raise ValueError("code artifacts may not access private or interpreter attributes")
            entrypoints = [
                node for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"
            ]
            if len(entrypoints) != 1 or isinstance(entrypoints[0], ast.AsyncFunctionDef):
                raise ValueError("code improvements must define exactly one synchronous main(payload) function")
            entrypoint = entrypoints[0]
            if len(entrypoint.args.args) != 1 or entrypoint.args.vararg or entrypoint.args.kwarg:
                raise ValueError("code improvement main must accept exactly one payload argument")
            for statement in tree.body:
                if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
                    continue
                if not isinstance(statement, ast.FunctionDef):
                    raise ValueError("code improvements may contain only function definitions at module scope")

    def _create_candidate(self, improvement_id: str, name: str, kind: str, content: str) -> tuple[str, str, str, str, str]:
        branch = f"mica/improvement-{improvement_id[:12]}"
        candidate = self.worktrees / improvement_id
        self._git(self.repository, "worktree", "add", "-b", branch, str(candidate), "main")
        extension = self._EXTENSIONS.get(kind, ".md")
        artifact_relative = PurePosixPath("artifacts") / kind / f"{self._slug(name)}-{improvement_id[:12]}{extension}"
        artifact = candidate.joinpath(*artifact_relative.parts)
        artifact.parent.mkdir(parents=True, exist_ok=True)
        normalized_content = content.strip() + "\n"
        artifact.write_text(normalized_content, encoding="utf-8")
        artifact_sha256 = self._sha256(normalized_content)
        validator = candidate / "validate.py"
        validator.write_text(
            "import ast,json,pathlib\n"
            f"p=pathlib.Path({artifact_relative.as_posix()!r})\n"
            "data=p.read_text(encoding='utf-8')\n"
            f"kind={kind!r}\n"
            "assert data.strip()\n"
            "ast.parse(data) if kind=='code' else None\n"
            "json.loads(data) if kind=='config' else None\n"
            "print(json.dumps({'tests_passed':True,'health_passed':True,'artifact':str(p)}))\n",
            encoding="utf-8",
        )
        docker_command = '["python", "/shadow/validate.py"]'
        health_command = "python /shadow/validate.py"
        if kind == "code":
            runner = candidate / "runner.py"
            runner.write_text(
                "import json,pathlib,sys\n"
                f"artifact=pathlib.Path({artifact_relative.as_posix()!r})\n"
                "source=artifact.read_text(encoding='utf-8')\n"
                "safe={'abs':abs,'all':all,'any':any,'bool':bool,'dict':dict,'enumerate':enumerate,"
                "'float':float,'int':int,'len':len,'list':list,'max':max,'min':min,'range':range,"
                "'round':round,'sorted':sorted,'str':str,'sum':sum,'tuple':tuple,'zip':zip}\n"
                "scope={'__builtins__':safe}\n"
                "exec(compile(source,str(artifact),'exec'),scope,scope)\n"
                "payload=json.loads(sys.argv[1]) if len(sys.argv)>1 else {'healthcheck':True}\n"
                "assert isinstance(payload,dict)\n"
                "result=scope['main'](payload)\n"
                "print(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':')))\n",
                encoding="utf-8",
            )
            docker_command = '["python", "/shadow/runner.py", "{\\"healthcheck\\":true}"]'
            health_command = "python /shadow/runner.py '{\"healthcheck\":true}'"
        (candidate / "Dockerfile").write_text(
            "FROM python:3.12-alpine\nWORKDIR /shadow\nCOPY . /shadow\n"
            f"HEALTHCHECK --interval=2s --timeout=2s --retries=3 CMD {health_command} || exit 1\n"
            f"CMD {docker_command}\n",
            encoding="utf-8",
        )
        manifest = {
            "id": improvement_id, "kind": kind, "artifact": artifact_relative.as_posix(),
            "artifact_sha256": artifact_sha256, "branch": branch, "activation": "data-only",
        }
        (candidate / "shadow.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        add_paths = ["artifacts", "validate.py", "Dockerfile", "shadow.json"]
        if kind == "code":
            add_paths.append("runner.py")
        self._git(candidate, "add", *add_paths)
        self._git(candidate, "commit", "-m", f"Propose {kind}: {name[:80]}")
        return branch, self._git(candidate, "rev-parse", "HEAD"), str(candidate), artifact_relative.as_posix(), artifact_sha256

    def propose(self, name: str, kind: str, content: str, evidence: str) -> dict[str, str]:
        if kind not in self._ALLOWED_KINDS:
            raise ValueError("kind must be prompt, skill, code, config or runbook")
        if not name.strip() or not content.strip() or not evidence.strip():
            raise ValueError("name, content and evidence are required")
        self._validate_candidate(name, kind, content)
        entry = {
            "id": uuid.uuid4().hex, "name": name.strip()[:160], "kind": kind,
            "content": content.strip(), "status": "proposed", "created_at": self._now(),
        }
        try:
            with self._locked():
                with self._connect() as conn:
                    parent = conn.execute(
                        "SELECT id FROM improvements WHERE name = ? AND status = 'active'", (entry["name"],)
                    ).fetchone()
                entry["parent_id"] = parent[0] if parent else None
                branch, commit_sha, candidate_path, artifact_path, artifact_sha256 = self._create_candidate(
                    entry["id"], entry["name"], kind, entry["content"],
                )
                with self._connect() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(
                        "INSERT INTO improvements(id, name, kind, content, status, parent_id, test_evidence, "
                        "health_evidence, created_at, activated_at, branch, commit_sha, candidate_path, "
                        "artifact_path, artifact_sha256, failure_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (entry["id"], entry["name"], entry["kind"], entry["content"], entry["status"], entry["parent_id"],
                         None, None, entry["created_at"], None, branch, commit_sha, candidate_path,
                         artifact_path, artifact_sha256, None),
                    )
                    conn.execute("COMMIT")
        except (RuntimeError, TimeoutError) as error:
            raise ValueError(str(error)) from error
        self._emit("propose", {
            "improvement_id": entry["id"], "name": entry["name"], "kind": entry["kind"],
        })
        document = self.brain.write(
            "improvements", f"Vorschlag: {entry['name']}",
            f"Typ: `{kind}`\n\nEvidenz:\n{evidence.strip()}\n\nVorschlag:\n{content.strip()}",
            {"improvement_id": entry["id"], "status": "proposed", "parent_id": entry["parent_id"] or ""},
        )
        return {"id": entry["id"], "status": entry["status"], "brain_document": document["id"], "branch": branch, "commit_sha": commit_sha}

    def active(self, name: str) -> str | None:
        with self._locked(), self._connect() as conn:
            row = conn.execute("SELECT id FROM improvements WHERE name = ? AND status = 'active'", (name,)).fetchone()
        return row[0] if row else None

    def evaluate(self, improvement_id: str, tests_passed: bool, health_passed: bool, test_evidence: str, health_evidence: str) -> bool:
        if not (tests_passed and health_passed and test_evidence.strip() and health_evidence.strip()):
            self._emit("evaluate", {
                "improvement_id": improvement_id, "tests_passed": bool(tests_passed),
                "health_passed": bool(health_passed), "evidence": str(test_evidence)[:600],
            })
            return False
        with self._locked(), self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            result = conn.execute(
                "UPDATE improvements SET status = 'validated', test_evidence = ?, health_evidence = ? "
                "WHERE id = ? AND status = 'proposed'", (test_evidence[:4000], health_evidence[:4000], improvement_id),
            )
            conn.execute("COMMIT")
        self._emit("evaluate", {
            "improvement_id": improvement_id, "tests_passed": bool(tests_passed),
            "health_passed": bool(health_passed), "evidence": str(test_evidence)[:600],
        })
        return result.rowcount == 1

    @staticmethod
    def _row_to_artifact(row: tuple[Any, ...]) -> dict[str, str]:
        return {
            "id": str(row[0]), "name": str(row[1]), "kind": str(row[2]), "commit_sha": str(row[3]),
            "artifact_path": str(row[4]), "artifact_sha256": str(row[5]), "activated_at": str(row[6] or ""),
        }

    def _active_rows(self, conn: sqlite3.Connection, replacement: tuple[Any, ...] | None = None) -> list[dict[str, str]]:
        rows = conn.execute(
            "SELECT id, name, kind, commit_sha, artifact_path, artifact_sha256, activated_at "
            "FROM improvements WHERE status = 'active' ORDER BY name"
        ).fetchall()
        artifacts = [self._row_to_artifact(row) for row in rows]
        if replacement:
            candidate = self._row_to_artifact(replacement)
            artifacts = [artifact for artifact in artifacts if artifact["name"] != candidate["name"]]
            artifacts.append(candidate)
        return sorted(artifacts, key=lambda artifact: artifact["name"])

    def _empty_runtime_state(self) -> dict[str, Any]:
        return {"schema_version": 1, "generated_at": self._now(), "activation": "data-only", "artifacts": []}

    def _build_runtime_state(self, artifacts: list[dict[str, str]]) -> dict[str, Any]:
        generation = uuid.uuid4().hex
        generation_dir = self.generations / generation
        generation_dir.mkdir(parents=True, exist_ok=False)
        published: list[dict[str, str]] = []
        for artifact in artifacts:
            relative = PurePosixPath(artifact["artifact_path"])
            if relative.is_absolute() or ".." in relative.parts or relative.parts[:2] != ("artifacts", artifact["kind"]):
                raise RuntimeError("Stored improvement artifact path is invalid")
            content = self._git(self.repository, "show", f"{artifact['commit_sha']}:{relative.as_posix()}") + "\n"
            if self._sha256(content) != artifact["artifact_sha256"]:
                raise RuntimeError("Stored improvement artifact checksum does not match its immutable Git revision")
            runtime_relative = PurePosixPath("generations") / generation / "artifacts" / artifact["kind"] / f"{artifact['id']}{self._EXTENSIONS.get(artifact['kind'], '.md')}"
            destination = self.runtime.joinpath(*runtime_relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
            try:
                destination.chmod(0o444)
            except OSError:
                pass
            published.append({
                "id": artifact["id"], "name": artifact["name"], "kind": artifact["kind"],
                "path": runtime_relative.as_posix(), "sha256": artifact["artifact_sha256"],
                "commit_sha": artifact["commit_sha"], "activated_at": artifact["activated_at"],
                "execution": "isolated-container-only" if artifact["kind"] == "code" else "data-only",
            })
        return {
            "schema_version": 1, "generated_at": self._now(), "generation": generation,
            "activation": "data-only", "artifacts": published,
        }

    def _publish_state(self, state: dict[str, Any]) -> None:
        temporary = self.active_state_path.with_name(f".{self.active_state_path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, self.active_state_path)

    def _replace_status_and_publish(
        self,
        conn: sqlite3.Connection,
        deactivate_id: str | None,
        activate_id: str,
        state: dict[str, Any],
        deactivate_status: str = "superseded",
    ) -> bool:
        """Commit status first, then atomically publish; compensate on I/O failure."""
        now = self._now()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if deactivate_id:
                conn.execute(
                    "UPDATE improvements SET status = ? WHERE id = ? AND status = 'active'",
                    (deactivate_status, deactivate_id),
                )
            activated = conn.execute(
                "UPDATE improvements SET status = 'active', activated_at = ?, failure_reason = NULL "
                "WHERE id = ? AND status IN ('validated', 'superseded')", (now, activate_id),
            )
            if activated.rowcount != 1:
                conn.execute("ROLLBACK")
                return False
            conn.execute("COMMIT")
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            return False
        for artifact in state.get("artifacts", []):
            if artifact.get("id") == activate_id:
                artifact["activated_at"] = now
        try:
            self._publish_state(state)
            return True
        except OSError:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE improvements SET status = 'validated', activated_at = NULL WHERE id = ? AND status = 'active'", (activate_id,))
            if deactivate_id:
                conn.execute(
                    "UPDATE improvements SET status = 'active' WHERE id = ? AND status = ?",
                    (deactivate_id, deactivate_status),
                )
            conn.execute("COMMIT")
            return False

    def promote(self, improvement_id: str) -> bool:
        with self._locked(), self._connect() as conn:
            candidate = conn.execute(
                "SELECT id, name, kind, commit_sha, artifact_path, artifact_sha256, activated_at, branch "
                "FROM improvements WHERE id = ? AND status = 'validated'", (improvement_id,)
            ).fetchone()
            if not candidate:
                return False
            existing = conn.execute("SELECT id FROM improvements WHERE name = ? AND status = 'active'", (candidate[1],)).fetchone()
            try:
                self._git(self.repository, "merge", "--ff-only", str(candidate[7]))
                state = self._build_runtime_state(self._active_rows(conn, candidate[:7]))
            except (OSError, RuntimeError):
                return False
            promoted = self._replace_status_and_publish(conn, existing[0] if existing else None, str(candidate[0]), state)
            if promoted:
                self._emit("promote", {"improvement_id": str(candidate[0]), "name": candidate[1], "kind": candidate[2]})
            return promoted

    def rollback(self, name: str) -> bool:
        with self._locked(), self._connect() as conn:
            active = conn.execute("SELECT id FROM improvements WHERE name = ? AND status = 'active'", (name,)).fetchone()
            previous = conn.execute(
                "SELECT id, name, kind, commit_sha, artifact_path, artifact_sha256, activated_at "
                "FROM improvements WHERE name = ? AND status = 'superseded' ORDER BY activated_at DESC LIMIT 1", (name,),
            ).fetchone()
            if not active or not previous:
                return False
            try:
                state = self._build_runtime_state(self._active_rows(conn, previous))
            except (OSError, RuntimeError):
                return False
            rolled_back = self._replace_status_and_publish(conn, str(active[0]), str(previous[0]), state, "rolled_back")
            if rolled_back:
                self._emit("rollback", {"improvement_id": str(active[0]), "name": name})
            return rolled_back

    def record_shadow_failure(self, improvement_id: str, reason: str) -> bool:
        """Quarantine a failed candidate and restore the last known good state.

        The normal Shadow path calls this before promotion. The active branch
        additionally covers a later health failure reported by a deployment
        watcher: it rolls the active artifact back automatically when a prior
        active revision exists.
        """
        with self._locked(), self._connect() as conn:
            current = conn.execute(
                "SELECT id, name, status FROM improvements WHERE id = ?", (improvement_id,)
            ).fetchone()
            if not current:
                return False
            if current[2] == "active":
                previous = conn.execute(
                    "SELECT id, name, kind, commit_sha, artifact_path, artifact_sha256, activated_at "
                    "FROM improvements WHERE name = ? AND status = 'superseded' "
                    "ORDER BY activated_at DESC LIMIT 1", (current[1],),
                ).fetchone()
                if not previous:
                    # There is no previous safe revision to restore. Do not
                    # replace the only currently active runtime state.
                    return False
                try:
                    state = self._build_runtime_state(self._active_rows(conn, previous))
                except (OSError, RuntimeError):
                    return False
                restored = self._replace_status_and_publish(conn, str(current[0]), str(previous[0]), state, "rolled_back")
                if restored:
                    conn.execute("UPDATE improvements SET failure_reason = ? WHERE id = ?", (reason[:4000], current[0]))
                return restored
            if current[2] not in {"proposed", "validated"}:
                return False
            conn.execute("BEGIN IMMEDIATE")
            result = conn.execute(
                "UPDATE improvements SET status = 'shadow_failed', failure_reason = ? "
                "WHERE id = ? AND status IN ('proposed', 'validated')", (reason[:4000], improvement_id),
            )
            conn.execute("COMMIT")
            if result.rowcount == 1:
                self._emit("shadow_failed", {"improvement_id": improvement_id, "name": current[1], "detail": {"reason": reason[:300]}})
            if result.rowcount != 1:
                return False
            try:
                active = self._active_rows(conn)
                self._publish_state(self._build_runtime_state(active) if active else self._empty_runtime_state())
            except (OSError, RuntimeError):
                # The old pointer was never changed, so it remains the last known good state.
                return False
        return True

    def _read_runtime_state_unlocked(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.active_state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return self._empty_runtime_state()
        if not isinstance(raw, dict) or raw.get("schema_version") != 1 or not isinstance(raw.get("artifacts"), list):
            return self._empty_runtime_state()
        return raw

    def runtime_state(self) -> dict[str, Any]:
        with self._locked():
            return self._read_runtime_state_unlocked()

    def runtime_artifact(self, name: str) -> dict[str, Any] | None:
        """Return verified artifact data for a runtime consumer; never execute it."""
        with self._locked():
            state = self._read_runtime_state_unlocked()
            artifact = next((item for item in state["artifacts"] if item.get("name") == name), None)
            if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
                return None
            try:
                candidate = (self.runtime / artifact["path"]).resolve()
                candidate.relative_to(self.runtime.resolve())
                content = candidate.read_text(encoding="utf-8")
            except (OSError, ValueError):
                return None
            if self._sha256(content) != artifact.get("sha256"):
                return None
            return {**artifact, "content": content}

    def list(self, name: str | None = None) -> list[dict[str, Any]]:
        query = (
            "SELECT id, name, kind, status, parent_id, created_at, activated_at, branch, commit_sha, "
            "artifact_path, artifact_sha256, failure_reason FROM improvements"
        )
        values: tuple[str, ...] = ()
        if name:
            query += " WHERE name = ?"
            values = (name,)
        query += " ORDER BY created_at DESC"
        with self._locked(), self._connect() as conn:
            rows = conn.execute(query, values).fetchall()
        return [
            {"id": row[0], "name": row[1], "kind": row[2], "status": row[3], "parent_id": row[4],
             "created_at": row[5], "activated_at": row[6], "branch": row[7], "commit_sha": row[8],
             "artifact_path": row[9], "artifact_sha256": row[10], "failure_reason": row[11]}
            for row in rows
        ]

    def candidate_path(self, improvement_id: str) -> Path | None:
        with self._locked(), self._connect() as conn:
            row = conn.execute("SELECT candidate_path FROM improvements WHERE id = ?", (improvement_id,)).fetchone()
        return Path(row[0]) if row and row[0] else None
