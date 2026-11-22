"""Domain exceptions and RFC 7807 (application/problem+json) error responses.

Every service returns errors in the same shape, always including the
correlation id so a support engineer can jump straight to the trace.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from orderflow_common.context import get_correlation_id
from orderflow_common.logging import get_logger

logger = get_logger(__name__)

PROBLEM_JSON = "application/problem+json"


class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"
    title: str = "Internal Server Error"

    def __init__(
        self,
        detail: str | None = None,
        *,
        extra: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.extra = extra or {}
        self.headers = headers


class BadRequestError(AppError):
    status_code, code, title = 400, "bad_request", "Bad Request"


class UnauthorizedError(AppError):
    status_code, code, title = 401, "unauthorized", "Unauthorized"

    def __init__(self, detail: str | None = None, **kwargs: Any) -> None:
        kwargs.setdefault("headers", {"WWW-Authenticate": "Bearer"})
        super().__init__(detail, **kwargs)


class ForbiddenError(AppError):
    status_code, code, title = 403, "forbidden", "Forbidden"


class NotFoundError(AppError):
    status_code, code, title = 404, "not_found", "Not Found"


class ConflictError(AppError):
    status_code, code, title = 409, "conflict", "Conflict"


def problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"urn:orderflow:error:{code}",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
        "correlation_id": get_correlation_id(),
    }
    if extra:
        body.update(extra)
    return JSONResponse(
        jsonable_encoder(body), status_code=status, media_type=PROBLEM_JSON, headers=headers
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("app_error", code=exc.code, detail=exc.detail)
        return problem_response(
            request,
            status=exc.status_code,
            code=exc.code,
            title=exc.title,
            detail=exc.detail,
            extra=exc.extra,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return problem_response(
            request,
            status=422,
            code="validation_error",
            title="Unprocessable Entity",
            detail="Request validation failed",
            extra={"errors": errors},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return problem_response(
            request,
            status=exc.status_code,
            code=f"http_{exc.status_code}",
            title=str(exc.detail) if exc.status_code < 500 else "Server Error",
            detail=str(exc.detail),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Never leak internals to the client; the trace has the stack.
        logger.exception("unhandled_exception", error_type=type(exc).__name__)
        return problem_response(
            request,
            status=500,
            code="internal_error",
            title="Internal Server Error",
            detail="An unexpected error occurred. Quote the correlation_id when reporting it.",
        )
