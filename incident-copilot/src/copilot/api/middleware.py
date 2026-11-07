"""Request-ID middleware.

Plain ASGI rather than BaseHTTPMiddleware, which wraps the response stream and interferes
with SSE and with disconnect detection.
"""

from __future__ import annotations

import re

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from structlog.contextvars import bound_contextvars

from copilot.domain.models import new_id

HEADER = "X-Request-ID"
# A caller's ID is kept for tracing across systems, but it also lands in the logs and in a
# response header, so anything beyond plain tokens is replaced.
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(HEADER, "")
        request_id = incoming if _SAFE_REQUEST_ID.fullmatch(incoming) else new_id()
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[HEADER] = request_id
            await send(message)

        with bound_contextvars(request_id=request_id):
            await self._app(scope, receive, send_with_request_id)
