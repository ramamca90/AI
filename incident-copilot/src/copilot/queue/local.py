"""In-process queue for local runs and tests. Jobs do not survive a restart."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog

from copilot.domain.models import Job
from copilot.queue.base import JobPool

log = structlog.get_logger(__name__)

Handler = Callable[[Job], Awaitable[None]]


@dataclass
class _Delivery:
    job: Job
    attempt: int = 1


class LocalQueue:
    """Retries a failing job, then parks it in `dead_letters`, the local stand-in for a DLQ."""

    def __init__(
        self,
        *,
        max_attempts: int = 3,
        retry_delay_seconds: float = 1.0,
        concurrency: int = 4,
        grace_seconds: float = 30.0,
    ) -> None:
        self._queue: asyncio.Queue[_Delivery] = asyncio.Queue()
        self._max_attempts = max_attempts
        self._retry_delay_seconds = retry_delay_seconds
        self._concurrency = concurrency
        self._grace_seconds = grace_seconds
        self.dead_letters: list[Job] = []

    async def enqueue(self, job: Job) -> None:
        self._queue.put_nowait(_Delivery(job))

    async def join(self) -> None:
        """Wait until every enqueued job has finished or been parked."""
        await self._queue.join()

    async def consume(self, handler: Handler) -> None:
        pool = JobPool(self._concurrency, self._grace_seconds)
        try:
            while True:
                await pool.wait_for_capacity()
                delivery = await self._queue.get()
                pool.spawn(self._deliver(delivery, handler))
        finally:
            await pool.drain()

    async def _deliver(self, delivery: _Delivery, handler: Handler) -> None:
        try:
            await handler(delivery.job)
        except Exception:
            await self._retry_or_park(delivery)
        finally:
            self._queue.task_done()

    async def _retry_or_park(self, delivery: _Delivery) -> None:
        job = delivery.job
        if delivery.attempt >= self._max_attempts:
            log.exception("queue.job_dead_lettered", job=job.kind, incident_id=job.incident_id)
            self.dead_letters.append(job)
            return
        log.warning(
            "queue.job_retrying",
            job=job.kind,
            incident_id=job.incident_id,
            attempt=delivery.attempt,
            exc_info=True,
        )
        await asyncio.sleep(self._retry_delay_seconds * delivery.attempt)
        # Queued before this delivery's task_done runs, so join() can't return early.
        self._queue.put_nowait(_Delivery(job, delivery.attempt + 1))
