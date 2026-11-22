"""Kubernetes/Container Apps style health probes.

* `/health/live`  - process is up (liveness probe: restart if it fails)
* `/health/ready` - dependencies reachable (readiness: stop routing traffic)
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from orderflow_common.logging import get_logger

logger = get_logger(__name__)

ReadinessCheck = Callable[[FastAPI], Awaitable[None]]


def build_health_router(checks: Mapping[str, ReadinessCheck], *, timeout: float = 3.0) -> APIRouter:
    router = APIRouter(prefix="/health", tags=["health"])

    @router.get("/live", summary="Liveness probe")
    async def live(request: Request) -> dict[str, str]:
        settings = request.app.state.settings
        return {
            "status": "ok",
            "service": settings.service_name,
            "version": settings.service_version,
        }

    @router.get("/ready", summary="Readiness probe")
    async def ready(request: Request) -> JSONResponse:
        results: dict[str, str] = {}
        healthy = True
        for name, check in checks.items():
            try:
                await asyncio.wait_for(check(request.app), timeout=timeout)
                results[name] = "ok"
            except Exception as exc:
                healthy = False
                results[name] = f"error: {type(exc).__name__}"
                logger.warning("readiness_check_failed", check=name, error=str(exc))
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={"status": "ok" if healthy else "unavailable", "checks": results},
        )

    return router
