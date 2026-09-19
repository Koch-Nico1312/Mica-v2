"""Minimal, separately deployed MICA host agent.

Run this only behind a mutually authenticated TLS reverse proxy.  It accepts
an authenticated broker identity, a one-use request id and a preconfigured
scope; it never accepts shell text, Docker commands or arbitrary file paths.
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
import subprocess
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator


CONFIG_PATH = Path(os.getenv("MICA_HOST_AGENT_CONFIG", "/data/host-agent/config.json"))
REPLAY_DB = Path(os.getenv("MICA_HOST_AGENT_REPLAY_DB", "/data/host-agent/replay.sqlite3"))
STOP_STATE_PATH = Path(os.getenv("MICA_HOST_AGENT_STOP_STATE", "/data/host-agent/emergency-stop.json"))
MAX_REQUEST_TTL_SECONDS = max(30, min(int(os.getenv("MICA_HOST_AGENT_MAX_REQUEST_TTL_SECONDS", "300")), 900))
_PROCESS_LOCK = threading.Lock()
_ACTIVE_PROCESSES: set[subprocess.Popen[str]] = set()


def _read_emergency_stop() -> bool:
    try:
        payload = json.loads(STOP_STATE_PATH.read_text(encoding="utf-8"))
        return bool(payload.get("active")) if isinstance(payload, dict) else True
    except FileNotFoundError:
        return False
    except (OSError, ValueError, json.JSONDecodeError):
        # A damaged marker fails closed until a local mTLS-authenticated
        # administrator explicitly repairs and clears it.
        return True


def _persist_emergency_stop(active: bool) -> None:
    STOP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STOP_STATE_PATH.with_name(f".{STOP_STATE_PATH.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps({"active": active, "updated_at": datetime.now(UTC).isoformat()}, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, STOP_STATE_PATH)


_EMERGENCY_STOPPED = _read_emergency_stop()


def _config() -> dict[str, Any]:
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(config, dict):
            return config
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return {"allowed_scopes": [], "trusted_broker_subject": ""}


def _mark_request_used(request_id: str) -> bool:
    REPLAY_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(REPLAY_DB)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, used_at TEXT NOT NULL)")
        try:
            conn.execute("INSERT INTO requests VALUES (?, ?)", (request_id, datetime.now(UTC).isoformat()))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
    finally:
        conn.close()


class ScopedRequest(BaseModel):
    request_id: str = Field(min_length=16, max_length=128)
    scope: str = Field(pattern=r"^[a-z]+(?:\.[a-z_]+)+$")
    params: dict[str, Any] = Field(default_factory=dict)
    approval_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    expires_at: str

    @field_validator("request_id")
    @classmethod
    def request_id_must_be_uuid(cls, value: str) -> str:
        try:
            uuid.UUID(hex=value)
        except ValueError as error:
            raise ValueError("request_id must be a UUID") from error
        return value

    @field_validator("expires_at")
    @classmethod
    def expiry_must_be_soon_and_timezone_aware(cls, value: str) -> str:
        try:
            expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("expires_at must be an ISO-8601 timestamp") from error
        if expiry.tzinfo is None:
            raise ValueError("expires_at must include a timezone")
        now = datetime.now(UTC)
        expiry = expiry.astimezone(UTC)
        if expiry <= now or expiry > now + timedelta(seconds=MAX_REQUEST_TTL_SECONDS):
            raise ValueError("expires_at is outside the permitted request lifetime")
        return value


app = FastAPI(title="MICA host agent", version="0.1.0")


def _authenticate(client_verified: str | None, client_subject: str | None) -> None:
    config = _config()
    if client_verified != "SUCCESS":
        raise HTTPException(401, "A mutually authenticated TLS client certificate is required")
    if not client_subject or client_subject != config.get("trusted_broker_subject"):
        raise HTTPException(403, "Untrusted broker certificate subject")


def _allowed_path(raw_path: str) -> Path:
    root = Path(_config().get("files_root", "/data")).resolve()
    candidate = Path(raw_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise HTTPException(403, "Path is outside the configured host-agent root") from error
    return candidate


def _run_argv(arguments: list[str], *, label: str, timeout: int = 45) -> str:
    """Run an operator-configured argv without a shell and track it for stop."""
    try:
        process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        with _PROCESS_LOCK:
            if _EMERGENCY_STOPPED:
                process.terminate()
                raise HTTPException(503, "Emergency stop is active on the host agent")
            _ACTIVE_PROCESSES.add(process)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        finally:
            with _PROCESS_LOCK:
                _ACTIVE_PROCESSES.discard(process)
    except (OSError, subprocess.TimeoutExpired) as error:
        if "process" in locals() and process.poll() is None:
            process.kill()
        raise HTTPException(503, f"{label} host command is unavailable") from error
    if process.returncode:
        raise HTTPException(502, (stderr or f"{label} command failed")[-500:])
    return stdout[-16000:]


def _docker(arguments: list[str]) -> str:
    """Run a fixed Docker argv without ever interpreting model text as shell."""
    return _run_argv(["docker", *arguments], label="Docker")


def _configured_argv(group: str, name: str, operation: str | None = None) -> list[str]:
    """Resolve a named operator-owned command; request data never becomes argv."""
    configured = _config().get(group, {})
    if not isinstance(configured, dict) or name not in configured:
        raise HTTPException(403, "Named host action is not allowlisted")
    entry: Any = configured[name]
    if operation is not None:
        if not isinstance(entry, dict) or operation not in entry:
            raise HTTPException(403, "Named host action state is not allowlisted")
        entry = entry[operation]
    if (
        not isinstance(entry, list) or not 1 <= len(entry) <= 32
        or any(not isinstance(part, str) or not part or len(part) > 512 or "\x00" in part for part in entry)
    ):
        raise HTTPException(503, "Configured host action argv is invalid")
    return list(entry)


def _configured_container(value: Any) -> str:
    name = str(value or "").strip()
    if not name or name not in set(_config().get("allowed_containers", [])):
        raise HTTPException(403, "Container is not allowlisted on this host")
    return name


def _shadow_improvement(improvement_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[a-f0-9]{32}", improvement_id):
        raise HTTPException(422, "Invalid improvement id")
    root = Path(_config().get("improvement_root", "/data/improvement-workspace/worktrees")).resolve()
    candidate = (root / improvement_id).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise HTTPException(403, "Improvement candidate is outside the configured root") from error
    try:
        manifest = json.loads((candidate / "shadow.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise HTTPException(422, "Candidate has no valid shadow manifest") from error
    if manifest.get("id") != improvement_id or not (candidate / "Dockerfile").is_file():
        raise HTTPException(422, "Candidate manifest does not match the request")
    artifact_relative = str(manifest.get("artifact", ""))
    artifact = (candidate / artifact_relative).resolve()
    try:
        artifact.relative_to(candidate)
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    except (OSError, ValueError) as error:
        raise HTTPException(422, "Candidate artifact is outside the worktree or unreadable") from error
    if digest != manifest.get("artifact_sha256"):
        raise HTTPException(422, "Candidate artifact checksum does not match its manifest")
    tag = f"mica-shadow-{improvement_id[:12]}"
    container = f"{tag}-health"
    _docker([
        "build", "--pull=false", "--network=none",
        "--label", f"mica.improvement.id={improvement_id}",
        "--label", f"mica.improvement.kind={manifest.get('kind', '')}",
        "--label", f"mica.improvement.sha256={digest}",
        "-t", tag, str(candidate),
    ])
    _docker([
        "run", "-d", "--name", container, "--network=none", "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--memory=256m", "--pids-limit=64",
        tag, "sh", "-c", "sleep 20",
    ])
    health = "starting"
    try:
        for _attempt in range(6):
            time.sleep(2)
            health = _docker(["inspect", "--format", "{{.State.Health.Status}}", container]).strip()
            if health in {"healthy", "unhealthy"}:
                break
    finally:
        try:
            _docker(["rm", "-f", container])
        except HTTPException:
            pass
    if health != "healthy":
        raise HTTPException(422, f"Shadow healthcheck did not pass: {health}")
    return {"tests_passed": True, "health_passed": True, "image": tag, "isolated": True}


def _invoke_active_improvement(improvement_id: str, payload: Any) -> dict[str, Any]:
    """Run only a currently active code artifact in its proven shadow image."""
    if not re.fullmatch(r"[a-f0-9]{32}", improvement_id):
        raise HTTPException(422, "Invalid improvement id")
    if not isinstance(payload, dict) or len(payload) > 64:
        raise HTTPException(422, "Improvement payload must be a bounded JSON object")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 65536:
        raise HTTPException(413, "Improvement payload exceeds 64 KiB")

    runtime_root = Path(
        _config().get("improvement_runtime_root", "/data/improvement-workspace/runtime")
    ).resolve()
    try:
        state = json.loads((runtime_root / "active.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise HTTPException(409, "No active improvement runtime manifest is available") from error
    artifacts = state.get("artifacts", []) if isinstance(state, dict) else []
    active = next(
        (
            item for item in artifacts
            if isinstance(item, dict) and item.get("id") == improvement_id
            and item.get("kind") == "code" and item.get("execution") == "isolated-container-only"
        ),
        None,
    )
    if not active:
        raise HTTPException(403, "Improvement is not the currently active isolated code revision")

    tag = f"mica-shadow-{improvement_id[:12]}"
    expected_label = f"{improvement_id}\t{active.get('sha256', '')}"
    labels = _docker([
        "image", "inspect", "--format",
        '{{ index .Config.Labels "mica.improvement.id" }}\t{{ index .Config.Labels "mica.improvement.sha256" }}',
        tag,
    ]).strip()
    if labels != expected_label:
        raise HTTPException(409, "Validated improvement image identity no longer matches the active manifest")

    output = _docker([
        "run", "--rm", "--network=none", "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--memory=128m", "--pids-limit=32",
        tag, "python", "/shadow/runner.py", encoded,
    ])
    try:
        result = json.loads(output.strip().splitlines()[-1])
    except (IndexError, ValueError, json.JSONDecodeError) as error:
        raise HTTPException(502, "Active improvement returned invalid JSON") from error
    return {"improvement_id": improvement_id, "isolated": True, "result": result}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "stopped" if _EMERGENCY_STOPPED else "ok", "authority": "scoped-mtls-only"}


@app.post("/v1/emergency-stop")
def emergency_stop(
    payload: dict[str, bool],
    x_client_cert_verified: str | None = Header(default=None),
    x_client_cert_subject: str | None = Header(default=None),
) -> dict[str, Any]:
    global _EMERGENCY_STOPPED
    _authenticate(x_client_cert_verified, x_client_cert_subject)
    active = bool(payload.get("active", True))
    terminated = 0
    with _PROCESS_LOCK:
        if active:
            # Stop immediately, then persist before reporting success.
            _EMERGENCY_STOPPED = True
            for process in list(_ACTIVE_PROCESSES):
                if process.poll() is None:
                    process.terminate()
                    terminated += 1
            try:
                _persist_emergency_stop(True)
            except OSError as error:
                raise HTTPException(503, "Emergency stop is active but could not be persisted") from error
        else:
            # Clear on disk first. A failed write leaves the in-memory guard
            # active, so a restart or I/O error cannot accidentally resume.
            try:
                _persist_emergency_stop(False)
            except OSError as error:
                raise HTTPException(503, "Emergency stop remains active because clearing was not persisted") from error
            _EMERGENCY_STOPPED = False
    return {"active": active, "terminated_processes": terminated}


@app.post("/v1/execute")
def execute(
    request: ScopedRequest,
    x_client_cert_verified: str | None = Header(default=None),
    x_client_cert_subject: str | None = Header(default=None),
) -> dict[str, Any]:
    _authenticate(x_client_cert_verified, x_client_cert_subject)
    if _EMERGENCY_STOPPED:
        raise HTTPException(503, "Emergency stop is active on the host agent")
    config = _config()
    if request.scope not in set(config.get("allowed_scopes", [])):
        raise HTTPException(403, "Scope is not configured on this host")
    approval_required = request.scope in {
        "files.delete", "network.change", "docker.lifecycle", "system.admin",
        "improvement.invoke",
    } or (request.scope == "files.create" and bool(request.params.get("overwrite")))
    if approval_required and not request.approval_id:
        raise HTTPException(403, "A parameter-bound broker approval is required for this scope")
    if not _mark_request_used(request.request_id):
        raise HTTPException(409, "Replayed request id")

    if request.scope == "files.list":
        target = _allowed_path(str(request.params.get("path", config.get("files_root", "/data"))))
        if not target.is_dir():
            raise HTTPException(400, "Configured path is not a directory")
        return {"request_id": request.request_id, "scope": request.scope, "entries": [child.name for child in sorted(target.iterdir())[:200]]}

    if request.scope == "files.create":
        target = _allowed_path(str(request.params.get("path", "")))
        content = str(request.params.get("content", ""))
        if not target.name or len(content.encode("utf-8")) > 65536:
            raise HTTPException(422, "File path is missing or content exceeds 64 KiB")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            if bool(request.params.get("overwrite")):
                target.write_text(content, encoding="utf-8", errors="strict")
            else:
                with target.open("x", encoding="utf-8") as handle:
                    handle.write(content)
        except FileExistsError as error:
            raise HTTPException(409, "File already exists; an explicit overwrite approval is required") from error
        except OSError as error:
            raise HTTPException(503, "File could not be created") from error
        return {"request_id": request.request_id, "scope": request.scope, "path": str(target), "undo": "files.delete requires a new destructive approval"}

    if request.scope == "files.move":
        source = _allowed_path(str(request.params.get("from", "")))
        destination = _allowed_path(str(request.params.get("to", "")))
        if not source.is_file() or destination.exists():
            raise HTTPException(409, "Source must exist and destination must not exist")
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.replace(destination)
        except OSError as error:
            raise HTTPException(503, "File could not be moved") from error
        return {"request_id": request.request_id, "scope": request.scope, "from": str(source), "to": str(destination), "undo": {"from": str(destination), "to": str(source)}}

    if request.scope == "files.delete":
        raw_target = str(request.params.get("path", ""))
        if Path(raw_target).is_symlink():
            raise HTTPException(422, "Deleting symbolic links through the host agent is not supported")
        target = _allowed_path(raw_target)
        if not target.is_file():
            raise HTTPException(409, "Only an existing regular file can be moved to host-agent trash")
        trash_default = Path(config.get("files_root", "/data")) / ".mica-trash"
        trash_root = _allowed_path(str(config.get("trash_root", trash_default)))
        destination = trash_root / f"{uuid.uuid4().hex}-{target.name}"
        try:
            trash_root.mkdir(parents=True, exist_ok=True)
            target.replace(destination)
        except OSError as error:
            raise HTTPException(503, "File could not be moved to host-agent trash") from error
        return {
            "request_id": request.request_id, "scope": request.scope,
            "path": str(target), "trashed_to": str(destination),
            "recoverable": True,
            "undo": {"action": "files.move", "from": str(destination), "to": str(target)},
        }

    if request.scope == "network.change":
        if set(request.params) - {"profile", "state"}:
            raise HTTPException(422, "Network changes accept only an allowlisted profile and state")
        profile = str(request.params.get("profile", "")).strip()
        state = str(request.params.get("state", "")).strip().lower()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", profile) or state not in {"up", "down"}:
            raise HTTPException(422, "A valid network profile and up/down state are required")
        argv = _configured_argv("network_profiles", profile, state)
        output = _run_argv(argv, label="Network", timeout=60)
        return {
            "request_id": request.request_id, "scope": request.scope,
            "profile": profile, "state": state, "output": output,
            "undo": {"action": "network.change", "profile": profile, "state": "down" if state == "up" else "up"},
        }

    if request.scope == "system.admin":
        if set(request.params) != {"action"}:
            raise HTTPException(422, "System administration accepts one allowlisted action name")
        action = str(request.params.get("action", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", action):
            raise HTTPException(422, "A valid system administration action is required")
        output = _run_argv(_configured_argv("admin_actions", action), label="System", timeout=60)
        return {"request_id": request.request_id, "scope": request.scope, "action": action, "output": output}

    if request.scope == "system.status":
        try:
            import psutil
            load = psutil.getloadavg()[0] / max(1, psutil.cpu_count() or 1) * 100 if hasattr(psutil, "getloadavg") else 0.0
            return {
                "request_id": request.request_id, "scope": request.scope,
                "cpu_percent": psutil.cpu_percent(), "memory_percent": psutil.virtual_memory().percent,
                "load_percent": round(load, 2), "disk_percent": psutil.disk_usage("/").percent,
            }
        except Exception as error:
            raise HTTPException(503, f"Host metrics unavailable: {error}") from error

    if request.scope == "docker.status":
        output = _docker(["ps", "-a", "--format", "{{json .}}"])
        allowed = set(config.get("allowed_containers", []))
        containers = []
        for line in output.splitlines()[:200]:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = str(item.get("Names", ""))
            if name not in allowed:
                continue
            status = str(item.get("Status", ""))
            state = str(item.get("State", "")).lower()
            health = "unhealthy" if "unhealthy" in status.lower() else "healthy" if "healthy" in status.lower() else state
            restart_text = _docker(["inspect", "--format", "{{.RestartCount}}", name]).strip()
            try:
                restart_count = max(0, int(restart_text))
            except ValueError as error:
                raise HTTPException(503, "Docker restart count was not numeric") from error
            containers.append({"name": name, "status": status, "health": health, "running": state == "running", "restart_count": restart_count})
        return {"request_id": request.request_id, "scope": request.scope, "containers": containers}

    if request.scope == "docker.lifecycle":
        operation = str(request.params.get("operation", "")).lower()
        if operation not in {"start", "stop", "restart"}:
            raise HTTPException(422, "Only start, stop, and restart are valid lifecycle operations")
        container = _configured_container(request.params.get("container"))
        output = _docker(["container", operation, container])
        return {"request_id": request.request_id, "scope": request.scope, "operation": operation, "container": container, "output": output}

    if request.scope == "improvement.shadow":
        result = _shadow_improvement(str(request.params.get("improvement_id", "")))
        return {"request_id": request.request_id, "scope": request.scope, **result}

    if request.scope == "improvement.invoke":
        result = _invoke_active_improvement(
            str(request.params.get("improvement_id", "")), request.params.get("payload", {}),
        )
        return {"request_id": request.request_id, "scope": request.scope, **result}

    raise HTTPException(501, "The scope is configured but has no safe host handler")
