"""One function that turns business routers into a production-ready service.

Every service gets the same: logging, telemetry, middleware, error format,
health probes, DB pool, event bus and graceful shutdown. Consistency across
services is what makes a fleet operable.
"""

from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from orderflow_common.config import ServiceSettings
from orderflow_common.db import Database
from orderflow_common.errors import register_exception_handlers
from orderflow_common.events import build_event_bus
from orderflow_common.health import build_health_router
from orderflow_common.logging import configure_logging, get_logger
from orderflow_common.middleware import RequestContextMiddleware
from orderflow_common.security import TokenService
from orderflow_common.telemetry import configure_telemetry

logger = get_logger(__name__)

BackgroundLifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


async def _check_database(app: FastAPI) -> None:
    await app.state.db.ping()


async def _check_event_bus(app: FastAPI) -> None:
    await app.state.event_bus.ping()


def create_service_app(
    settings: ServiceSettings,
    *,
    title: str,
    description: str,
    routers: Sequence[APIRouter],
    background: BackgroundLifespan | None = None,
) -> FastAPI:
    configure_logging(
        level=settings.log_level,
        json_logs=settings.log_json,
        service_name=settings.service_name,
        environment=settings.environment.value,
    )
    telemetry_enabled = configure_telemetry(settings)  # before FastAPI() is constructed

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(
            settings.database_url,
            echo=settings.db_echo,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
        )
        if telemetry_enabled:
            try:  # optional extra: per-query spans in Application Insights
                from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

                SQLAlchemyInstrumentor().instrument(engine=db.engine.sync_engine)
            except ImportError:
                logger.info("sqlalchemy_instrumentation_unavailable")
        event_bus = build_event_bus(settings)
        await event_bus.start()

        app.state.settings = settings
        app.state.db = db
        app.state.event_bus = event_bus
        app.state.token_service = TokenService(settings)
        logger.info(
            "service_started",
            version=settings.service_version,
            event_bus=settings.event_bus_backend.value,
        )
        try:
            if background is not None:
                async with background(app):
                    yield
            else:
                yield
        finally:
            logger.info("service_stopping")
            await event_bus.close()
            await db.dispose()

    app = FastAPI(
        title=title,
        description=description,
        version=settings.service_version,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        swagger_ui_parameters={"persistAuthorization": True},
    )
    app.state.settings = settings

    if settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Correlation-ID"],
        )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(RequestContextMiddleware)  # added last => outermost

    register_exception_handlers(app)
    app.include_router(
        build_health_router({"database": _check_database, "event_bus": _check_event_bus})
    )
    for router in routers:
        app.include_router(router)
    return app
