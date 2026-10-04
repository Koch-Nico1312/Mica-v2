from __future__ import annotations
import json
import hashlib
import hmac
import os
import uuid
from fastapi import HTTPException
from typing import Any
from fastapi import Header, Query, Request, Response
from backend.services.api.schemas import ConnectorConfiguration, ConnectorEvent


class ConnectorsRoutes:
    def list_connectors(self) -> dict[str, Any]:
        return {"connectors": self.connectors.list()}

    def configure_connector(
        self, name: str, request: ConnectorConfiguration
    ) -> dict[str, Any]:
        params = {"name": name, "enabled": request.enabled}
        decision = self.policy.decide("connector.configure", params)
        if not decision.allowed:
            raise HTTPException(
                403,
                detail={"reason": decision.reason, "approval_id": decision.approval_id},
            )
        try:
            self.connectors.set_enabled(name, request.enabled)
        except ValueError as error:
            raise HTTPException(422, detail=str(error)) from error
        self.audit.append(
            "connector.configured",
            {"name": name, "enabled": request.enabled, "external": True},
        )
        return {"name": name, "enabled": request.enabled, "external": True}

    def receive_connector_event(
        self,
        name: str,
        event: ConnectorEvent,
        x_mica_connector_secret: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """Legacy generic ingress for non-provider-specific local connectors."""
        if name in {"telegram", "whatsapp"}:
            raise HTTPException(404, "Use the provider-specific webhook endpoint")
        self._require_enabled_connector(name)
        expected = os.getenv(f"MICA_{name.upper()}_WEBHOOK_SECRET", "")
        if (
            not expected
            or not x_mica_connector_secret
            or (not hmac.compare_digest(expected, x_mica_connector_secret))
        ):
            raise HTTPException(401, "Invalid connector webhook secret")
        return self._record_inbound_connector_event(
            name, f"generic:{uuid.uuid4().hex}", event.event, event.message, {}
        )

    async def receive_telegram_webhook(
        self,
        request: Request,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """Authenticate and parse Telegram updates without giving them authority."""
        self._require_enabled_connector("telegram")
        expected_secret = os.getenv("MICA_TELEGRAM_WEBHOOK_SECRET", "").strip()
        if (
            not expected_secret
            or not x_telegram_bot_api_secret_token
            or (
                not hmac.compare_digest(
                    expected_secret, x_telegram_bot_api_secret_token
                )
            )
        ):
            raise HTTPException(401, "Invalid Telegram webhook secret")
        _, payload = await self._webhook_json(request)
        update_id = payload.get("update_id")
        if (
            isinstance(update_id, bool)
            or not isinstance(update_id, int)
            or update_id < 0
        ):
            raise HTTPException(422, "Telegram update_id is required")
        parsed = self._telegram_message(payload)
        if not parsed:
            return {"accepted": True, "ignored": True}
        event, message, chat_id = parsed
        allowed_chats = {
            item.strip()
            for item in os.getenv("MICA_TELEGRAM_INBOUND_CHAT_IDS", "").split(",")
            if item.strip()
        }
        if allowed_chats and (not chat_id or chat_id not in allowed_chats):
            raise HTTPException(403, "Telegram chat is not allowlisted")
        metadata = {"chat_id": chat_id} if chat_id else {}
        return self._record_inbound_connector_event(
            "telegram", f"telegram:{update_id}", event, message, metadata
        )

    def verify_whatsapp_webhook(
        self,
        hub_mode: str | None = Query(default=None, alias="hub.mode"),
        hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
        hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    ) -> Response:
        """Perform Meta's challenge handshake only for an explicitly enabled connector."""
        self._require_enabled_connector("whatsapp")
        expected_token = os.getenv("MICA_WHATSAPP_VERIFY_TOKEN", "").strip()
        if (
            hub_mode != "subscribe"
            or not expected_token
            or (not hub_verify_token)
            or (not hmac.compare_digest(expected_token, hub_verify_token))
            or (hub_challenge is None)
        ):
            raise HTTPException(403, "WhatsApp webhook verification failed")
        if len(hub_challenge) > 512:
            raise HTTPException(422, "WhatsApp webhook challenge is invalid")
        return Response(content=hub_challenge, media_type="text/plain")

    async def receive_whatsapp_webhook(
        self, request: Request, x_hub_signature_256: str | None = Header(default=None)
    ) -> dict[str, Any]:
        """Verify Meta's raw-body HMAC and turn inbound text into dry-run context."""
        self._require_enabled_connector("whatsapp")
        body, payload = await self._webhook_json(request)
        app_secret = os.getenv("MICA_WHATSAPP_APP_SECRET", "").strip()
        expected_signature = (
            "sha256="
            + hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
            if app_secret
            else ""
        )
        if (
            not expected_signature
            or not x_hub_signature_256
            or (
                not hmac.compare_digest(expected_signature, x_hub_signature_256.strip())
            )
        ):
            raise HTTPException(401, "Invalid WhatsApp webhook signature")
        if payload.get("object") != "whatsapp_business_account":
            raise HTTPException(422, "Unexpected WhatsApp webhook object")
        accepted: list[dict[str, Any]] = []
        ignored = 0
        entries = payload.get("entry")
        if not isinstance(entries, list) or len(entries) > 100:
            raise HTTPException(422, "WhatsApp webhook entry is invalid")
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(
                entry.get("changes"), list
            ):
                raise HTTPException(422, "WhatsApp webhook change is invalid")
            for change in entry["changes"]:
                if (
                    not isinstance(change, dict)
                    or change.get("field") != "messages"
                    or (not isinstance(change.get("value"), dict))
                ):
                    ignored += 1
                    continue
                for message in change["value"].get("messages", []):
                    if not isinstance(message, dict):
                        raise HTTPException(422, "WhatsApp message is invalid")
                    message_id = message.get("id")
                    message_type = message.get("type")
                    text_body = (
                        message.get("text", {}).get("body")
                        if isinstance(message.get("text"), dict)
                        else None
                    )
                    if (
                        not isinstance(message_id, str)
                        or not message_id
                        or len(message_id) > 512
                    ):
                        raise HTTPException(422, "WhatsApp message id is required")
                    if (
                        message_type != "text"
                        or not isinstance(text_body, str)
                        or (not text_body.strip())
                    ):
                        ignored += 1
                        continue
                    sender = message.get("from")
                    metadata = (
                        {"sender": str(sender)[:64]} if sender is not None else {}
                    )
                    accepted.append(
                        self._record_inbound_connector_event(
                            "whatsapp",
                            f"whatsapp:{message_id}",
                            "message",
                            text_body.strip()[:16000],
                            metadata,
                        )
                    )
        return {
            "accepted": True,
            "received": len(accepted),
            "duplicates": sum((1 for item in accepted if item.get("duplicate"))),
            "ignored": ignored,
        }

    def _require_enabled_connector(self, name: str) -> None:
        try:
            if not self.connectors.enabled(name):
                raise HTTPException(409, "Connector is disabled")
        except ValueError as error:
            raise HTTPException(404, str(error)) from error

    def _record_inbound_connector_event(
        self,
        name: str,
        provider_event_id: str,
        event: str,
        message: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist an authenticated inbound message and produce a dry-run only.

        Provider payloads deliberately do not supply a MICA action or parameters.
        The event becomes context for a later local interaction, never an external
        command path.
        """
        try:
            claimed = self.connectors.claim_inbound_event(name, provider_event_id)
        except ValueError as error:
            raise HTTPException(422, detail=str(error)) from error
        if not claimed:
            return {"accepted": True, "duplicate": True}
        source = self.brain.write(
            "events",
            f"{name}: {event}",
            f"Connector: `{name}`\n\nEvent: `{event}`\n\nMessage:\n{message}",
            {
                "connector": name,
                "external": True,
                "provider_event_id": provider_event_id,
                **metadata,
            },
        )
        plan = self.orchestrator.plan(
            message or f"External event {event} from {name}", None, {}, True
        )
        self.audit.append(
            "connector.event_received",
            {
                "name": name,
                "event": event,
                "provider_event_id": provider_event_id,
                "brain_document": source["id"],
                "task_id": plan["task_id"],
            },
        )
        return {
            "accepted": True,
            "duplicate": False,
            "brain_document": source["id"],
            "plan": plan,
        }

    async def _webhook_json(self, request: Request) -> tuple[bytes, dict[str, Any]]:
        content_length = request.headers.get("content-length", "")
        try:
            if (
                content_length
                and int(content_length) > self.MAX_CONNECTOR_WEBHOOK_BYTES
            ):
                raise HTTPException(413, "Connector webhook payload is too large")
        except ValueError as error:
            raise HTTPException(400, "Invalid Content-Length") from error
        body = await request.body()
        if len(body) > self.MAX_CONNECTOR_WEBHOOK_BYTES:
            raise HTTPException(413, "Connector webhook payload is too large")
        try:
            payload = json.loads(body)
        except (TypeError, ValueError) as error:
            raise HTTPException(400, "Connector webhook body must be JSON") from error
        if not isinstance(payload, dict):
            raise HTTPException(422, "Connector webhook payload must be an object")
        return (body, payload)

    def _telegram_message(
        self, payload: dict[str, Any]
    ) -> tuple[str, str, str | None] | None:
        for key in ("message", "edited_message", "channel_post", "edited_channel_post"):
            candidate = payload.get(key)
            if not isinstance(candidate, dict):
                continue
            text = candidate.get("text", candidate.get("caption", ""))
            if not isinstance(text, str) or not text.strip():
                continue
            chat = candidate.get("chat")
            chat_id = (
                str(chat.get("id"))
                if isinstance(chat, dict) and chat.get("id") is not None
                else None
            )
            return (key, text.strip()[:16000], chat_id)
        callback = payload.get("callback_query")
        if (
            isinstance(callback, dict)
            and isinstance(callback.get("data"), str)
            and callback["data"].strip()
        ):
            callback_message = callback.get("message")
            chat = (
                callback_message.get("chat")
                if isinstance(callback_message, dict)
                else None
            )
            chat_id = (
                str(chat.get("id"))
                if isinstance(chat, dict) and chat.get("id") is not None
                else None
            )
            return ("callback_query", callback["data"].strip()[:16000], chat_id)
        return None


ROUTES = [
    ("/v1/connectors", "get", "list_connectors"),
    ("/v1/connectors/{name}", "post", "configure_connector"),
    ("/v1/connectors/{name}/events", "post", "receive_connector_event"),
    ("/v1/connectors/telegram/webhook", "post", "receive_telegram_webhook"),
    ("/v1/connectors/whatsapp/webhook", "get", "verify_whatsapp_webhook"),
    ("/v1/connectors/whatsapp/webhook", "post", "receive_whatsapp_webhook"),
]
