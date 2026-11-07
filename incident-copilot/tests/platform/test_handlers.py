from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from prometheus_client import REGISTRY
from tests.platform.support import (
    FakeRuntime,
    RejectedError,
    make_alert,
    make_result,
    seed_incident,
)

from copilot.db import Repository
from copilot.domain.models import (
    EventType,
    IncidentStatus,
    Job,
    JobKind,
    ProposalStatus,
    utcnow,
)
from copilot.domain.ports import BudgetExceededError, LLMRefusedError
from copilot.queue import LocalQueue
from copilot.worker import sweeper
from copilot.worker.handlers import JobHandlers


def investigate(incident_id: str) -> Job:
    return Job(kind=JobKind.INVESTIGATE, incident_id=incident_id)


def remediate(incident_id: str, proposal_id: str) -> Job:
    return Job(kind=JobKind.REMEDIATE, incident_id=incident_id, proposal_id=proposal_id)


async def approved_proposal(repository: Repository, incident_id: str) -> str:
    proposal = (await repository.list_proposals(incident_id))[0]
    await repository.approve_proposal(incident_id, proposal.id, "ann")
    return proposal.id


async def event_types(repository: Repository, incident_id: str) -> list[EventType]:
    return [stored.event.type for stored in await repository.list_events(incident_id)]


async def test_investigation_saves_the_outcome_and_creates_proposals(
    repository: Repository, handlers: JobHandlers, runtime: FakeRuntime
) -> None:
    incident_id = await seed_incident(repository, handlers)

    incident = await repository.get_incident(incident_id)
    assert incident is not None
    assert incident.status is IncidentStatus.AWAITING_APPROVAL
    assert incident.triage == runtime.result.triage
    assert incident.findings == runtime.result.findings
    assert incident.report == runtime.result.report
    assert incident.usage == runtime.result.usage
    proposals = await repository.list_proposals(incident_id)
    assert [p.draft for p in proposals] == runtime.result.report.remediations
    assert runtime.scenarios == ["bad_deploy"]


async def test_agent_events_are_persisted_as_they_occur(
    repository: Repository, handlers: JobHandlers, runtime: FakeRuntime
) -> None:
    runtime.gate = asyncio.Event()
    incident, _ = await repository.create_incident(make_alert())
    job = asyncio.create_task(handlers.handle(investigate(incident.id)))
    await runtime.started.wait()

    # The job is still running, and its events are already readable from the database.
    assert EventType.TOOL_CALL in await event_types(repository, incident.id)
    assert await repository.get_status(incident.id) is IncidentStatus.INVESTIGATING

    runtime.gate.set()
    await job


async def test_no_remediations_closes_without_action(
    repository: Repository, handlers: JobHandlers, runtime: FakeRuntime
) -> None:
    runtime.result = make_result(remediations=0)
    incident_id = await seed_incident(repository, handlers)
    assert await repository.get_status(incident_id) is IncidentStatus.CLOSED_NO_ACTION
    assert await repository.list_proposals(incident_id) == []


async def test_a_redelivered_investigation_is_a_noop(
    repository: Repository, handlers: JobHandlers, runtime: FakeRuntime
) -> None:
    incident_id = await seed_incident(repository, handlers)
    before = await repository.list_events(incident_id)

    await handlers.handle(investigate(incident_id))

    assert len(runtime.investigate_calls) == 1
    assert await repository.list_events(incident_id) == before
    assert len(await repository.list_proposals(incident_id)) == 1


async def test_a_delivery_racing_the_first_is_a_noop(
    repository: Repository, handlers: JobHandlers, runtime: FakeRuntime
) -> None:
    runtime.gate = asyncio.Event()
    incident, _ = await repository.create_incident(make_alert())
    first = asyncio.create_task(handlers.handle(investigate(incident.id)))
    await runtime.started.wait()

    await handlers.handle(investigate(incident.id))
    runtime.gate.set()
    await first

    assert len(runtime.investigate_calls) == 1
    assert await repository.get_status(incident.id) is IncidentStatus.AWAITING_APPROVAL


async def test_a_job_for_an_unknown_incident_is_a_noop(
    handlers: JobHandlers, runtime: FakeRuntime
) -> None:
    await handlers.handle(investigate("nope"))
    assert runtime.investigate_calls == []


@pytest.mark.parametrize(
    ("error", "expected_text"),
    [
        (BudgetExceededError("spent $9 of $2"), "budget"),
        (LLMRefusedError("refused"), "declined"),
        (RuntimeError("secret token in telemetry"), "internal error"),
    ],
)
async def test_investigation_failures_are_recorded_with_a_safe_message(
    repository: Repository,
    handlers: JobHandlers,
    runtime: FakeRuntime,
    error: Exception,
    expected_text: str,
) -> None:
    runtime.investigate_error = error
    incident_id = await seed_incident(repository, handlers)

    incident = await repository.get_incident(incident_id)
    assert incident is not None
    assert incident.status is IncidentStatus.FAILED
    assert incident.error is not None
    assert expected_text in incident.error
    assert str(error) not in incident.error
    events = await repository.list_events(incident_id)
    errors = [s.event for s in events if s.event.type is EventType.ERROR]
    assert len(errors) == 1
    assert str(error) not in str(errors[0].data)


async def test_a_failed_investigation_keeps_the_partial_result(
    repository: Repository, handlers: JobHandlers, runtime: FakeRuntime
) -> None:
    runtime.investigate_error = BudgetExceededError("over")
    incident_id = await seed_incident(repository, handlers)

    incident = await repository.get_incident(incident_id)
    assert incident is not None
    assert incident.triage == runtime.result.triage
    assert incident.usage.cost_usd == 0.5


async def test_a_failed_runtime_factory_fails_the_incident(
    repository: Repository, settings: object
) -> None:
    def broken_factory(*_: object) -> FakeRuntime:
        raise ValueError("unknown scenario")

    handlers = JobHandlers(repository, settings, broken_factory)  # type: ignore[arg-type]
    incident, _ = await repository.create_incident(make_alert())
    await handlers.handle(investigate(incident.id))
    assert await repository.get_status(incident.id) is IncidentStatus.FAILED


async def test_a_cancelled_investigation_goes_back_to_queued_for_redelivery(
    repository: Repository, handlers: JobHandlers, runtime: FakeRuntime
) -> None:
    runtime.gate = asyncio.Event()
    incident, _ = await repository.create_incident(make_alert())
    job = asyncio.create_task(handlers.handle(investigate(incident.id)))
    await runtime.started.wait()

    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    assert await repository.get_status(incident.id) is IncidentStatus.QUEUED

    runtime.gate.set()
    await handlers.handle(investigate(incident.id))
    assert await repository.get_status(incident.id) is IncidentStatus.AWAITING_APPROVAL


async def test_remediation_executes_and_resolves(
    repository: Repository, handlers: JobHandlers, runtime: FakeRuntime
) -> None:
    incident_id = await seed_incident(repository, handlers)
    proposal_id = await approved_proposal(repository, incident_id)

    await handlers.handle(remediate(incident_id, proposal_id))

    assert runtime.execute_calls == [proposal_id]
    assert await repository.get_status(incident_id) is IncidentStatus.RESOLVED
    proposal = await repository.get_proposal(incident_id, proposal_id)
    assert proposal is not None
    assert proposal.status is ProposalStatus.EXECUTED
    assert proposal.result == "restarted checkout-api"


async def test_a_redelivered_remediation_does_not_execute_twice(
    repository: Repository, handlers: JobHandlers, runtime: FakeRuntime
) -> None:
    incident_id = await seed_incident(repository, handlers)
    proposal_id = await approved_proposal(repository, incident_id)

    await asyncio.gather(*(handlers.handle(remediate(incident_id, proposal_id)) for _ in range(5)))
    await handlers.handle(remediate(incident_id, proposal_id))

    assert runtime.execute_calls == [proposal_id]


async def test_a_remediation_job_for_an_undecided_proposal_does_nothing(
    repository: Repository, handlers: JobHandlers, runtime: FakeRuntime
) -> None:
    incident_id = await seed_incident(repository, handlers)
    proposal = (await repository.list_proposals(incident_id))[0]
    await handlers.handle(remediate(incident_id, proposal.id))
    assert runtime.execute_calls == []
    assert await repository.get_status(incident_id) is IncidentStatus.AWAITING_APPROVAL


async def test_a_remediation_job_without_a_proposal_id_does_nothing(
    handlers: JobHandlers, runtime: FakeRuntime
) -> None:
    await handlers.handle(Job(kind=JobKind.REMEDIATE, incident_id="x"))
    assert runtime.execute_calls == []


async def test_a_rejected_remediation_fails_with_the_validator_message(
    repository: Repository, handlers: JobHandlers, runtime: FakeRuntime
) -> None:
    incident_id = await seed_incident(repository, handlers)
    proposal_id = await approved_proposal(repository, incident_id)
    runtime.execute_error = RejectedError("unknown service 'x'")

    await handlers.handle(remediate(incident_id, proposal_id))

    incident = await repository.get_incident(incident_id)
    proposal = await repository.get_proposal(incident_id, proposal_id)
    assert incident is not None
    assert proposal is not None
    assert incident.status is IncidentStatus.FAILED
    assert proposal.status is ProposalStatus.FAILED
    assert proposal.result == "unknown service 'x'"
    assert EventType.ERROR in await event_types(repository, incident_id)


async def test_a_crashed_remediation_hides_the_exception_text(
    repository: Repository, handlers: JobHandlers, runtime: FakeRuntime
) -> None:
    incident_id = await seed_incident(repository, handlers)
    proposal_id = await approved_proposal(repository, incident_id)
    runtime.execute_error = RuntimeError("password=hunter2")

    await handlers.handle(remediate(incident_id, proposal_id))

    proposal = await repository.get_proposal(incident_id, proposal_id)
    assert proposal is not None
    assert proposal.status is ProposalStatus.FAILED
    assert "hunter2" not in (proposal.result or "")


async def test_a_cancelled_remediation_is_recorded_and_not_retried(
    repository: Repository, handlers: JobHandlers, runtime: FakeRuntime
) -> None:
    incident_id = await seed_incident(repository, handlers)
    proposal_id = await approved_proposal(repository, incident_id)
    runtime.execute_error = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await handlers.handle(remediate(incident_id, proposal_id))

    assert await repository.get_status(incident_id) is IncidentStatus.FAILED
    runtime.execute_error = None
    await handlers.handle(remediate(incident_id, proposal_id))
    assert runtime.execute_calls == [proposal_id]


async def test_metrics_count_usage_tool_calls_and_guardrails(
    repository: Repository, handlers: JobHandlers
) -> None:
    def sample(name: str, **labels: str) -> float:
        return REGISTRY.get_sample_value(name, labels) or 0.0

    tools = sample("copilot_tool_calls_total", tool="search_logs")
    guardrails = sample("copilot_guardrail_events_total", kind="suspected_prompt_injection")
    cache_read = sample("copilot_llm_tokens_total", type="cache_read")
    cost = sample("copilot_llm_cost_usd_total")

    await seed_incident(repository, handlers)

    assert sample("copilot_tool_calls_total", tool="search_logs") == tools + 1
    guardrail_now = sample("copilot_guardrail_events_total", kind="suspected_prompt_injection")
    assert guardrail_now == guardrails + 1
    assert sample("copilot_llm_tokens_total", type="cache_read") == cache_read + 50
    assert sample("copilot_llm_cost_usd_total") == pytest.approx(cost + 0.01)


async def backdate(repository: Repository, incident_id: str, age: timedelta) -> None:
    from sqlalchemy import update

    from copilot.db.models import IncidentRow

    async with repository._sessions.begin() as session:
        await session.execute(
            update(IncidentRow)
            .where(IncidentRow.id == incident_id)
            .values(updated_at=utcnow() - age)
        )


async def test_sweeper_fails_an_abandoned_investigation_and_frees_its_fingerprint(
    repository: Repository,
) -> None:
    incident, _ = await repository.create_incident(make_alert())
    await repository.transition_status(
        incident.id, IncidentStatus.QUEUED, IncidentStatus.INVESTIGATING
    )
    await backdate(repository, incident.id, sweeper.STALE_RUNNING_AFTER + timedelta(minutes=1))

    await sweeper.sweep_once(repository, LocalQueue())

    assert await repository.get_status(incident.id) is IncidentStatus.FAILED
    _, created = await repository.create_incident(make_alert())
    assert created is True


async def test_sweeper_flags_an_action_whose_outcome_is_unknown(
    repository: Repository, handlers: JobHandlers
) -> None:
    incident_id = await seed_incident(repository, handlers)
    proposal_id = await approved_proposal(repository, incident_id)
    await repository.claim_proposal(proposal_id)
    await backdate(repository, incident_id, sweeper.STALE_RUNNING_AFTER + timedelta(minutes=1))

    await sweeper.sweep_once(repository, LocalQueue())

    proposal = await repository.get_proposal(incident_id, proposal_id)
    assert proposal is not None
    assert proposal.status is ProposalStatus.FAILED
    assert "Verify" in (proposal.result or "")


async def test_sweeper_leaves_an_active_job_alone(repository: Repository) -> None:
    incident, _ = await repository.create_incident(make_alert())
    await repository.transition_status(
        incident.id, IncidentStatus.QUEUED, IncidentStatus.INVESTIGATING
    )
    await sweeper.sweep_once(repository, LocalQueue())
    assert await repository.get_status(incident.id) is IncidentStatus.INVESTIGATING


async def test_sweeper_requeues_a_queued_incident_that_lost_its_job(
    repository: Repository, handlers: JobHandlers, runtime: FakeRuntime
) -> None:
    incident, _ = await repository.create_incident(make_alert())
    await backdate(repository, incident.id, sweeper.STALE_QUEUED_AFTER + timedelta(minutes=1))
    queue = LocalQueue()

    await sweeper.sweep_once(repository, queue)
    await sweeper.sweep_once(repository, queue)  # The touch stops a second enqueue.

    consumer = asyncio.create_task(queue.consume(handlers.handle))
    await queue.join()
    consumer.cancel()
    await asyncio.gather(consumer, return_exceptions=True)
    assert runtime.investigate_calls == [incident.id]
