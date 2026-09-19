"""Strict local HTTPS client used by the Windows PyQt shell."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


class LocalCoreError(RuntimeError):
    pass


class LocalCoreClient:
    def __init__(self, base_url: str | None = None, ca_file: str | Path | None = None):
        self.base_url = (base_url or os.getenv("MICA_CORE_URL", "https://mica.local")).rstrip("/")
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or parsed.hostname not in {"mica.local", "localhost", "127.0.0.1"}:
            raise LocalCoreError("MICA_CORE_URL must be a local HTTPS endpoint")
        configured_ca = ca_file or os.getenv("MICA_CORE_CA_FILE", "")
        self.verify: str | bool = str(Path(configured_ca).expanduser().resolve()) if configured_ca else True
        self.session = requests.Session()
        self.session.trust_env = False

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.session.request(
                method, self.base_url + path, timeout=(5, 180), verify=self.verify, **kwargs,
            )
        except requests.RequestException as error:
            raise LocalCoreError(f"Lokaler MICA-Core nicht erreichbar: {error}") from error
        try:
            payload = response.json()
        except ValueError as error:
            raise LocalCoreError(f"Ungueltige Core-Antwort ({response.status_code})") from error
        if not response.ok:
            detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
            raise LocalCoreError(f"Core-Anfrage fehlgeschlagen ({response.status_code}): {detail}")
        if not isinstance(payload, dict):
            raise LocalCoreError("Core-Antwort ist kein Objekt")
        return payload

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/v1/health/phase0")

    def capabilities(self) -> dict[str, Any]:
        return self._request("GET", "/v1/capabilities")

    def turn(self, message: str, conversation_mode: str = "personal") -> dict[str, Any]:
        return self._request("POST", "/v1/turns", json={
            "message": message,
            "client": "pyqt",
            "conversation_mode": conversation_mode,
        })

    def plan(
        self,
        message: str,
        action: str,
        params: dict[str, Any],
        *,
        dry_run: bool = True,
        conversation_mode: str = "personal",
    ) -> dict[str, Any]:
        return self._request(
            "POST", "/v1/turns",
            json={
                "message": message,
                "action": action,
                "params": params,
                "dry_run": dry_run,
                "client": "pyqt",
                "conversation_mode": conversation_mode,
            },
        )

    def profile(self) -> dict[str, Any]:
        return self._request("GET", "/v1/profile")

    def update_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", "/v1/profile", json=profile)

    def learning_domains(self) -> dict[str, Any]:
        return self._request("GET", "/v1/learning/domains")

    def research(self, topic: str, domain_id: str, max_sources: int = 3) -> dict[str, Any]:
        return self._request("POST", "/v1/learning/research", json={
            "schema_version": 1, "topic": topic,
            "domain_id": domain_id, "max_sources": max_sources,
        })

    def execute(
        self,
        task_id: str,
        action: str,
        params: dict[str, Any],
        *,
        approval_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/tasks/execute", json={
            "task_id": task_id,
            "action": action,
            "params": params,
            "approval_id": approval_id,
            "idempotency_key": idempotency_key,
        })
