"""Native Windows action boundary for MICA Phase 0.

Bind this application to loopback only and publish it through the companion
mTLS reverse proxy.  Requests select an exact capability; they can never name
a Python module, function, executable, or shell command.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from typing import Any
import uuid

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from desktop.core.action_adapters import execution_availability
from desktop.core.windows_alerts import notify_critical
from backend.services.common.capabilities import (
    RISK_READ,
    capability_for,
)


PROGRAM_DATA = Path(os.getenv("PROGRAMDATA", r"C:\ProgramData")) / "Mica"
CONFIG_PATH = Path(os.getenv("MICA_WINDOWS_AGENT_CONFIG", str(PROGRAM_DATA / "windows-host-agent.json")))
REPLAY_DB = Path(os.getenv("MICA_WINDOWS_AGENT_REPLAY_DB", str(PROGRAM_DATA / "windows-host-replay.sqlite3")))
STOP_PATH = Path(os.getenv("MICA_WINDOWS_AGENT_STOP_STATE", str(PROGRAM_DATA / "EMERGENCY_STOP")))
LEGACY_STOP_PATH = PROGRAM_DATA / "EMERGENCY_STOP.json"
MAX_TTL_SECONDS = max(30, min(int(os.getenv("MICA_WINDOWS_AGENT_MAX_TTL_SECONDS", "300")), 900))
MAX_INPUT_BYTES = 256 * 1024
_LOCK = threading.RLock()
_ACTIVE: set[subprocess.Popen[str]] = set()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def _config() -> dict[str, Any]:
    try:
        return _read_json(CONFIG_PATH)
    except (OSError, ValueError, json.JSONDecodeError):
        return {"allowed_actions": [], "trusted_broker_subject": "", "allow_broker_resume": False}


def _read_stop() -> bool:
    source = STOP_PATH
    if not source.exists() and "MICA_WINDOWS_AGENT_STOP_STATE" not in os.environ and LEGACY_STOP_PATH.exists():
        source = LEGACY_STOP_PATH
    if not source.exists():
        return False
    try:
        return bool(_read_json(source).get("active", True))
    except (OSError, ValueError, json.JSONDecodeError):
        return True


def _write_stop(active: bool) -> None:
    STOP_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STOP_PATH.with_name(f".{STOP_PATH.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps({"active": active, "updated_at": datetime.now(UTC).isoformat()}, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, STOP_PATH)


_STOPPED = _read_stop()
if _STOPPED and not STOP_PATH.exists():
    # Preserve a stop created by pre-Phase-0 builds under the exact durable
    # marker name. Failure is safe: _STOPPED remains true in memory.
    try:
        _write_stop(True)
    except OSError:
        pass


def _authenticate(verified: str | None, subject: str | None) -> dict[str, Any]:
    config = _config()
    if verified != "SUCCESS":
        raise HTTPException(401, "A mutually authenticated TLS client certificate is required")
    if not subject or subject != config.get("trusted_broker_subject"):
        raise HTTPException(403, "Untrusted broker certificate subject")
    return config


def _claim_request(request_id: str) -> bool:
    REPLAY_DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(REPLAY_DB, timeout=5)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS requests (request_id TEXT PRIMARY KEY, used_at TEXT NOT NULL)"
        )
        try:
            connection.execute(
                "INSERT INTO requests VALUES (?, ?)",
                (request_id, datetime.now(UTC).isoformat()),
            )
            connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False
    finally:
        connection.close()


class ScopedRequest(BaseModel):
    request_id: str = Field(min_length=16, max_length=128)
    scope: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    params: dict[str, Any] = Field(default_factory=dict, max_length=64)
    approval_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    expires_at: str

    @field_validator("request_id")
    @classmethod
    def valid_request_id(cls, value: str) -> str:
        try:
            uuid.UUID(hex=value)
        except ValueError as error:
            raise ValueError("request_id must be a UUID") from error
        return value

    @field_validator("expires_at")
    @classmethod
    def valid_expiry(cls, value: str) -> str:
        try:
            expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("expires_at must be ISO-8601") from error
        if expiry.tzinfo is None:
            raise ValueError("expires_at must include a timezone")
        now = datetime.now(UTC)
        expiry = expiry.astimezone(UTC)
        if expiry <= now or expiry > now + timedelta(seconds=MAX_TTL_SECONDS):
            raise ValueError("expires_at is outside the permitted lifetime")
        return value


class StopRequest(BaseModel):
    active: bool = True


def _runner_command() -> list[str]:
    return [sys.executable, "-m", "backend.windows_host_agent.runner"]


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10, check=False, shell=False, startupinfo=startupinfo,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        process.terminate()


def _run_action(action: str, params: dict[str, Any], timeout: int) -> dict[str, Any]:
    payload = json.dumps({"action": action, "params": params}, ensure_ascii=False, allow_nan=False)
    if len(payload.encode("utf-8")) > MAX_INPUT_BYTES:
        raise HTTPException(413, "Action input exceeds 256 KiB")
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    try:
        process = subprocess.Popen(
            _runner_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", shell=False, startupinfo=startupinfo,
            creationflags=creationflags,
        )
    except OSError as error:
        raise HTTPException(503, "Windows action runner could not start") from error
    with _LOCK:
        if _STOPPED:
            _terminate_process_tree(process)
            raise HTTPException(503, "Emergency stop is active")
        _ACTIVE.add(process)
    try:
        stdout, stderr = process.communicate(payload, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        _terminate_process_tree(process)
        process.communicate()
        raise HTTPException(504, "Windows action timed out") from error
    finally:
        with _LOCK:
            _ACTIVE.discard(process)
    if len(stdout.encode("utf-8", errors="replace")) > 1024 * 1024:
        raise HTTPException(502, "Windows action output exceeded 1 MiB")
    try:
        result = json.loads(stdout)
    except (ValueError, json.JSONDecodeError) as error:
        raise HTTPException(502, "Windows action returned invalid JSON") from error
    if process.returncode or not isinstance(result, dict) or not result.get("ok"):
        message = result.get("error") if isinstance(result, dict) else None
        raise HTTPException(502, str(message or stderr or "Windows action failed")[-500:])
    return result


app = FastAPI(title="MICA Windows host agent", version="0.1.0")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "stopped" if _STOPPED else "ok",
        "authority": "allowlisted-mtls-subprocess-only",
        "configured": CONFIG_PATH.is_file(),
        "active_processes": len(_ACTIVE),
    }


@app.post("/v1/emergency-stop")
def emergency_stop(
    request: StopRequest,
    x_client_cert_verified: str | None = Header(default=None),
    x_client_cert_subject: str | None = Header(default=None),
) -> dict[str, Any]:
    global _STOPPED
    config = _authenticate(x_client_cert_verified, x_client_cert_subject)
    if not request.active and not bool(config.get("allow_broker_resume", False)):
        raise HTTPException(403, "Remote resume is disabled; perform the local recovery checklist")
    terminated = 0
    with _LOCK:
        if request.active:
            _STOPPED = True
            for process in list(_ACTIVE):
                if process.poll() is None:
                    _terminate_process_tree(process)
                    terminated += 1
            try:
                _write_stop(True)
            except OSError as error:
                raise HTTPException(503, "Stop is active but could not be persisted") from error
        else:
            try:
                _write_stop(False)
            except OSError as error:
                raise HTTPException(503, "Stop remains active because resume was not persisted") from error
            _STOPPED = False
    return {"active": request.active, "terminated_processes": terminated}


@app.post("/v1/execute")
def execute(
    request: ScopedRequest,
    x_client_cert_verified: str | None = Header(default=None),
    x_client_cert_subject: str | None = Header(default=None),
) -> dict[str, Any]:
    config = _authenticate(x_client_cert_verified, x_client_cert_subject)
    if _STOPPED:
        raise HTTPException(503, "Emergency stop is active")
    manifest = capability_for(request.scope)
    if manifest is None:
        raise HTTPException(404, "Unknown Phase-0 capability")
    allowed = set(config.get("allowed_actions", []))
    if request.scope not in allowed and manifest.module not in allowed:
        raise HTTPException(403, "Capability is not allowlisted on this Windows host")
    available, reason = execution_availability(request.scope, request.params)
    if not available:
        raise HTTPException(409, reason)
    if manifest.risk_for(request.params) != RISK_READ and not request.approval_id:
        raise HTTPException(403, "A parameter-bound broker approval is required")
    if not _claim_request(request.request_id):
        raise HTTPException(409, "Replayed request id")
    try:
        result = _run_action(request.scope, request.params, manifest.timeout_seconds)
    except HTTPException as error:
        if error.status_code >= 500:
            notify_critical(f"windows_host_http_{error.status_code}")
        raise
    return {"request_id": request.request_id, "scope": request.scope, **result}
