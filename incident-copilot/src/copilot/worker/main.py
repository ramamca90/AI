"""`copilot-worker` entry point: consume jobs until told to stop."""

from __future__ import annotations

import asyncio
import os
import signal
import sys

import structlog
from prometheus_client import start_http_server

from copilot.config import Settings, get_settings
from copilot.db import Repository, create_engine, create_session_factory, init_schema
from copilot.observability import configure_logging, configure_tracing
from copilot.queue import build_queue
from copilot.worker.handlers import JobHandlers
from copilot.worker.runtime import default_rejection_errors, default_runtime_factory
from copilot.worker.sweeper import run_sweeper

log = structlog.get_logger(__name__)

_DEFAULT_METRICS_PORT = 9100


def install_stop_signals(stop: asyncio.Event) -> None:
    """Set `stop` on SIGTERM or SIGINT, plus Ctrl+Break on Windows.

    `loop.add_signal_handler` isn't implemented on the Windows event loop. There, the plain
    `signal` handler can run between loop iterations, so it must hop back onto the loop
    instead of touching the event directly.
    """
    loop = asyncio.get_running_loop()
    signals = [signal.SIGTERM, signal.SIGINT]
    if sys.platform == "win32":
        signals.append(signal.SIGBREAK)
    for signum in signals:
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:
            signal.signal(signum, lambda *_: loop.call_soon_threadsafe(stop.set))


async def serve(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    await init_schema(engine)
    repository = Repository(create_session_factory(engine))
    queue = build_queue(settings)
    handlers = JobHandlers(
        repository, settings, default_runtime_factory, default_rejection_errors()
    )

    stop = asyncio.Event()
    install_stop_signals(stop)
    consumer = asyncio.create_task(queue.consume(handlers.handle))
    sweeper = asyncio.create_task(run_sweeper(repository, queue))
    stopping = asyncio.create_task(stop.wait())
    log.info("worker.started", queue=settings.queue_backend)

    await asyncio.wait({consumer, stopping}, return_when=asyncio.FIRST_COMPLETED)
    log.info("worker.stopping")
    stopping.cancel()
    sweeper.cancel()
    consumer.cancel()  # consume() drains in-flight jobs before this task finishes.
    results = await asyncio.gather(consumer, sweeper, return_exceptions=True)
    await engine.dispose()
    log.info("worker.stopped")
    for result in results:
        if isinstance(result, Exception):
            raise result


def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_tracing("copilot-worker")
    if settings.queue_backend == "local":
        # A LocalQueue lives inside one process, so this worker would never see the API's jobs.
        raise SystemExit(
            "QUEUE_BACKEND=local runs the worker inside copilot-api. "
            "Use QUEUE_BACKEND=sqs to run copilot-worker separately."
        )
    metrics_port = int(os.environ.get("WORKER_METRICS_PORT", _DEFAULT_METRICS_PORT))
    if metrics_port:
        start_http_server(metrics_port)
    asyncio.run(serve(settings))
