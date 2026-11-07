from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable, Iterator

import pytest

from copilot.config import Settings
from copilot.domain.models import Job, JobKind
from copilot.observability import configure_tracing, get_tracer
from copilot.queue import LocalQueue
from copilot.worker import main as worker_main
from copilot.worker.main import install_stop_signals, serve


@pytest.fixture
def restore_signals() -> Iterator[None]:
    saved = {signum: signal.getsignal(signum) for signum in (signal.SIGTERM, signal.SIGINT)}
    yield
    for signum, handler in saved.items():
        signal.signal(signum, handler)


@pytest.mark.usefixtures("restore_signals")
async def test_sigterm_sets_the_stop_event() -> None:
    stop = asyncio.Event()
    install_stop_signals(stop)

    signal.raise_signal(signal.SIGTERM)

    await asyncio.wait_for(stop.wait(), timeout=5)


class _QueueThatStopsTheProcess(LocalQueue):
    """Delivers one job, then raises SIGTERM while the job is still running."""

    def __init__(self) -> None:
        super().__init__()
        self.job_finished = False

    async def consume(self, handler: Callable[[Job], Awaitable[None]]) -> None:
        release = asyncio.Event()

        async def in_flight(_job: Job) -> None:
            signal.raise_signal(signal.SIGTERM)
            # Finishing only after shutdown began proves that serve() drains.
            await asyncio.sleep(0)
            release.set()
            self.job_finished = True

        await self.enqueue(Job(kind=JobKind.INVESTIGATE, incident_id="i"))
        await super().consume(in_flight)
        assert release.is_set()


@pytest.mark.usefixtures("restore_signals")
async def test_serve_shuts_down_cleanly_on_sigterm(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = _QueueThatStopsTheProcess()
    monkeypatch.setattr(worker_main, "build_queue", lambda _settings: queue)

    await asyncio.wait_for(serve(settings), timeout=10)

    assert queue.job_finished is True


def test_the_worker_refuses_the_in_process_queue(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker_main, "get_settings", lambda: settings)
    monkeypatch.setattr(worker_main, "configure_logging", lambda _level: None)
    monkeypatch.setattr(worker_main, "configure_tracing", lambda _name: None)
    with pytest.raises(SystemExit, match="QUEUE_BACKEND=local"):
        worker_main.run()


def test_job_spans_work_without_an_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_TRACES_EXPORTER", raising=False)
    configure_tracing("test")
    with get_tracer().start_as_current_span("job.test") as span:
        span.set_attribute("incident.id", "i")
