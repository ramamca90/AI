"""Fakes and builders shared by the platform tests.

Separate from conftest.py because pytest imports that file under its own module name, and a
second import of it through `tests.platform` would duplicate classes such as RejectedError.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx
from fastapi import FastAPI

from copilot.config import Settings
from copilot.db import Repository
from copilot.domain.models import (
    AgentEvent,
    Alert,
    EventType,
    Evidence,
    Finding,
    Incident,
    IncidentStatus,
    InvestigationResult,
    Investigator,
    Job,
    JobKind,
    Proposal,
    RCAReport,
    RemediationDraft,
    Severity,
    TokenUsage,
    Triage,
)
from copilot.domain.ports import EventSink
from copilot.queue import LocalQueue
from copilot.worker.handlers import JobHandlers

API_KEY = "test-key"
AUTH = {"X-API-Key": API_KEY}


class RejectedError(Exception):
    """Stands in for RemediationRejectedError."""


def make_alert(fingerprint: str = "fp-1", **overrides: object) -> Alert:
    values: dict[str, object] = {
        "fingerprint": fingerprint,
        "service": "checkout-api",
        "title": "5xx spike",
        "scenario": "bad_deploy",
    }
    return Alert.model_validate({**values, **overrides})


def make_draft(action: str = "restart_service") -> RemediationDraft:
    return RemediationDraft.model_validate(
        {
            "action": action,
            "service": "checkout-api",
            "target_version": None,
            "replicas": None,
            "rationale": "It is wedged.",
            "risk": "low",
        }
    )


def make_result(remediations: int = 1) -> InvestigationResult:
    evidence = Evidence(ref="log:1", observation="timeouts")
    return InvestigationResult(
        triage=Triage(
            severity=Severity.SEV2,
            affected_services=["checkout-api"],
            summary="Checkout is failing",
            investigators=[Investigator.LOGS],
        ),
        findings={
            "logs": Finding(
                summary="Timeouts", suspected_cause="deploy", evidence=[evidence], confidence=0.8
            )
        },
        report=RCAReport(
            summary="A bad deploy",
            root_cause="Connection leak",
            confidence=0.9,
            timeline=["12:00 deploy"],
            evidence=[evidence],
            runbook_refs=["runbook:rollback"],
            remediations=[make_draft() for _ in range(remediations)],
        ),
        usage=TokenUsage(input_tokens=100, output_tokens=20, cache_read_tokens=50, cost_usd=0.01),
    )


@dataclass
class FakeRuntime:
    """Scripted orchestrator and executor. Set `investigate_error` or `execute_error` to fail."""

    result: InvestigationResult = field(default_factory=make_result)
    investigate_error: BaseException | None = None
    execute_error: BaseException | None = None
    execute_calls: list[str] = field(default_factory=list)
    investigate_calls: list[str] = field(default_factory=list)
    scenarios: list[str | None] = field(default_factory=list)
    # When set, investigate waits here, so a test can hold a job in flight without sleeping.
    gate: asyncio.Event | None = None
    started: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def orchestrator(self) -> FakeRuntime:
        return self

    @property
    def executor(self) -> FakeRuntime:
        return self

    def factory(self, _settings: Settings, scenario: str | None) -> FakeRuntime:
        self.scenarios.append(scenario)
        return self

    async def investigate(self, incident: Incident, emit: EventSink) -> InvestigationResult:
        self.investigate_calls.append(incident.id)
        await emit(
            AgentEvent(
                incident_id=incident.id,
                type=EventType.TOOL_CALL,
                agent="logs",
                data={"tool": "search_logs", "input": {"query": "error"}},
            )
        )
        await emit(
            AgentEvent(
                incident_id=incident.id,
                type=EventType.GUARDRAIL,
                agent="logs",
                data={"kind": "suspected_prompt_injection"},
            )
        )
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.investigate_error is not None:
            incident.triage = self.result.triage
            incident.usage = TokenUsage(input_tokens=7, cost_usd=0.5)
            raise self.investigate_error
        return self.result

    async def execute(self, proposal: Proposal, emit: EventSink) -> str:
        self.execute_calls.append(proposal.id)
        if self.execute_error is not None:
            raise self.execute_error
        await emit(
            AgentEvent(
                incident_id=proposal.incident_id,
                type=EventType.STATUS,
                agent="remediation",
                data={"stage": "remediation_executed"},
            )
        )
        return "restarted checkout-api"


@dataclass
class Platform:
    """A running app with its embedded worker, plus the seams tests reach through."""

    app: FastAPI
    client: httpx.AsyncClient
    queue: LocalQueue
    runtime: FakeRuntime

    @property
    def repository(self) -> Repository:
        repository: Repository = self.app.state.services.repository
        return repository

    async def fire(self, fingerprint: str = "fp-1") -> str:
        response = await self.client.post(
            "/v1/alerts",
            json=make_alert(fingerprint).model_dump(mode="json"),
            headers=AUTH,
        )
        assert response.status_code == 202, response.text
        incident_id: str = response.json()["id"]
        await self.queue.join()
        return incident_id

    async def proposals(self, incident_id: str) -> list[Proposal]:
        return await self.repository.list_proposals(incident_id)

    async def status(self, incident_id: str) -> IncidentStatus | None:
        return await self.repository.get_status(incident_id)


async def seed_incident(
    repository: Repository,
    handlers: JobHandlers,
    fingerprint: str = "fp-1",
) -> str:
    """An investigated incident, awaiting approval."""
    incident, _ = await repository.create_incident(make_alert(fingerprint))
    await handlers.handle(Job(kind=JobKind.INVESTIGATE, incident_id=incident.id))
    return incident.id
