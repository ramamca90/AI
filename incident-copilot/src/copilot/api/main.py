"""`copilot-api` entry point."""

from __future__ import annotations

import os

import uvicorn

from copilot.api.app import create_app
from copilot.config import get_settings
from copilot.observability import configure_logging, configure_tracing

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000
# Open SSE streams would otherwise hold up shutdown until every client leaves.
_GRACEFUL_SHUTDOWN_SECONDS = 10


def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_tracing("copilot-api")
    uvicorn.run(
        create_app(settings),
        host=os.environ.get("API_HOST", _DEFAULT_HOST),
        port=int(os.environ.get("API_PORT", _DEFAULT_PORT)),
        log_config=None,
        timeout_graceful_shutdown=_GRACEFUL_SHUTDOWN_SECONDS,
    )
