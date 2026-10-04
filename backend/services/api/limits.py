"""Global request-body bound for the local API.

Handlers such as connector webhooks and voice already carry their own exact
limits. This middleware is the transport backstop: without it a single
authenticated request could pin arbitrarily large memory before any handler,
schema or policy check runs.

Declared lengths are rejected up front. Bodies without a ``Content-Length``
(chunked uploads) are buffered under the same bound and replayed, because an
exception raised from the receive channel would be converted by the framework
into a misleading 400 instead of a 413.
"""
from __future__ import annotations

from starlette.responses import JSONResponse


DEFAULT_MAX_REQUEST_BYTES = 16 * 1024 * 1024

# Desktop backup restore uploads are separately capped at 64 MB by the
# maintenance router, so their documented transport limit is larger.
OVERRIDES = {
    "/v1/backups/restore": 64 * 1024 * 1024,
}


class RequestSizeLimit:
    """Reject oversized HTTP bodies before handlers or Pydantic read them."""

    def __init__(self, app, maximum: int | None = None):
        self.app = app
        self.maximum = maximum if isinstance(maximum, int) and maximum > 0 else DEFAULT_MAX_REQUEST_BYTES

    def _limit_for(self, path: str) -> int:
        return max(self.maximum, OVERRIDES.get(path, 0))

    @staticmethod
    def _declared_length(scope) -> int | None:
        """Return the declared body length, or None when the request is chunked."""
        declared = None
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                declared = max(declared or 0, int(value))  # raises ValueError
        return declared

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self._limit_for(scope.get("path", ""))
        try:
            declared = self._declared_length(scope)
        except ValueError:
            return await self._reject(scope, receive, send, "Invalid Content-Length", 400)
        if declared is not None:
            if declared > limit:
                return await self._reject(scope, receive, send, "Request body too large", 413)
            # Framing guarantees the delivered body matches the declared length.
            return await self.app(scope, receive, send)
        body = await self._buffered_body(receive, limit)
        if body is None:
            return await self._reject(scope, receive, send, "Request body too large", 413)
        return await self.app(scope, self._replayed(body, receive), send)

    @staticmethod
    async def _buffered_body(receive, limit: int) -> bytes | None:
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return None
            if message["type"] != "http.request":
                continue
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > limit:
                return None
            chunks.append(chunk)
            if not message.get("more_body", False):
                return b"".join(chunks)

    @staticmethod
    def _replayed(body: bytes, receive):
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        return replay

    @staticmethod
    async def _reject(scope, receive, send, detail: str, status: int):
        response = JSONResponse({"detail": detail}, status_code=status)
        await response(scope, receive, send)
