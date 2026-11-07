"""Chooses the queue implementation from settings."""

from __future__ import annotations

from copilot.config import Settings
from copilot.domain.ports import JobQueue
from copilot.queue.local import LocalQueue
from copilot.queue.sqs import SQSQueue

# Local runs stop on Ctrl+C, where a long wait for in-flight jobs is just annoying.
_LOCAL_GRACE_SECONDS = 5.0


def build_queue(settings: Settings) -> JobQueue:
    if settings.queue_backend == "local":
        return LocalQueue(grace_seconds=_LOCAL_GRACE_SECONDS)
    if not settings.sqs_queue_url:
        raise ValueError("QUEUE_BACKEND=sqs requires SQS_QUEUE_URL")
    return SQSQueue(settings.sqs_queue_url, settings.aws_region)
