"""Shared domain contracts. Every layer imports these; none of them import a layer.

Models marked "LLM output" are also sent to the API as structured-output schemas, so they
avoid numeric bounds and free-form dicts. Range checks that the schema can't express live
in validators and run on the parsed response.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid4().hex


class Severity(StrEnum):
    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"
    SEV4 = "SEV4"


class IncidentStatus(StrEnum):
    QUEUED = "queued"
    INVESTIGATING = "investigating"
    AWAITING_APPROVAL = "awaiting_approval"
    REMEDIATING = "remediating"
    RESOLVED = "resolved"
    CLOSED_NO_ACTION = "closed_no_action"
    FAILED = "failed"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


class Investigator(StrEnum):
    LOGS = "logs"
    METRICS = "metrics"
    DEPLOYS = "deploys"


class Alert(BaseModel):
    """Incoming alert. `fingerprint` deduplicates redelivered webhooks."""

    fingerprint: str = Field(min_length=1, max_length=128)
    source: str = "webhook"
    service: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=4000)
    fired_at: datetime = Field(default_factory=utcnow)
    # Selects a simulated telemetry fixture. Unset means the default demo scenario.
    scenario: str | None = None


class _LLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Triage(_LLMOutput):
    """LLM output from the triage agent."""

    severity: Severity
    affected_services: list[str]
    summary: str
    investigators: list[Investigator]


class Evidence(_LLMOutput):
    """One verifiable observation. `ref` must match a ref returned by a tool or runbook."""

    ref: str
    observation: str


class Finding(_LLMOutput):
    """LLM output from a specialist investigator."""

    summary: str
    suspected_cause: str | None
    evidence: list[Evidence]
    confidence: float

    @field_validator("confidence")
    @classmethod
    def _unit_interval(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("confidence must be between 0 and 1")
        return value


RemediationAction = Literal["rollback_deploy", "restart_service", "scale_service"]


class RemediationDraft(_LLMOutput):
    """Part of the LLM report. Only a suggestion; deterministic code validates and executes it."""

    action: RemediationAction
    service: str
    target_version: str | None
    replicas: int | None
    rationale: str
    risk: Literal["low", "medium", "high"]


class RCAReport(_LLMOutput):
    """LLM output from the synthesizer."""

    summary: str
    root_cause: str
    confidence: float
    timeline: list[str]
    evidence: list[Evidence]
    runbook_refs: list[str]
    remediations: list[RemediationDraft]

    @field_validator("confidence")
    @classmethod
    def _unit_interval(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("confidence must be between 0 and 1")
        return value


class Proposal(BaseModel):
    """A persisted remediation awaiting a human decision."""

    id: str = Field(default_factory=new_id)
    incident_id: str
    draft: RemediationDraft
    status: ProposalStatus = ProposalStatus.PENDING
    decided_by: str | None = None
    decided_at: datetime | None = None
    result: str | None = None


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
        )


class Incident(BaseModel):
    id: str = Field(default_factory=new_id)
    alert: Alert
    status: IncidentStatus = IncidentStatus.QUEUED
    triage: Triage | None = None
    findings: dict[str, Finding] = Field(default_factory=dict)
    report: RCAReport | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class EventType(StrEnum):
    STATUS = "status"
    AGENT_STARTED = "agent_started"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    AGENT_FINISHED = "agent_finished"
    GUARDRAIL = "guardrail"
    ERROR = "error"


class AgentEvent(BaseModel):
    """Append-only trace of one incident. Drives the live UI and the audit log."""

    incident_id: str
    type: EventType
    agent: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    at: datetime = Field(default_factory=utcnow)


class InvestigationResult(BaseModel):
    triage: Triage
    findings: dict[str, Finding]
    report: RCAReport
    usage: TokenUsage


class JobKind(StrEnum):
    INVESTIGATE = "investigate"
    REMEDIATE = "remediate"


class Job(BaseModel):
    """Queue payload. Delivery is at-least-once, so handlers must be idempotent."""

    kind: JobKind
    incident_id: str
    proposal_id: str | None = None
