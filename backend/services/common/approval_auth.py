from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta


class LocalApprovalSessions:
    """Short-lived in-memory sessions unlocked by an environment-owned secret."""

    def __init__(self, secret: str, ttl_minutes: int = 10):
        self._secret_digest = hashlib.sha256(secret.encode("utf-8")).digest() if secret else b""
        self._ttl = timedelta(minutes=max(1, min(ttl_minutes, 60)))
        self._sessions: dict[str, datetime] = {}

    @property
    def configured(self) -> bool:
        return bool(self._secret_digest)

    def login(self, supplied_secret: str) -> str | None:
        if not self.configured:
            return None
        supplied_digest = hashlib.sha256(supplied_secret.encode("utf-8")).digest()
        if not hmac.compare_digest(self._secret_digest, supplied_digest):
            return None
        token = secrets.token_urlsafe(32)
        self._sessions[token] = datetime.now(UTC) + self._ttl
        return token

    def valid(self, token: str | None) -> bool:
        now = datetime.now(UTC)
        self._sessions = {key: expiry for key, expiry in self._sessions.items() if expiry > now}
        return bool(token and self._sessions.get(token, now) > now)

    def revoke_all(self) -> None:
        self._sessions.clear()
