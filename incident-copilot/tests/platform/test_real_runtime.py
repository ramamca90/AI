"""Runs the real agent core on its scripted LLM, so the interface can't drift unnoticed."""

from __future__ import annotations

import pytest
from tests.platform.support import make_alert, make_draft

from copilot.config import Settings
from copilot.db import Repository
from copilot.domain.models import AgentEvent, IncidentStatus, Job, JobKind, ProposalStatus
from copilot.worker.handlers import JobHandlers
from copilot.worker.runtime import default_rejection_errors, default_runtime_factory


@pytest.fixture
def real_handlers(repository: Repository, settings: Settings) -> JobHandlers:
    assert settings.llm_provider == "scripted"
    return JobHandlers(repository, settings, default_runtime_factory, default_rejection_errors())


@pytest.mark.parametrize("scenario", ["bad_deploy", "db_pool_exhausted", "prompt_injection"])
async def test_a_scenario_runs_from_alert_to_resolved(
    repository: Repository, real_handlers: JobHandlers, scenario: str
) -> None:
    incident, _ = await repository.create_incident(make_alert(scenario=scenario))

    await real_handlers.handle(Job(kind=JobKind.INVESTIGATE, incident_id=incident.id))

    loaded = await repository.get_incident(incident.id)
    assert loaded is not None
    assert loaded.status is IncidentStatus.AWAITING_APPROVAL, loaded.error
    assert loaded.report is not None
    proposal = (await repository.list_proposals(incident.id))[0]
    await repository.approve_proposal(incident.id, proposal.id, "ann")

    await real_handlers.handle(
        Job(kind=JobKind.REMEDIATE, incident_id=incident.id, proposal_id=proposal.id)
    )

    assert await repository.get_status(incident.id) is IncidentStatus.RESOLVED
    executed = await repository.get_proposal(incident.id, proposal.id)
    assert executed is not None
    assert executed.status is ProposalStatus.EXECUTED


async def test_the_real_executor_rejection_is_recognized(
    repository: Repository, settings: Settings
) -> None:
    runtime = default_runtime_factory(settings, "bad_deploy")
    errors = default_rejection_errors()
    draft = make_draft().model_copy(update={"service": "not-a-service"})
    from copilot.domain.models import Proposal

    async def emit(_event: AgentEvent) -> None:
        return None

    with pytest.raises(errors):
        await runtime.executor.execute(Proposal(incident_id="i", draft=draft), emit)


async def test_an_unknown_scenario_fails_the_incident_safely(
    repository: Repository, real_handlers: JobHandlers
) -> None:
    incident, _ = await repository.create_incident(make_alert(scenario="nope"))

    await real_handlers.handle(Job(kind=JobKind.INVESTIGATE, incident_id=incident.id))

    assert await repository.get_status(incident.id) is IncidentStatus.FAILED
