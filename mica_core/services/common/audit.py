from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, TextIO


_SECRET_KEY_PARTS = (
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "authorization", "cookie", "private_key", "client_key",
)
_SENSITIVE_CONTENT_KEYS = {
    "message", "message_text", "text", "content", "prompt", "body",
    "path", "from", "to", "receiver", "recipient", "query",
}
_INLINE_SECRET_PATTERNS = (
    # Provider errors sometimes include request URLs or selected headers in an
    # otherwise harmless-looking field such as ``reason``.  Redact those at
    # the final audit boundary as a second line of defence.
    re.compile(
        r"(?i)(\b(?:[a-z0-9]+[_-])*(?:api[_-]?key|access[_-]?token|authorization)\b"
        r"\s*[=:]\s*)([^\s&,;]+)"
    ),
    re.compile(r"(?i)(\bBearer\s+)([^\s,;]+)"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{16,}\b"),
)


def _redact_inline_secrets(value: str) -> str:
    redacted = value
    for pattern in _INLINE_SECRET_PATTERNS[:2]:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    for pattern in _INLINE_SECRET_PATTERNS[2:]:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def redact_secrets(value: Any, key: str = "") -> Any:
    """Return a JSON-compatible copy with credential-shaped fields removed."""
    lowered = key.casefold()
    if key and any(part in lowered for part in _SECRET_KEY_PARTS):
        return "[REDACTED]"
    if lowered in _SENSITIVE_CONTENT_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): redact_secrets(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        return _redact_inline_secrets(value)
    return value


class AuditIntegrityError(RuntimeError):
    """Raised rather than silently extending a tampered or corrupt audit chain."""


class AuditLog:
    """Append-only JSONL audit log with a verified hash chain.

    The hash chain detects in-place changes and reordered records. It is not a
    substitute for filesystem permissions or an external/immutable anchor, so
    production mounts must be writable only by the MICA service account.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.getenv("AUDIT_PATH", "/data/audit/events.jsonl"))
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _locked_file(self) -> Iterator[TextIO]:
        """Open the log for exclusive append across Linux service processes."""
        fd = os.open(self.path, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o600)
        handle = os.fdopen(fd, "r+", encoding="utf-8")
        try:
            try:  # The runtime containers are Linux; keep local Windows tests portable.
                import fcntl  # type: ignore[import-not-found]

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except ImportError:
                pass
            yield handle
        finally:
            try:
                try:
                    import fcntl  # type: ignore[import-not-found]

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except ImportError:
                    pass
            finally:
                handle.close()

    @staticmethod
    def _records_from(handle: TextIO) -> list[dict[str, Any]]:
        handle.seek(0)
        records: list[dict[str, Any]] = []
        for line in handle:
            if line.strip():
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise AuditIntegrityError("Audit event is not an object")
                records.append(event)
        return records

    @staticmethod
    def _verify_records(records: list[dict[str, Any]]) -> str:
        previous = ""
        for stored_event in records:
            digest = stored_event.get("hash", "")
            if not isinstance(digest, str) or len(digest) != 64:
                raise AuditIntegrityError("Audit event has no valid hash")
            event = {key: value for key, value in stored_event.items() if key != "hash"}
            if event.get("previous_hash", "") != previous:
                raise AuditIntegrityError("Audit chain link does not match")
            canonical = json.dumps(event, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != digest:
                raise AuditIntegrityError("Audit event hash does not match")
            previous = digest
        return previous

    def append(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("Audit event type is required")
        payload = redact_secrets(payload)
        # Validate before obtaining the lock so unserialisable payloads never
        # result in a partially appended record.
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        with self._locked_file() as handle:
            try:
                previous_hash = self._verify_records(self._records_from(handle))
            except (OSError, ValueError, json.JSONDecodeError) as error:
                raise AuditIntegrityError("Audit log cannot be verified; refusing to append") from error
            event = {
                "timestamp": datetime.now(UTC).isoformat(),
                "type": event_type.strip(),
                "payload": payload,
                "previous_hash": previous_hash,
            }
            canonical = json.dumps(event, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            event["hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            handle.seek(0, os.SEEK_END)
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return event

    def read(self, limit: int = 100) -> list[dict[str, Any]]:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                records = self._records_from(handle)
            self._verify_records(records)
        except (OSError, ValueError, json.JSONDecodeError, AuditIntegrityError):
            return []
        return records[-max(1, min(limit, 1000)):]

    def verify(self) -> bool:
        """Verify the complete chain, not merely the API's most recent page."""
        try:
            if not self.path.exists():
                return True
            with self.path.open("r", encoding="utf-8") as handle:
                self._verify_records(self._records_from(handle))
        except (OSError, ValueError, json.JSONDecodeError, AuditIntegrityError):
            return False
        return True
