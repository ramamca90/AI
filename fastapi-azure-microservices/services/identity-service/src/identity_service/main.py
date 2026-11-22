"""ASGI entrypoint: `uvicorn identity_service.main:create_app --factory`."""

from fastapi import FastAPI

from identity_service.api import router
from identity_service.config import IdentitySettings, get_settings
from orderflow_common.app_factory import create_service_app


def create_app(settings: IdentitySettings | None = None) -> FastAPI:
    return create_service_app(
        settings or get_settings(),
        title="OrderFlow Identity Service",
        description="User registration and JWT access-token issuing.",
        routers=[router],
    )
