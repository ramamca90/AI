from __future__ import annotations

import asyncio

import pytest
from tests.platform.support import make_alert, make_result

from copilot.db import DecisionConflictError, NotFoundError, Repository
from copilot.domain.models import (
    AgentEvent,
    EventType,
    IncidentStatus,
    ProposalStatus,
)


async def to_awaiting_approval(repository: Repository, remediations: int = 1) -> str:
    incident, _ = await repository.create_incident(make_alert())
    await repository.transition_status(
        incident.id, IncidentStatus.QUEUED, IncidentStatus.INVESTIGATING
    )
    await repository.complete_investigation(incident.id, make_result(remediations))
    return incident.id


async def test_create_returns_the_active_incident_for_a_duplicate_fingerprint(
    repository: Repository,
) -> None:
    first, created = await repository.create_incident(make_alert())
    second, created_again = await repository.create_incident(make_alert())
    assert created is True
    assert created_again is False
    assert second.id == first.id


async def test_concurrent_duplicates_create_exactly_one_incident(repository: Repository) -> None:
    results = await asyncio.gather(*(repository.create_incident(make_alert()) for _ in range(20)))
    assert sum(created for _, created in results) == 1
    assert len({incident.id for incident, _ in results}) == 1
    incidents, total = await repository.list_incidents(limit=50, offset=0)
    assert total == 1
    assert len(incidents) == 1


@pytest.mark.parametrize(
    "terminal",
    [IncidentStatus.FAILED, IncidentStatus.RESOLVED, IncidentStatus.CLOSED_NO_ACTION],
)
async def test_a_terminal_incident_frees_its_fingerprint(
    repository: Repository, terminal: IncidentStatus
) -> None:
    first, _ = await repository.create_incident(make_alert())
    assert await repository.transition_status(first.id, IncidentStatus.QUEUED, terminal)
    second, created = await repository.create_incident(make_alert())
    assert created is True
    assert second.id != first.id


async def test_different_fingerprints_do_not_collide(repository: Repository) -> None:
    _, first = await repository.create_incident(make_alert("a"))
    _, second = await repository.create_incident(make_alert("b"))
    assert first and second


async def test_only_one_concurrent_compare_and_set_wins(repository: Repository) -> None:
    incident, _ = await repository.create_incident(make_alert())
    outcomes = await asyncio.gather(
        *(
            repository.transition_status(
                incident.id, IncidentStatus.QUEUED, IncidentStatus.INVESTIGATING
            )
            for _ in range(10)
        )
    )
    assert sum(outcomes) == 1
    status_events = [
        stored
        for stored in await repository.list_events(incident.id)
        if stored.event.data.get("status") == IncidentStatus.INVESTIGATING.value
    ]
    assert len(status_events) == 1


async def test_compare_and_set_refuses_a_wrong_expected_status(repository: Repository) -> None:
    incident, _ = await repository.create_incident(make_alert())
    moved = await repository.transition_status(
        incident.id, IncidentStatus.INVESTIGATING, IncidentStatus.AWAITING_APPROVAL
    )
    assert moved is False
    assert await repository.get_status(incident.id) is IncidentStatus.QUEUED


async def test_event_ids_are_monotonic_under_concurrent_writers(repository: Repository) -> None:
    incident, _ = await repository.create_incident(make_alert())
    await asyncio.gather(
        *(
            repository.append_event(
                AgentEvent(incident_id=incident.id, type=EventType.TOOL_CALL, data={"n": n})
            )
            for n in range(25)
        )
    )
    ids = [stored.id for stored in await repository.list_events(incident.id)]
    assert ids == sorted(set(ids))
    assert len(ids) == 26  # The queued status event plus the 25 above.


async def test_list_events_resumes_after_a_cursor(repository: Repository) -> None:
    incident, _ = await repository.create_incident(make_alert())
    cursor = await repository.append_event(
        AgentEvent(incident_id=incident.id, type=EventType.AGENT_STARTED)
    )
    later = await repository.append_event(
        AgentEvent(incident_id=incident.id, type=EventType.AGENT_FINISHED)
    )
    assert [stored.id for stored in await repository.list_events(incident.id, cursor)] == [later]


async def test_appending_to_a_missing_incident_raises(repository: Repository) -> None:
    with pytest.raises(NotFoundError):
        await repository.append_event(AgentEvent(incident_id="nope", type=EventType.STATUS))


async def test_timestamps_round_trip_as_aware_utc(repository: Repository) -> None:
    incident, _ = await repository.create_incident(make_alert())
    loaded = await repository.get_incident(incident.id)
    assert loaded is not None
    assert loaded.created_at.tzinfo is not None
    assert loaded.created_at.utcoffset().total_seconds() == 0  # type: ignore[union-attr]
    assert loaded.created_at == incident.created_at


async def test_complete_investigation_loses_its_cas_without_creating_proposals(
    repository: Repository,
) -> None:
    incident, _ = await repository.create_incident(make_alert())
    assert await repository.complete_investigation(incident.id, make_result()) is None
    assert await repository.list_proposals(incident.id) == []


async def test_a_proposal_can_only_be_claimed_once(repository: Repository) -> None:
    incident_id = await to_awaiting_approval(repository)
    proposal = (await repository.list_proposals(incident_id))[0]
    await repository.approve_proposal(incident_id, proposal.id, "ann")
    outcomes = await asyncio.gather(*(repository.claim_proposal(proposal.id) for _ in range(10)))
    assert sum(outcomes) == 1


async def test_an_unapproved_proposal_cannot_be_claimed(repository: Repository) -> None:
    incident_id = await to_awaiting_approval(repository)
    proposal = (await repository.list_proposals(incident_id))[0]
    assert await repository.claim_proposal(proposal.id) is False


async def test_concurrent_approvals_of_one_proposal_have_one_winner(
    repository: Repository,
) -> None:
    incident_id = await to_awaiting_approval(repository)
    proposal = (await repository.list_proposals(incident_id))[0]
    outcomes = await asyncio.gather(
        *(repository.approve_proposal(incident_id, proposal.id, f"u{n}") for n in range(8)),
        return_exceptions=True,
    )
    conflicts = [item for item in outcomes if isinstance(item, DecisionConflictError)]
    assert len(conflicts) == 7


async def test_concurrent_approvals_of_different_proposals_run_only_one_action(
    repository: Repository,
) -> None:
    incident_id = await to_awaiting_approval(repository, remediations=2)
    first, second = await repository.list_proposals(incident_id)
    outcomes = await asyncio.gather(
        repository.approve_proposal(incident_id, first.id, "ann"),
        repository.approve_proposal(incident_id, second.id, "bob"),
        return_exceptions=True,
    )
    assert sum(isinstance(item, DecisionConflictError) for item in outcomes) == 1
    statuses = [p.status for p in await repository.list_proposals(incident_id)]
    assert sorted(statuses) == [ProposalStatus.APPROVED, ProposalStatus.PENDING]


async def test_a_conflicting_approval_rolls_back_its_incident_transition(
    repository: Repository,
) -> None:
    incident_id = await to_awaiting_approval(repository, remediations=2)
    first, _ = await repository.list_proposals(incident_id)
    await repository.reject_proposal(incident_id, first.id, "ann")
    with pytest.raises(DecisionConflictError):
        await repository.approve_proposal(incident_id, first.id, "bob")
    assert await repository.get_status(incident_id) is IncidentStatus.AWAITING_APPROVAL


async def test_concurrent_last_rejections_still_close_the_incident(repository: Repository) -> None:
    incident_id = await to_awaiting_approval(repository, remediations=5)
    proposals = await repository.list_proposals(incident_id)
    await asyncio.gather(*(repository.reject_proposal(incident_id, p.id, "ann") for p in proposals))
    assert await repository.get_status(incident_id) is IncidentStatus.CLOSED_NO_ACTION


async def test_finishing_a_remediation_supersedes_the_other_proposals(
    repository: Repository,
) -> None:
    incident_id = await to_awaiting_approval(repository, remediations=2)
    first, second = await repository.list_proposals(incident_id)
    await repository.approve_proposal(incident_id, first.id, "ann")
    await repository.finish_remediation(incident_id, first.id, succeeded=True, result="done")
    done, superseded = await repository.list_proposals(incident_id)
    assert done.status is ProposalStatus.EXECUTED
    assert superseded.id == second.id
    assert superseded.status is ProposalStatus.REJECTED
    assert superseded.decided_by == "system"


async def test_decisions_on_an_unknown_proposal_raise_not_found(repository: Repository) -> None:
    incident_id = await to_awaiting_approval(repository)
    with pytest.raises(NotFoundError):
        await repository.approve_proposal(incident_id, "nope", "ann")
    with pytest.raises(NotFoundError):
        await repository.reject_proposal("nope", "nope", "ann")


async def test_a_proposal_is_not_reachable_through_another_incident(
    repository: Repository,
) -> None:
    incident_id = await to_awaiting_approval(repository)
    proposal = (await repository.list_proposals(incident_id))[0]
    with pytest.raises(NotFoundError):
        await repository.approve_proposal("other-incident", proposal.id, "ann")
