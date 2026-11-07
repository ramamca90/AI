"""Every error response has the same shape: {"error": {code, message, request_id}}."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

log = structlog.get_logger(__name__)

_CODES = {
    400: "bad_request",
    401: "unauthorized",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    503: "unavailable",
}


class ApiError(Exception):
    def __init__(self, status: int, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code or _CODES.get(status, "error")


def _request_id(request: Request) -> str | None:
    request_id: str | None = getattr(request.state, "request_id", None)
    return request_id


def _body(request: Request, code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": _request_id(request),
            **extra,
        }
    }


async def _api_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, ApiError)
    return JSONResponse(_body(request, error.code, error.message), status_code=error.status)


async def _http_exception(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, HTTPException)
    code = _CODES.get(error.status_code, "error")
    return JSONResponse(
        _body(request, code, str(error.detail)),
        status_code=error.status_code,
        headers=error.headers,
    )


async def _validation_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, RequestValidationError)
    # Location and reason only. Pydantic's `input` would echo the request body back.
    details = [
        {"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
        for item in error.errors()
    ]
    body = _body(request, "validation_error", "Invalid request.", details=details)
    return JSONResponse(body, status_code=422)


async def _unhandled(request: Request, error: Exception) -> JSONResponse:
    log.error("api.unhandled_exception", path=request.url.path, exc_info=error)
    response = JSONResponse(
        _body(request, "internal_error", "Internal server error."), status_code=500
    )
    # This handler runs outside the middleware stack, so the request-ID header isn't added.
    request_id = _request_id(request)
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(HTTPException, _http_exception)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled)
