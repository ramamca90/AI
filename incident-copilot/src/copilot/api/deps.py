"""Request dependencies: the shared services and API key authentication."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader

from copilot.api.errors import ApiError
from copilot.config import Settings
from copilot.db import Repository
from copilot.domain.ports import JobQueue


@dataclass(frozen=True)
class Services:
    settings: Settings
    repository: Repository
    queue: JobQueue
    sse_poll_seconds: float


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


ServicesDep = Annotated[Services, Depends(get_services)]

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    services: ServicesDep,
    provided: Annotated[str | None, Security(_api_key_header)],
) -> None:
    expected = services.settings.api_key.get_secret_value()
    # Bytes, because compare_digest raises TypeError on non-ASCII str and headers may hold it.
    if provided is None or not secrets.compare_digest(provided.encode(), expected.encode()):
        raise ApiError(401, "Missing or invalid API key.")
