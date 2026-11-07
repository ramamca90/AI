"""SQS adapter. boto3 is synchronous, so every call runs in a worker thread.

Dead-letter handling is SQS's job, not this code's. Attach a redrive policy to the queue
(`deadLetterTargetArn`, `maxReceiveCount`). A message is deleted only after its handler
returns, so a failing job and a malformed body both reappear after the visibility timeout,
and SQS moves them to the DLQ once `maxReceiveCount` is reached. Nothing is dropped silently,
and a bad message stays available for inspection.

Set the queue's visibility timeout above the longest expected job. Exceeding it is safe but
wasteful: the redelivered copy loses the handler's compare-and-set and becomes a no-op.

On cancellation an in-flight `receive_message` thread can't be interrupted, so process exit
can wait up to `wait_seconds`. Anything that call receives simply reappears later. Give the
container a stop timeout above `wait_seconds` plus `grace_seconds`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import boto3  # type: ignore[import-untyped]
import structlog
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]
from pydantic import ValidationError

from copilot.domain.models import Job
from copilot.queue.base import JobPool

log = structlog.get_logger(__name__)

Handler = Callable[[Job], Awaitable[None]]

_MAX_BATCH = 10  # The SQS limit for one receive.


class SQSQueue:
    def __init__(
        self,
        queue_url: str,
        region: str,
        *,
        client: Any | None = None,
        wait_seconds: int = 20,
        concurrency: int = 4,
        grace_seconds: float = 90.0,
        error_backoff_seconds: float = 5.0,
    ) -> None:
        self._queue_url = queue_url
        self._client = client or boto3.client("sqs", region_name=region)
        self._wait_seconds = wait_seconds
        self._concurrency = concurrency
        self._grace_seconds = grace_seconds
        self._error_backoff_seconds = error_backoff_seconds

    async def enqueue(self, job: Job) -> None:
        await asyncio.to_thread(
            self._client.send_message,
            QueueUrl=self._queue_url,
            MessageBody=job.model_dump_json(),
        )

    async def consume(self, handler: Handler) -> None:
        pool = JobPool(self._concurrency, self._grace_seconds)
        try:
            while True:
                free_slots = await pool.wait_for_capacity()
                try:
                    messages = await self._receive(min(free_slots, _MAX_BATCH))
                except (BotoCoreError, ClientError):
                    log.exception("queue.sqs_receive_failed")
                    await asyncio.sleep(self._error_backoff_seconds)
                    continue
                for message in messages:
                    pool.spawn(self._process(message, handler))
        finally:
            await pool.drain()

    async def _receive(self, max_messages: int) -> list[dict[str, Any]]:
        response = await asyncio.to_thread(
            self._client.receive_message,
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=self._wait_seconds,
        )
        messages: list[dict[str, Any]] = response.get("Messages", [])
        return messages

    async def _process(self, message: dict[str, Any], handler: Handler) -> None:
        message_id = message.get("MessageId")
        try:
            job = Job.model_validate_json(message["Body"])
        except (KeyError, ValidationError):
            # Left on the queue on purpose: the redrive policy carries it to the DLQ.
            log.warning("queue.sqs_malformed_message", message_id=message_id)
            return
        try:
            await handler(job)
        except Exception:
            log.exception(
                "queue.sqs_job_failed",
                message_id=message_id,
                job=job.kind,
                incident_id=job.incident_id,
            )
            return
        await self._delete(message)

    async def _delete(self, message: dict[str, Any]) -> None:
        try:
            await asyncio.to_thread(
                self._client.delete_message,
                QueueUrl=self._queue_url,
                ReceiptHandle=message["ReceiptHandle"],
            )
        except (BotoCoreError, ClientError):
            # The job is done, and the redelivered copy will be a no-op.
            log.exception("queue.sqs_delete_failed", message_id=message.get("MessageId"))
