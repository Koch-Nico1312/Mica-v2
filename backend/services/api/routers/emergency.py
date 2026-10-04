from __future__ import annotations
from fastapi import HTTPException
from typing import Any
from fastapi import Header, Request
from backend.services.api.schemas import EmergencyLoginRequest, EmergencyTicketResolveRequest


class EmergencyRoutes:
    def emergency_login(
        self, request: EmergencyLoginRequest, req: Request
    ) -> dict[str, Any]:
        self._require_phase45()
        client_ip = req.client.host if req.client else "remote"
        token = self.emergency_service.login(request.secret, client_ip)
        if not token:
            self.audit.append("emergency.login_failed", {"client_ip": client_ip})
            raise HTTPException(
                401, "Ungültiges Notfall-Secret oder Client vorübergehend gesperrt."
            )
        self.audit.append("emergency.login_success", {"client_ip": client_ip})
        return {"token": token, "expires_in_minutes": 15}

    def emergency_overview(
        self,
        authorization: str | None = Header(None),
        x_mica_emergency_authorization: str | None = Header(None),
    ) -> dict[str, Any]:
        authorization = (
            x_mica_emergency_authorization
            if isinstance(x_mica_emergency_authorization, str)
            else authorization
        )
        self._require_phase45()
        self._verify_emergency_auth(authorization)
        return self.emergency_service.get_emergency_overview(
            policy=self.policy,
            phase4_store=self.phase4_store,
            ambient_monitor=self.ambient_monitor,
            guard=self.autonomous_guard,
        )

    def emergency_stop_action(
        self,
        authorization: str | None = Header(None),
        x_mica_emergency_authorization: str | None = Header(None),
    ) -> dict[str, Any]:
        authorization = (
            x_mica_emergency_authorization
            if isinstance(x_mica_emergency_authorization, str)
            else authorization
        )
        self._require_phase45()
        self._verify_emergency_auth(authorization)
        self.emergency_service.trigger_emergency_stop(
            self.policy, self.autonomous_guard
        )
        self._cancel_active_voice()
        self.audit.append("emergency.notaus_triggered", {"source": "mobile_emergency"})
        return {"status": "emergency_stop_activated", "stopped": True}

    def emergency_resume_action(
        self,
        authorization: str | None = Header(None),
        x_mica_emergency_authorization: str | None = Header(None),
    ) -> dict[str, Any]:
        authorization = (
            x_mica_emergency_authorization
            if isinstance(x_mica_emergency_authorization, str)
            else authorization
        )
        self._require_phase45()
        self._verify_emergency_auth(authorization)
        self.emergency_service.resume_from_emergency_stop(self.policy)
        self.audit.append("emergency.resumed", {"source": "mobile_emergency"})
        return {"status": "resumed", "stopped": False}

    def emergency_resolve_ticket(
        self,
        ticket_id: str,
        request: EmergencyTicketResolveRequest,
        authorization: str | None = Header(None),
        x_mica_emergency_authorization: str | None = Header(None),
    ) -> dict[str, Any]:
        authorization = (
            x_mica_emergency_authorization
            if isinstance(x_mica_emergency_authorization, str)
            else authorization
        )
        self._require_phase45()
        self._verify_emergency_auth(authorization)
        if request.approve:
            ok, token_or_err = self.autonomous_guard.approve_ticket(
                ticket_id, operator_id="mobile_emergency"
            )
            if not ok:
                raise HTTPException(409, token_or_err)
            self.audit.append("emergency.ticket_approved", {"ticket_id": ticket_id})
            return {"status": "approved", "token": token_or_err}
        else:
            ok = self.autonomous_guard.reject_ticket(
                ticket_id, operator_id="mobile_emergency"
            )
            if not ok:
                raise HTTPException(409, "Ticket konnte nicht abgelehnt werden.")
            self.audit.append("emergency.ticket_rejected", {"ticket_id": ticket_id})
            return {"status": "rejected"}

    def _verify_emergency_auth(self, authorization: str | None = Header(None)) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Authorization Bearer Token fehlt")
        token = authorization.split(" ", 1)[1]
        if not self.emergency_service.validate_token(token):
            raise HTTPException(403, "Notfall-Token abgelaufen oder ungültig")


ROUTES = [
    ("/v1/emergency/login", "post", "emergency_login"),
    ("/v1/emergency/overview", "get", "emergency_overview"),
    ("/v1/emergency/stop", "post", "emergency_stop_action"),
    ("/v1/emergency/resume", "post", "emergency_resume_action"),
    ("/v1/emergency/tickets/{ticket_id}/resolve", "post", "emergency_resolve_ticket"),
]
