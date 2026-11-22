"""Pure-ASGI request middleware (no BaseHTTPMiddleware overhead).

* Accepts or generates an `X-Correlation-ID` and echoes it on the response.
* Emits one structured access-log line per request with latency.
* Adds baseline security headers.
"""

import re
import time
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from orderflow_common.context import correlation_id_var
from orderflow_common.logging import get_logger

CORRELATION_HEADER = "X-Correlation-ID"
_VALID_ID = re.compile(r"^[A-Za-z0-9._\-]{8,128}$")
_QUIET_PATHS = ("/health/",)

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

logger = get_logger("orderflow.access")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        incoming = headers.get(CORRELATION_HEADER) or headers.get("X-Request-ID")
        correlation_id = incoming if incoming and _VALID_ID.match(incoming) else uuid.uuid4().hex

        structlog.contextvars.clear_contextvars()
        token = correlation_id_var.set(correlation_id)
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = MutableHeaders(scope=message)
                response_headers[CORRELATION_HEADER] = correlation_id
                for key, value in _SECURITY_HEADERS.items():
                    response_headers.setdefault(key, value)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope.get("path", "")
            log = logger.debug if path.startswith(_QUIET_PATHS) else logger.info
            log(
                "http_request",
                method=scope.get("method"),
                path=path,
                status=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                client=(scope.get("client") or ("-",))[0],
            )
            correlation_id_var.reset(token)
