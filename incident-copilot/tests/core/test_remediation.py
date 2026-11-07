from __future__ import annotations

from typing import Any

import pytest
from tests.core.conftest import EventLog

from copilot.agents.remediation import RemediationExecutor, RemediationRejectedError
from copilot.domain.models import EventType, Proposal, ProposalStatus, RemediationDraft
from copilot.tools.fixtures import FixtureActuator, FixtureTelemetry, Scenario


def draft(**overrides: Any) -> RemediationDraft:
    fields: dict[str, Any] = {
        "action": "rollback_deploy",
        "service": "checkout-api",
        "target_version": "v2.4.0",
        "replicas": None,
        "rationale": "Test.",
        "risk": "low",
    }
    return RemediationDraft.model_construct(**{**fields, **overrides})


def proposal(**overrides: Any) -> Proposal:
    return Proposal.model_construct(
        id="p1",
        incident_id="inc-1",
        draft=draft(**overrides),
        status=ProposalStatus.APPROVED,
    )


@pytest.fixture
def actuator() -> FixtureActuator:
    return FixtureActuator()


@pytest.fixture
def executor(telemetry: FixtureTelemetry, actuator: FixtureActuator) -> RemediationExecutor:
    return RemediationExecutor(telemetry, actuator)


async def test_valid_rollback_runs(
    executor: RemediationExecutor, actuator: FixtureActuator, events: EventLog
) -> None:
    result = await executor.execute(proposal(), events)
    assert result == "rolled back checkout-api to v2.4.0"
    assert actuator.actions == [
        {"action": "rollback_deploy", "service": "checkout-api", "target_version": "v2.4.0"}
    ]
    assert events.of(EventType.STATUS)[0].data["stage"] == "remediation_executed"


async def test_an_older_healthy_version_is_a_valid_target(
    executor: RemediationExecutor, actuator: FixtureActuator, events: EventLog
) -> None:
    await executor.execute(proposal(target_version="v2.3.9"), events)
    assert actuator.actions[0]["target_version"] == "v2.3.9"


async def test_valid_restart_runs(
    executor: RemediationExecutor, actuator: FixtureActuator, events: EventLog
) -> None:
    result = await executor.execute(proposal(action="restart_service", target_version=None), events)
    assert result == "restarted checkout-api"
    assert actuator.actions == [{"action": "restart_service", "service": "checkout-api"}]


@pytest.mark.parametrize("replicas", [1, 7, 20])
async def test_valid_scale_runs(
    executor: RemediationExecutor, actuator: FixtureActuator, events: EventLog, replicas: int
) -> None:
    await executor.execute(
        proposal(action="scale_service", target_version=None, replicas=replicas), events
    )
    assert actuator.actions == [
        {"action": "scale_service", "service": "checkout-api", "replicas": replicas}
    ]


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        pytest.param({"action": "drop_database"}, "not allowed", id="action-not-allowed"),
        pytest.param({"action": ""}, "not allowed", id="action-empty"),
        pytest.param({"service": "no-such-service"}, "unknown service", id="unknown-service"),
        pytest.param({"target_version": None}, "needs a target_version", id="rollback-no-target"),
        pytest.param({"target_version": ""}, "needs a target_version", id="rollback-empty-target"),
        pytest.param({"target_version": "v0.0.1"}, "not in the recent", id="rollback-unknown"),
        pytest.param({"target_version": "v2.4.1"}, "already running", id="rollback-to-current"),
        pytest.param(
            {"action": "scale_service", "replicas": None}, "needs replicas", id="scale-none"
        ),
        pytest.param(
            {"action": "scale_service", "replicas": 0}, "outside 1..20", id="scale-to-zero"
        ),
        pytest.param({"action": "scale_service", "replicas": 21}, "outside", id="scale-too-many"),
        pytest.param({"action": "scale_service", "replicas": -3}, "outside", id="scale-negative"),
    ],
)
async def test_every_rejection_path(
    executor: RemediationExecutor,
    actuator: FixtureActuator,
    events: EventLog,
    overrides: dict[str, Any],
    reason: str,
) -> None:
    with pytest.raises(RemediationRejectedError, match=reason):
        await executor.execute(proposal(**overrides), events)

    assert actuator.actions == [], "a rejected draft must not touch production"
    guardrail = events.of(EventType.GUARDRAIL)[0]
    assert guardrail.data["kind"] == "remediation_rejected"
    assert guardrail.data["proposal_id"] == "p1"
    assert events.of(EventType.STATUS) == []


async def test_rollback_checks_the_proposals_own_service(
    executor: RemediationExecutor, actuator: FixtureActuator, events: EventLog
) -> None:
    """v2.4.0 belongs to checkout-api, so it is no target for payments-api."""
    with pytest.raises(RemediationRejectedError, match="not in the recent"):
        await executor.execute(proposal(service="payments-api"), events)
    assert actuator.actions == []


async def test_without_a_current_marker_the_newest_deploy_counts_as_current(
    bad_deploy: Scenario, actuator: FixtureActuator, events: EventLog
) -> None:
    for deploy in bad_deploy.deploys["checkout-api"]:
        deploy.pop("current")
    executor = RemediationExecutor(FixtureTelemetry(bad_deploy), actuator)
    with pytest.raises(RemediationRejectedError, match="already running"):
        await executor.execute(proposal(target_version="v2.4.1"), events)


async def test_injected_draft_is_stopped_by_code_even_if_a_human_approved_it(
    executor: RemediationExecutor, actuator: FixtureActuator, events: EventLog
) -> None:
    with pytest.raises(RemediationRejectedError):
        await executor.execute(
            proposal(action="scale_service", target_version=None, replicas=0), events
        )
    assert actuator.actions == []


@pytest.mark.parametrize(
    "status",
    [
        ProposalStatus.PENDING,
        ProposalStatus.REJECTED,
        ProposalStatus.EXECUTED,
        ProposalStatus.FAILED,
    ],
)
async def test_only_an_approved_proposal_can_run(
    executor: RemediationExecutor,
    actuator: FixtureActuator,
    events: EventLog,
    status: ProposalStatus,
) -> None:
    unapproved = proposal().model_copy(update={"status": status})
    with pytest.raises(RemediationRejectedError, match="only an approved proposal"):
        await executor.execute(unapproved, events)
    assert actuator.actions == []
