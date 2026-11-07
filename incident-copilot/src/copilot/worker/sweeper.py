"""Recovers incidents that no job will ever move again.

Compare-and-set makes redelivery harmless, but it also means a redelivered job can't finish
what a crashed worker started: it sees `investigating` and does nothing. Without this sweep
that incident would hold its fingerprint forever and swallow every later alert as a duplicate.

Events bump `updated_at`, so a running job heartbeats just by working. Running this from
several workers at once is safe, because each step is a compare-and-set or an idempotent job.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import structlog

from copilot.db.repository import Repository
from copilot.domain.models import IncidentStatus, Job, JobKind, utcnow
from copilot.domain.ports import JobQueue

log = structlog.get_logger(__name__)

SWEEP_INTERVAL_SECONDS = 60.0
STALE_RUNNING_AFTER = timedelta(minutes=15)
STALE_QUEUED_AFTER = timedelta(minutes=5)

_WORKER_LOST = "The worker stopped responding. Verify the service state before retrying."


async def sweep_once(repository: Repository, queue: JobQueue) -> None:
    now = utcnow()
    running = await repository.stale_incidents(
        (IncidentStatus.INVESTIGATING, IncidentStatus.REMEDIATING), now - STALE_RUNNING_AFTER
    )
    for incident in running:
        log.error("sweeper.failing_stale", incident_id=incident.id, status=incident.status.value)
        await repository.fail_incident(incident.id, (incident.status,), _WORKER_LOST)

    # A queued incident may have lost its job: a crash just after commit, or a local queue
    # that restarted. Enqueueing again is safe because the handler is a no-op on duplicates.
    queued = await repository.stale_incidents((IncidentStatus.QUEUED,), now - STALE_QUEUED_AFTER)
    for incident in queued:
        log.warning("sweeper.requeueing", incident_id=incident.id)
        await repository.touch_incident(incident.id)
        await queue.enqueue(Job(kind=JobKind.INVESTIGATE, incident_id=incident.id))


async def run_sweeper(
    repository: Repository,
    queue: JobQueue,
    interval_seconds: float = SWEEP_INTERVAL_SECONDS,
) -> None:
    while True:
        try:
            await sweep_once(repository, queue)
        except Exception:
            log.exception("sweeper.failed")
        await asyncio.sleep(interval_seconds)
