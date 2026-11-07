from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from copilot.config import Settings
from copilot.domain.models import Job, JobKind
from copilot.queue import LocalQueue, SQSQueue, build_queue

REGION = "us-east-1"
JOB = Job(kind=JobKind.INVESTIGATE, incident_id="i-1")


async def run_until(
    queue: Any, handler: Callable[[Job], Awaitable[None]], done: asyncio.Event
) -> None:
    consumer = asyncio.create_task(queue.consume(handler))
    await asyncio.wait_for(done.wait(), timeout=10)
    consumer.cancel()
    await asyncio.gather(consumer, return_exceptions=True)


# LocalQueue


async def test_local_queue_delivers_a_job() -> None:
    queue = LocalQueue()
    seen: list[Job] = []
    done = asyncio.Event()

    async def handler(job: Job) -> None:
        seen.append(job)
        done.set()

    await queue.enqueue(JOB)
    await run_until(queue, handler, done)
    assert seen == [JOB]


async def test_local_queue_retries_then_succeeds() -> None:
    queue = LocalQueue(max_attempts=3, retry_delay_seconds=0)
    attempts = 0
    done = asyncio.Event()

    async def handler(_job: Job) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("flaky")
        done.set()

    await queue.enqueue(JOB)
    await run_until(queue, handler, done)
    assert attempts == 3
    assert queue.dead_letters == []


async def test_local_queue_parks_a_job_after_its_attempts_run_out() -> None:
    queue = LocalQueue(max_attempts=2, retry_delay_seconds=0)
    attempts = 0

    async def handler(_job: Job) -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("always")

    await queue.enqueue(JOB)
    consumer = asyncio.create_task(queue.consume(handler))
    await queue.join()
    consumer.cancel()
    await asyncio.gather(consumer, return_exceptions=True)
    assert attempts == 2
    assert queue.dead_letters == [JOB]


async def test_local_queue_bounds_concurrency_and_runs_jobs_side_by_side() -> None:
    queue = LocalQueue(concurrency=2)
    release = asyncio.Event()
    running = 0
    peak = 0
    both_started = asyncio.Event()

    async def handler(_job: Job) -> None:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        if running == 2:
            both_started.set()
        await release.wait()
        running -= 1

    for _ in range(4):
        await queue.enqueue(JOB)
    consumer = asyncio.create_task(queue.consume(handler))
    await asyncio.wait_for(both_started.wait(), timeout=5)
    await asyncio.sleep(0)
    release.set()
    await queue.join()
    consumer.cancel()
    await asyncio.gather(consumer, return_exceptions=True)
    assert peak == 2


async def test_cancelling_consume_waits_for_in_flight_jobs() -> None:
    queue = LocalQueue(grace_seconds=5)
    started = asyncio.Event()
    release = asyncio.Event()
    finished = False

    async def handler(_job: Job) -> None:
        nonlocal finished
        started.set()
        await release.wait()
        finished = True

    await queue.enqueue(JOB)
    consumer = asyncio.create_task(queue.consume(handler))
    await started.wait()
    consumer.cancel()
    await asyncio.sleep(0)
    assert not consumer.done()

    release.set()
    await asyncio.gather(consumer, return_exceptions=True)
    assert finished is True


async def test_drain_cancels_jobs_that_outlive_the_grace_period() -> None:
    queue = LocalQueue(grace_seconds=0)
    started = asyncio.Event()
    cancelled = False

    async def handler(_job: Job) -> None:
        nonlocal cancelled
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled = True
            raise

    await queue.enqueue(JOB)
    consumer = asyncio.create_task(queue.consume(handler))
    await started.wait()
    consumer.cancel()
    await asyncio.gather(consumer, return_exceptions=True)
    assert cancelled is True


# SQSQueue


@pytest.fixture
async def sqs() -> AsyncIterator[Any]:
    with mock_aws():
        yield boto3.client(
            "sqs",
            region_name=REGION,
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        )


def make_queue(sqs: Any, name: str = "jobs", **attributes: str) -> str:
    url: str = sqs.create_queue(QueueName=name, Attributes=attributes)["QueueUrl"]
    return url


def approximate_count(sqs: Any, url: str) -> tuple[int, int]:
    attributes = sqs.get_queue_attributes(
        QueueUrl=url,
        AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
    )["Attributes"]
    return (
        int(attributes["ApproximateNumberOfMessages"]),
        int(attributes["ApproximateNumberOfMessagesNotVisible"]),
    )


def adapter(sqs: Any, url: str, **options: Any) -> SQSQueue:
    return SQSQueue(url, REGION, client=sqs, wait_seconds=0, **options)


async def test_sqs_round_trip_deletes_after_the_handler_succeeds(sqs: Any) -> None:
    url = make_queue(sqs)
    queue = adapter(sqs, url)
    seen: list[Job] = []
    finished = asyncio.Event()

    async def handler(job: Job) -> None:
        seen.append(job)
        # Still in flight here: the delete hasn't happened yet.
        assert approximate_count(sqs, url) == (0, 1)
        finished.set()

    await queue.enqueue(JOB)
    await run_until(queue, handler, finished)

    assert seen == [JOB]
    assert approximate_count(sqs, url) == (0, 0)


async def test_sqs_message_stays_on_the_queue_when_the_handler_fails(sqs: Any) -> None:
    url = make_queue(sqs, VisibilityTimeout="60")
    queue = adapter(sqs, url)
    failed = asyncio.Event()

    async def handler(_job: Job) -> None:
        failed.set()
        raise RuntimeError("job failed")

    await queue.enqueue(JOB)
    await run_until(queue, handler, failed)

    assert approximate_count(sqs, url) == (0, 1)


async def test_sqs_malformed_messages_do_not_stop_the_loop(sqs: Any) -> None:
    url = make_queue(sqs, VisibilityTimeout="60")
    queue = adapter(sqs, url)
    sqs.send_message(QueueUrl=url, MessageBody="not json")
    sqs.send_message(QueueUrl=url, MessageBody=json.dumps({"kind": "unknown"}))
    await queue.enqueue(JOB)
    seen: list[Job] = []
    done = asyncio.Event()

    async def handler(job: Job) -> None:
        seen.append(job)
        done.set()

    await run_until(queue, handler, done)

    assert seen == [JOB]
    # Both bad messages are left in flight for the redrive policy, not deleted.
    assert approximate_count(sqs, url) == (0, 2)


async def test_sqs_redrive_policy_moves_a_poison_message_to_the_dlq(sqs: Any) -> None:
    dlq_url = make_queue(sqs, "jobs-dlq")
    dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])["Attributes"][
        "QueueArn"
    ]
    url = make_queue(
        sqs,
        VisibilityTimeout="0",
        RedrivePolicy=json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": 2}),
    )
    sqs.send_message(QueueUrl=url, MessageBody="not json")
    queue = adapter(sqs, url)
    deadline = asyncio.get_running_loop().time() + 10

    async def handler(_job: Job) -> None:
        raise AssertionError("a malformed message must not reach the handler")

    consumer = asyncio.create_task(queue.consume(handler))
    while approximate_count(sqs, dlq_url)[0] == 0:
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0.01)
    consumer.cancel()
    await asyncio.gather(consumer, return_exceptions=True)

    assert approximate_count(sqs, dlq_url) == (1, 0)


async def test_sqs_receive_errors_are_survived(sqs: Any) -> None:
    url = make_queue(sqs)
    await adapter(sqs, url).enqueue(JOB)
    real_receive = sqs.receive_message
    calls = 0

    def flaky_receive(**kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ClientError({"Error": {"Code": "ServiceUnavailable"}}, "ReceiveMessage")
        return real_receive(**kwargs)

    sqs.receive_message = flaky_receive
    queue = adapter(sqs, url, error_backoff_seconds=0)
    done = asyncio.Event()

    async def handler(_job: Job) -> None:
        done.set()

    await run_until(queue, handler, done)
    assert calls >= 2


async def test_sqs_delete_failure_does_not_stop_the_loop(sqs: Any) -> None:
    url = make_queue(sqs, VisibilityTimeout="60")
    queue = adapter(sqs, url)
    await queue.enqueue(JOB)
    await queue.enqueue(Job(kind=JobKind.INVESTIGATE, incident_id="i-2"))

    def failing_delete(**_kwargs: Any) -> None:
        raise ClientError({"Error": {"Code": "InternalError"}}, "DeleteMessage")

    sqs.delete_message = failing_delete
    seen: list[str] = []
    done = asyncio.Event()

    async def handler(job: Job) -> None:
        seen.append(job.incident_id)
        if len(seen) == 2:
            done.set()

    await run_until(queue, handler, done)
    assert sorted(seen) == ["i-1", "i-2"]


async def test_sqs_uses_long_polling_by_default() -> None:
    calls: list[dict[str, Any]] = []
    done = asyncio.Event()

    class StubClient:
        def receive_message(self, **kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            done.set()
            return {}

    queue = SQSQueue("url", REGION, client=StubClient())

    async def handler(_job: Job) -> None:
        raise AssertionError

    await run_until(queue, handler, done)
    assert calls[0]["WaitTimeSeconds"] == 20


# Factory


def test_factory_builds_a_local_queue() -> None:
    settings = Settings(_env_file=None, queue_backend="local")  # type: ignore[call-arg]
    assert isinstance(build_queue(settings), LocalQueue)


def test_factory_builds_an_sqs_queue() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        queue_backend="sqs",
        sqs_queue_url="https://sqs.example/jobs",
    )
    with mock_aws():
        assert isinstance(build_queue(settings), SQSQueue)


def test_factory_requires_a_queue_url_for_sqs() -> None:
    settings = Settings(_env_file=None, queue_backend="sqs")  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="SQS_QUEUE_URL"):
        build_queue(settings)
