from __future__ import annotations
import os
from fastapi import WebSocket
from fastapi import HTTPException
from typing import Any
from fastapi import Header, Request, Response
from backend.services.api.schemas import ApprovalLogin, ApprovalRequest, EmergencyStopRequest


class ApprovalsRoutes:
    def create_approval_session(
        self, login: ApprovalLogin, request: Request, response: Response
    ) -> dict[str, bool]:
        """Unlock confirmations locally without exposing the secret to tool calls."""
        if not self.approval_sessions.configured:
            raise HTTPException(503, "Local approval authentication is not configured")
        token = self.approval_sessions.login(login.secret)
        if not token:
            self.audit.append(
                "approval.login_failed",
                {"client": request.client.host if request.client else "unknown"},
            )
            raise HTTPException(401, "Invalid local approval secret")
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        response.set_cookie(
            "mica_approval_session",
            token,
            max_age=600,
            httponly=True,
            secure=request.url.scheme == "https" or forwarded_proto == "https",
            samesite="strict",
            path="/v1/",
        )
        self.audit.append(
            "approval.login_succeeded",
            {"client": request.client.host if request.client else "unknown"},
        )
        return {"authenticated": True}

    def approve(
        self,
        approval_id: str,
        approval: ApprovalRequest,
        request: Request,
        x_mica_approval_intent: str | None = Header(default=None),
    ) -> dict[str, bool]:
        if x_mica_approval_intent != "confirm" or not self.approval_sessions.valid(
            request.cookies.get("mica_approval_session")
        ):
            raise HTTPException(
                401, "An authenticated local browser confirmation is required"
            )
        if not self.policy.resolve(approval_id, approval.approved):
            raise HTTPException(status_code=404, detail="Pending approval not found")
        self.audit.append(
            "approval.resolved",
            {"approval_id": approval_id, "approved": approval.approved},
        )
        return {"ok": True}

    def pending_approvals(self, request: Request) -> dict[str, Any]:
        if not self.approval_sessions.valid(
            request.cookies.get("mica_approval_session")
        ):
            raise HTTPException(
                401, "An authenticated local browser session is required"
            )
        return {"approvals": self.policy.pending()}

    def emergency_stop(
        self,
        control: EmergencyStopRequest,
        request: Request,
        x_mica_approval_intent: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """Persistently block new tool decisions until a local user clears the stop."""
        if not control.active and (
            x_mica_approval_intent != "confirm"
            or not self.approval_sessions.valid(
                request.cookies.get("mica_approval_session")
            )
        ):
            raise HTTPException(
                401,
                "Clearing emergency stop requires an authenticated local confirmation",
            )
        if control.active:
            return self._activate_emergency_stop("api")
        try:
            with self.StorageLease(self.brain.root.parent, timeout=1):
                if (self.brain.root.parent / ".restore-incomplete").exists():
                    raise HTTPException(
                        409,
                        "Not-Aus bleibt während einer unvollständigen Wiederherstellung aktiv",
                    )
                return self._clear_emergency_stop(control)
        except self.StorageBusy as error:
            raise HTTPException(
                409, "Not-Aus bleibt während Backup/Wiederherstellung aktiv"
            ) from error

    def _activate_emergency_stop(
        self, source: str, *, exclude_voice: WebSocket | None = None
    ) -> dict[str, Any]:
        self.policy.set_emergency_stop(True)
        self.approval_sessions.revoke_all()
        cancelled = self.schedule_store.stop_all_pending()
        cancelled_voice = self._cancel_active_voice(exclude_voice)
        broker_result: dict[str, Any] = {"reachable": False}
        try:
            response = self.httpx.post(
                os.getenv("TOOL_BROKER_URL", "http://tool-broker:8093")
                + "/v1/emergency-stop",
                json={"active": True},
                timeout=self.httpx.Timeout(10.0, connect=3.0),
            )
            response.raise_for_status()
            broker_result = response.json()
        except (self.httpx.HTTPError, ValueError):
            pass
        self.audit.append(
            "emergency_stop.changed",
            {
                "active": True,
                "source": source,
                "cancelled_schedules": cancelled,
                "cancelled_voice_sessions": cancelled_voice,
                "broker": broker_result,
            },
        )
        return {
            "active": True,
            "cancelled_schedules": cancelled,
            "cancelled_voice_sessions": cancelled_voice,
            "broker": broker_result,
        }

    def _clear_emergency_stop(self, control: EmergencyStopRequest) -> dict[str, Any]:
        cancelled = 0
        broker_result: dict[str, Any]
        try:
            response = self.httpx.post(
                os.getenv("TOOL_BROKER_URL", "http://tool-broker:8093")
                + "/v1/emergency-stop",
                json={"active": control.active},
                timeout=self.httpx.Timeout(10.0, connect=3.0),
            )
            response.raise_for_status()
            broker_result = response.json()
        except (self.httpx.HTTPError, ValueError) as error:
            raise HTTPException(
                503,
                "Not-Aus bleibt aktiv, weil Broker/Host-Agent die Aufhebung nicht bestaetigt hat",
            ) from error
        self.policy.set_emergency_stop(False)
        self.audit.append(
            "emergency_stop.changed",
            {
                "active": control.active,
                "cancelled_schedules": cancelled,
                "broker": broker_result,
            },
        )
        return {
            "active": control.active,
            "cancelled_schedules": cancelled,
            "broker": broker_result,
        }


ROUTES = [
    ("/v1/auth/approval-session", "post", "create_approval_session"),
    ("/v1/approvals/{approval_id}", "post", "approve"),
    ("/v1/approvals", "get", "pending_approvals"),
    ("/v1/emergency-stop", "post", "emergency_stop"),
]
