from __future__ import annotations
import base64
from fastapi import HTTPException
from typing import Any
from backend.services.api.schemas import (
    AddressingEvaluateRequest,
    AutonomousPolicyUpdateRequest,
    AutonomousTicketResolveRequest,
    SatelliteAnnounceRequest,
    SatelliteHeartbeatRequest,
    SatelliteRegisterRequest,
    VisionAnalyzeRequest,
    VisionCaptureRequest,
)


class PerceptionRoutes:
    def vision_status(self) -> dict[str, Any]:
        self._require_phase45()
        return {
            "ready": self.vision_engine.ready,
            "endpoint": self.vision_engine.local_endpoint,
            "remote_provider": self.vision_engine.remote_provider,
            "modes": ["general", "room_state", "server_rack", "object_detection"],
            "max_bytes": 5 * 1024 * 1024,
        }

    def vision_analyze(self, request: VisionAnalyzeRequest) -> dict[str, Any]:
        self._require_phase45()
        try:
            data = base64.b64decode(request.image_base64)
        except Exception as e:
            raise HTTPException(422, f"Ungültiges Base64-Bild: {e}")
        try:
            result = self.vision_engine.analyze(
                data, mode=request.mode, prompt=request.prompt
            )
        except ValueError as err:
            raise HTTPException(422, str(err))
        self.audit.append(
            "vision.analyzed",
            {
                "image_hash": result.image_hash,
                "mode": result.mode,
                "anomalies_count": len(result.anomalies),
            },
        )
        return result.to_dict()

    def vision_capture(self, request: VisionCaptureRequest) -> dict[str, Any]:
        self._require_phase45()
        try:
            frame_bytes = self.vision_engine.capture_frame(request.source_id)
            fmt, sha256, dims = self.vision_engine.validate_image_payload(frame_bytes)
        except Exception as err:
            raise HTTPException(500, f"Bildaufnahme fehlgeschlagen: {err}")
        self.audit.append(
            "vision.captured", {"image_hash": sha256, "source_id": request.source_id}
        )
        return {
            "image_hash": sha256,
            "format": fmt,
            "dimensions": dims,
            "image_base64": base64.b64encode(frame_bytes).decode("ascii"),
        }

    def list_ambient_events(
        self, status: str | None = None, limit: int = 50
    ) -> dict[str, Any]:
        self._require_phase45()
        return {"events": self.ambient_monitor.list_events(status=status, limit=limit)}

    def acknowledge_ambient_event(self, event_id: str) -> dict[str, bool]:
        self._require_phase45()
        success = self.ambient_monitor.acknowledge_event(event_id)
        if not success:
            raise HTTPException(
                404, "Ambient-Event nicht gefunden oder bereits bestätigt."
            )
        self.audit.append("ambient.acknowledged", {"event_id": event_id})
        return {"acknowledged": True}

    def ambient_status(self) -> dict[str, Any]:
        self._require_phase45()
        return {
            "pending_events": self.ambient_monitor.pending_count(),
            "quiet_hours_enabled": self.ambient_monitor.quiet_hours_enabled,
            "quiet_start_hour": self.ambient_monitor.quiet_start_hour,
            "quiet_end_hour": self.ambient_monitor.quiet_end_hour,
        }

    def evaluate_ambient(self) -> dict[str, Any]:
        self._require_phase45()
        obs = self.phase4_store.server_observations()
        server_events = self.ambient_monitor.evaluate_server_state(obs)
        schedules = self.schedule_store.list("pending")
        schedule_events = self.ambient_monitor.evaluate_schedules(schedules)
        all_events = server_events + schedule_events
        self.audit.append("ambient.evaluated", {"new_events_count": len(all_events)})
        return {"events": all_events}

    def evaluate_addressing(self, request: AddressingEvaluateRequest) -> dict[str, Any]:
        self._require_phase45()
        decision = self.addressing_detector.evaluate(
            request.text, acoustic_energy=request.acoustic_energy, snr_db=request.snr_db
        )
        return decision.to_dict()

    def register_satellite(self, request: SatelliteRegisterRequest) -> dict[str, Any]:
        self._require_phase45()
        node = self.satellite_registry.register(
            request.satellite_id,
            request.name,
            request.room,
            request.ip_address,
            request.capabilities,
        )
        self.audit.append(
            "satellite.registered",
            {"satellite_id": request.satellite_id, "room": request.room},
        )
        return node

    def list_satellites(self) -> dict[str, Any]:
        self._require_phase45()
        return {"satellites": self.satellite_registry.list_satellites()}

    def satellite_heartbeat(
        self, satellite_id: str, request: SatelliteHeartbeatRequest
    ) -> dict[str, Any]:
        self._require_phase45()
        announcements = self.satellite_registry.heartbeat(
            satellite_id, request.telemetry
        )
        return {"status": "ok", "announcements": announcements}

    def queue_satellite_announcement(
        self, request: SatelliteAnnounceRequest
    ) -> dict[str, Any]:
        self._require_phase45()
        ann = self.satellite_registry.queue_announcement(
            request.satellite_id, request.message, request.priority
        )
        self.audit.append(
            "satellite.announced",
            {"announcement_id": ann["id"], "target": request.satellite_id or "all"},
        )
        return ann

    def mark_satellite_announcement_delivered(
        self, announcement_id: str
    ) -> dict[str, bool]:
        self._require_phase45()
        ok = self.satellite_registry.mark_announcement_delivered(announcement_id)
        return {"delivered": ok}

    def list_autonomous_tickets(self, status: str | None = None) -> dict[str, Any]:
        self._require_phase45()
        return {"tickets": self.autonomous_guard.list_tickets(status=status)}

    def get_autonomous_ticket(self, ticket_id: str) -> dict[str, Any]:
        self._require_phase45()
        t = self.autonomous_guard.get_ticket(ticket_id)
        if not t:
            raise HTTPException(404, "Ticket nicht gefunden")
        return t

    def resolve_autonomous_ticket(
        self, ticket_id: str, request: AutonomousTicketResolveRequest
    ) -> dict[str, Any]:
        self._require_phase45()
        if request.approve:
            ok, token_or_err = self.autonomous_guard.approve_ticket(
                ticket_id, request.operator_id
            )
            if not ok:
                raise HTTPException(409, token_or_err)
            self.audit.append(
                "autonomous_guard.ticket_approved",
                {"ticket_id": ticket_id, "operator_id": request.operator_id},
            )
            return {"approved": True, "token": token_or_err}
        else:
            ok = self.autonomous_guard.reject_ticket(ticket_id, request.operator_id)
            if not ok:
                raise HTTPException(
                    409, "Ticket nicht gefunden oder bereits bearbeitet."
                )
            self.audit.append(
                "autonomous_guard.ticket_rejected",
                {"ticket_id": ticket_id, "operator_id": request.operator_id},
            )
            return {"approved": False}

    def update_autonomous_policy(
        self, request: AutonomousPolicyUpdateRequest
    ) -> dict[str, bool]:
        self._require_phase45()
        self.autonomous_guard.set_tier1_policy(
            request.action, request.auto_allow_tier1, request.max_auto_per_hour
        )
        self.audit.append(
            "autonomous_guard.policy_updated",
            {"action": request.action, "auto_allow": request.auto_allow_tier1},
        )
        return {"updated": True}


ROUTES = [
    ("/v1/vision/status", "get", "vision_status"),
    ("/v1/vision/analyze", "post", "vision_analyze"),
    ("/v1/vision/capture", "post", "vision_capture"),
    ("/v1/ambient/events", "get", "list_ambient_events"),
    ("/v1/ambient/events/{event_id}/acknowledge", "post", "acknowledge_ambient_event"),
    ("/v1/ambient/status", "get", "ambient_status"),
    ("/v1/ambient/evaluate", "post", "evaluate_ambient"),
    ("/v1/addressing/evaluate", "post", "evaluate_addressing"),
    ("/v1/satellites/register", "post", "register_satellite"),
    ("/v1/satellites", "get", "list_satellites"),
    ("/v1/satellites/{satellite_id}/heartbeat", "post", "satellite_heartbeat"),
    ("/v1/satellites/announce", "post", "queue_satellite_announcement"),
    (
        "/v1/satellites/announcements/{announcement_id}/delivered",
        "post",
        "mark_satellite_announcement_delivered",
    ),
    ("/v1/autonomous-guard/tickets", "get", "list_autonomous_tickets"),
    ("/v1/autonomous-guard/tickets/{ticket_id}", "get", "get_autonomous_ticket"),
    (
        "/v1/autonomous-guard/tickets/{ticket_id}/resolve",
        "post",
        "resolve_autonomous_ticket",
    ),
    ("/v1/autonomous-guard/policies", "patch", "update_autonomous_policy"),
]
