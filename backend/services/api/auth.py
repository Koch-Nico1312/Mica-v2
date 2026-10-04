"""Fail-closed authentication before HTTP handlers or WebSocket acceptance."""

import hashlib
import hmac

from starlette.responses import JSONResponse


# Provider ingress has its own mandatory signature/shared-secret verification.
# These exact method/path pairs cannot expose the generic connector endpoints.
PROVIDER_INGRESS = {
    ("POST", "/v1/connectors/telegram/webhook"),
    ("GET", "/v1/connectors/whatsapp/webhook"),
    ("POST", "/v1/connectors/whatsapp/webhook"),
}


class ApiTokenGate:
    def __init__(self, app, token: str):
        self.app = app
        self.configured = len(token.encode("utf-8")) >= 32
        self.digest = hashlib.sha256(token.encode("utf-8")).digest()

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        method, path = scope.get("method"), scope.get("path", "")
        if scope["type"] == "http" and (
            (method, path) == ("GET", "/health") or (method, path) in PROVIDER_INGRESS
        ):
            return await self.app(scope, receive, send)
        values = [
            value
            for name, value in scope.get("headers", [])
            if name.lower() == b"x-mica-api-token"
        ]
        authorized = (
            self.configured
            and len(values) == 1
            and hmac.compare_digest(
                self.digest,
                hashlib.sha256(values[0]).digest(),
            )
        )
        if authorized:
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send(
                {
                    "type": "websocket.close",
                    "code": 1008,
                    "reason": "API authentication required",
                }
            )
        response = JSONResponse(
            {
                "detail": "API authentication required"
                if self.configured
                else "API authentication is not configured"
            },
            status_code=401 if self.configured else 503,
        )
        await response(scope, receive, send)
