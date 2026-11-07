"""Response and request shapes that aren't already domain models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from copilot.domain.models import Incident, IncidentStatus, Proposal, Severity


class IncidentDetail(Incident):
    proposals: list[Proposal] = Field(default_factory=list)


class IncidentSummary(BaseModel):
    id: str
    status: IncidentStatus
    fingerprint: str
    service: str
    title: str
    scenario: str | None
    severity: Severity | None
    cost_usd: float
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, incident: Incident) -> IncidentSummary:
        return cls(
            id=incident.id,
            status=incident.status,
            fingerprint=incident.alert.fingerprint,
            service=incident.alert.service,
            title=incident.alert.title,
            scenario=incident.alert.scenario,
            severity=incident.triage.severity if incident.triage else None,
            cost_usd=incident.usage.cost_usd,
            created_at=incident.created_at,
            updated_at=incident.updated_at,
        )


class IncidentPage(BaseModel):
    items: list[IncidentSummary]
    total: int
    limit: int
    offset: int


class DecisionRequest(BaseModel):
    decided_by: str = Field(min_length=1, max_length=128)


class DecisionResponse(BaseModel):
    proposal: Proposal
    incident_status: IncidentStatus


class HealthResponse(BaseModel):
    status: str
