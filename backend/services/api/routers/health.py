from __future__ import annotations
import json
from datetime import timedelta
from pathlib import Path
import os
from datetime import UTC, datetime
from urllib.parse import urlparse
from typing import Any
from fastapi import Query
from backend.services.api.constants import LOCAL_LLM_HOSTS


class HealthRoutes:
    def health(self) -> dict[str, str]:
        return {"status": "ok", "mode": "local-only"}

    def capabilities(self) -> dict[str, Any]:
        """Expose the authoritative Phase-0 registry without importing host actions."""
        entries = self.list_capabilities()
        return {
            "schema_version": 1,
            "count": len(entries),
            "available": sum((1 for item in entries if item["available"])),
            "capabilities": entries,
        }

    def phase0_health(self) -> dict[str, Any]:
        entries = self.list_capabilities()
        windows_preflight = self._windows_preflight_evidence()
        unavailable = [
            {"module": item["module"], "reason": item["availability_reason"]}
            for item in entries
            if not item["available"]
        ]
        checks = {
            "audit_chain": self.audit.verify(),
            "approval_auth": self.approval_sessions.configured,
            "capability_contract": len(entries) == 20,
            "local_llm_url": all(
                (
                    not value
                    or (
                        urlparse(value).scheme == "http"
                        and urlparse(value).hostname in LOCAL_LLM_HOSTS
                    )
                    for value in (
                        os.getenv("LLAMA_URL", "http://llama-server:8080"),
                        os.getenv("MICA_LLM_FALLBACK_URL", ""),
                    )
                )
            ),
            "host_agent_configured": bool(os.getenv("MICA_HOST_AGENT_URL", "").strip()),
            "windows_preflight": bool(windows_preflight.get("ok")),
        }
        return {
            "status": "ready"
            if all(checks.values()) and (not unavailable)
            else "blocked",
            "checks": checks,
            "windows_preflight": windows_preflight,
            "unavailable_capabilities": unavailable,
        }

    def operations_summary(
        self, hours: int = Query(default=24, ge=1, le=744)
    ) -> dict[str, Any]:
        """Local dashboard data; unknown prices intentionally show quantities only."""
        result = self.operations.summary(hours)
        result["services"] = {
            "api": "ok",
            "audit": "ok" if self.audit.verify() else "critical",
            "emergency_stop": "active"
            if self.policy.is_emergency_stopped()
            else "inactive",
        }
        capability_entries = self.list_capabilities()
        result["tool_availability"] = {
            "total": len(capability_entries),
            "available": sum((1 for item in capability_entries if item["available"])),
            "blocked": [
                item["action"] for item in capability_entries if not item["available"]
            ],
        }
        return result

    def diagnostics(self) -> dict[str, Any]:
        phase0 = self.phase0_health()
        labels = {
            "audit_valid": "Integrität des Aktionsprotokolls",
            "capability_registry": "Aktionsregister",
            "local_llm_url": "Lokale Modelladresse",
            "host_agent_configured": "Windows-Aktionsdienst eingerichtet",
            "windows_preflight": "Windows-Betriebsprüfung",
            "emergency_stop_inactive": "Not-Aus aufgehoben",
        }
        checks = [
            {
                "id": name,
                "label": labels.get(name, name.replace("_", " ")),
                "status": "ok" if ok else "blocked",
                "detail": "Prüfung bestanden" if ok else "Prüfung nicht bestanden",
                "remedy": ""
                if ok
                else "Backend-Konfiguration und Phase-0-Abnahme prüfen.",
            }
            for name, ok in phase0["checks"].items()
        ]
        checks.extend(self.service_diagnostics())
        unavailable = phase0["unavailable_capabilities"]
        checks.append(
            {
                "id": "capabilities",
                "label": "Verfügbare Aktionen",
                "status": "blocked" if unavailable else "ok",
                "detail": ", ".join((str(item) for item in unavailable))
                if unavailable
                else "Alle registrierten Aktionen verfügbar",
                "remedy": "Benötigte Funktionen und ihre Zugangsdaten in den Einstellungen prüfen."
                if unavailable
                else "",
            }
        )
        return {
            "checked_at": datetime.now(UTC).isoformat(),
            "checks": checks,
            "status": "ready"
            if all((item["status"] == "ok" for item in checks))
            else "blocked",
        }

    def _windows_preflight_evidence(self) -> dict[str, Any]:
        path = Path(
            os.getenv(
                "MICA_WINDOWS_PREFLIGHT_REPORT", "/data/phase0/windows-preflight.json"
            )
        )
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            checked_at = datetime.fromisoformat(
                str(report["checked_at"]).replace("Z", "+00:00")
            ).astimezone(UTC)
            fresh = datetime.now(UTC) - checked_at <= timedelta(hours=24)
            return {
                "ok": bool(report.get("ready")) and fresh,
                "fresh": fresh,
                "checked_at": checked_at.isoformat(),
                "checks": report.get("checks", {}),
            }
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return {
                "ok": False,
                "fresh": False,
                "reason": "missing_or_invalid_windows_preflight",
            }


ROUTES = [
    ("/health", "get", "health"),
    ("/v1/capabilities", "get", "capabilities"),
    ("/v1/health/phase0", "get", "phase0_health"),
    ("/v1/operations/summary", "get", "operations_summary"),
    ("/v1/diagnostics", "get", "diagnostics"),
]
