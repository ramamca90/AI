"""Bounded concurrency and draining, shared by both queue adapters."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import structlog

log = structlog.get_logger(__name__)


class JobPool:
    """Runs jobs as tasks, at most `concurrency` at once.

    Jobs run side by side so one long investigation can't delay an approved remediation.
    `drain` is the graceful half of shutdown: in-flight jobs get `grace_seconds` to finish,
    and the rest are cancelled so their handlers can clean up.
    """

    def __init__(self, concurrency: int, grace_seconds: float) -> None:
        self._concurrency = concurrency
        self._grace_seconds = grace_seconds
        self._tasks: set[asyncio.Task[None]] = set()
        self._capacity_freed = asyncio.Event()

    async def wait_for_capacity(self) -> int:
        """Wait for a free slot and return how many are free. Only the consumer loop spawns,
        so that number can only grow until the loop next calls `spawn`."""
        while len(self._tasks) >= self._concurrency:
            self._capacity_freed.clear()
            await self._capacity_freed.wait()
        return self._concurrency - len(self._tasks)

    def spawn(self, job: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(job)
        self._tasks.add(task)
        task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        self._capacity_freed.set()
        if not task.cancelled() and task.exception() is not None:
            log.error("queue.job_task_crashed", exc_info=task.exception())

    async def drain(self) -> None:
        if not self._tasks:
            return
        tasks = set(self._tasks)
        log.info("queue.draining", in_flight=len(tasks), grace_seconds=self._grace_seconds)
        _, pending = await asyncio.wait(tasks, timeout=self._grace_seconds)
        if pending:
            log.warning("queue.drain_cancelling", jobs=len(pending))
            for task in pending:
                task.cancel()
            await asyncio.wait(pending)
