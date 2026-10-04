"""Strict local HTTPS client used by the Windows PyQt shell."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .response_timing import RESPONSE_TIMINGS


class LocalCoreError(RuntimeError):
    pass


class LocalCoreClient:
    def __init__(self, base_url: str | None = None, ca_file: str | Path | None = None,
                 api_token: str | None = None):
        self.base_url = (base_url or os.getenv("MICA_CORE_URL", "https://mica.local")).rstrip("/")
        parsed = urlparse(self.base_url)
        if (parsed.scheme != "https" or parsed.hostname not in {"mica.local", "localhost", "127.0.0.1"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {'', '/'}):
            raise LocalCoreError("MICA_CORE_URL must be a local HTTPS endpoint")
        configured_ca = ca_file or os.getenv("MICA_CORE_CA_FILE", "")
        self.verify: str | bool = str(Path(configured_ca).expanduser().resolve()) if configured_ca else True
        self.session = requests.Session()
        self.session.trust_env = False
        self._credential_error = ''
        if api_token is None:
            api_token = os.getenv('MICA_API_TOKEN', '')
            if not api_token:
                from desktop.core.secure_store import SecureStoreUnavailable, get_secret
                try:
                    api_token = get_secret('MICA_API_TOKEN') or ''
                except SecureStoreUnavailable:
                    self._credential_error = 'Windows Credential Manager ist nicht verfügbar.'
        self.auth_headers = {'X-Mica-API-Token': api_token} if api_token else {}
        self.session.headers.update(self.auth_headers)

    def ensure_credentials(self) -> None:
        if not self.auth_headers:
            detail = self._credential_error or 'MICA_API_TOKEN ist nicht eingerichtet.'
            raise LocalCoreError(f'{detail} Bitte den Core-Zugriffsschlüssel einrichten.')

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        self.ensure_credentials()
        try:
            response = self.session.request(
                method, self.base_url + path, timeout=kwargs.pop('timeout', (5, 180)), verify=self.verify, **kwargs,
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

    def activity(self) -> dict[str, Any]:
        return self._request("GET", "/v1/tasks/activity")

    def action_history(self) -> dict[str, Any]:
        return self._request('GET', '/v1/actions/history')

    def diagnostics(self) -> dict[str, Any]:
        return self._request("GET", "/v1/diagnostics", timeout=(3, 15))

    def pause_plan(self, plan_id: str) -> dict[str, Any]:
        return self._request("PATCH", f"/v1/agent-plans/{plan_id}", json={"status": "paused"})

    def cancel_plan(self, plan_id: str) -> dict[str, Any]:
        return self._request("PATCH", f"/v1/agent-plans/{plan_id}", json={"status": "cancelled"})

    def preview_plan(self, plan_id: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/agent-plans/{plan_id}/dry-run")

    def update_task(self, task_id: str, status: str) -> dict[str, Any]:
        return self._request("PATCH", f"/v1/task-items/{task_id}", json={"status": status})

    def resume_plan(self, plan_id: str, approval_id: str | None = None) -> dict[str, Any]:
        return self._request("POST", f"/v1/agent-plans/{plan_id}/activate", json={'approval_id': approval_id})

    def reconcile(self, identifier: str, *, plan: bool = False) -> dict[str, Any]:
        path = f'/v1/agent-plans/{identifier}/reconcile' if plan else f'/v1/tasks/executions/{identifier}/reconcile'
        return self._request('POST', path, headers={'X-Mica-Approval-Intent': 'confirm'})

    def resume_execution(self, key: str, approval_id: str | None = None) -> dict[str, Any]:
        return self._request('POST', f'/v1/tasks/executions/{key}/resume', json={'approval_id': approval_id},
                             headers={'X-Mica-Approval-Intent': 'confirm'})

    def approvals(self) -> dict[str, Any]:
        return self._request('GET', '/v1/approvals')

    def approve(self, identifier: str) -> dict[str, Any]:
        return self._request('POST', f'/v1/approvals/{identifier}', json={'approved': True},
                             headers={'X-Mica-Approval-Intent': 'confirm'})

    def clear_emergency_stop(self) -> dict[str, Any]:
        return self._request('POST', '/v1/emergency-stop', json={'active': False},
                             headers={'X-Mica-Approval-Intent': 'confirm'})

    def capabilities(self) -> dict[str, Any]:
        return self._request("GET", "/v1/capabilities")

    def turn(self, message: str, conversation_mode: str = "personal", *, remember: bool = True) -> dict[str, Any]:
        timing = RESPONSE_TIMINGS.begin('text')
        try:
            result = self._request("POST", "/v1/turns", json={
                "message": message,
                "client": "pyqt",
                "conversation_mode": conversation_mode,
                "remember": remember,
            })
        except Exception:
            timing.finish('failed')
            raise
        timing.mark('reply')
        timing.finish('success')
        return result

    def login(self, secret: str) -> dict[str, Any]:
        return self._request("POST", "/v1/auth/approval-session", json={"secret": secret})

    def memory_items(self) -> dict[str, Any]:
        return self._request("GET", "/v1/memory/items")

    def remember_item(self, title: str, body: str) -> dict[str, Any]:
        return self._request("POST", "/v1/memory/items", json={"title": title, "body": body},
                             headers={"X-Mica-Approval-Intent": "confirm"})

    def correct_memory(self, document_id: str, body: str) -> dict[str, Any]:
        return self._request("PATCH", f"/v1/brain/documents/{document_id}", json={"body": body},
                             headers={"X-Mica-Approval-Intent": "confirm"})

    def forget_memory(self, document_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/v1/brain/documents/{document_id}",
                             headers={"X-Mica-Approval-Intent": "confirm"})

    def download_backup(self, recovery_id: str | None = None) -> bytes:
        self.ensure_credentials()
        path = f'/v1/backups/recovery/{recovery_id}' if recovery_id else '/v1/backups/export'
        try:
            with self.session.get(self.base_url + path, timeout=(5, 180), verify=self.verify,
                                  headers={'X-Mica-Approval-Intent': 'confirm'}, stream=True) as response:
                if not response.ok:
                    raise LocalCoreError(f'Backup-Anfrage fehlgeschlagen ({response.status_code}): {response.text[:1000]}')
                content = bytearray()
                for chunk in response.iter_content(65536):
                    content.extend(chunk)
                    if len(content) > 64 * 1024 * 1024:
                        raise LocalCoreError('Backup ist zu groß für die Desktop-Oberfläche.')
                return bytes(content)
        except requests.RequestException as error:
            raise LocalCoreError('Backup-Verbindung fehlgeschlagen') from error

    def restore_backup(self, archive: bytes) -> dict[str, Any]:
        return self._request('POST', '/v1/backups/restore', data=archive,
                             headers={'X-Mica-Approval-Intent': 'confirm', 'Content-Type': 'application/gzip'})

    def backup_status(self) -> dict[str, Any]:
        return self._request('GET', '/v1/backups/status')

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
