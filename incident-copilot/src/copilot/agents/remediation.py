"""Deterministic execution of a human-approved remediation. No LLM is involved here.

A draft came from a model that read untrusted logs, so nothing in it is taken on trust: every
field is checked against the allowlist and live service state just before acting.
"""

from __future__ import annotations

from typing import Any, get_args

from copilot.domain.models import (
    AgentEvent,
    EventType,
    Proposal,
    ProposalStatus,
    RemediationAction,
    RemediationDraft,
)
from copilot.domain.ports import Actuator, EventSink, Telemetry

ALLOWED_ACTIONS = frozenset(get_args(RemediationAction))
MIN_REPLICAS = 1
MAX_REPLICAS = 20
_AGENT = "remediation"


class RemediationRejectedError(ValueError):
    """The draft failed validation. Nothing was changed."""


class RemediationExecutor:
    def __init__(self, telemetry: Telemetry, actuator: Actuator) -> None:
        self.telemetry = telemetry
        self.actuator = actuator

    async def execute(self, proposal: Proposal, emit: EventSink) -> str:
        """Validate, then act. Returns the actuator's message, or raises
        `RemediationRejectedError` without having touched production."""
        draft = proposal.draft
        try:
            # The repository claims the proposal first; this second check means no code path
            # can reach production with an unapproved proposal, even if that claim is bypassed.
            if proposal.status != ProposalStatus.APPROVED:
                raise RemediationRejectedError(
                    f"proposal is {proposal.status}, only an approved proposal can run"
                )
            await self._validate(draft)
        except RemediationRejectedError as exc:
            await self._event(
                proposal,
                emit,
                EventType.GUARDRAIL,
                kind="remediation_rejected",
                action=str(draft.action),
                service=draft.service,
                reason=str(exc),
            )
            raise
        result = await self._act(draft)
        await self._event(
            proposal,
            emit,
            EventType.STATUS,
            stage="remediation_executed",
            action=draft.action,
            service=draft.service,
            result=result,
        )
        return result

    async def _validate(self, draft: RemediationDraft) -> None:
        if draft.action not in ALLOWED_ACTIONS:
            raise RemediationRejectedError(f"action {draft.action!r} is not allowed")
        services = await self.telemetry.list_services()
        if draft.service not in services:
            raise RemediationRejectedError(f"unknown service {draft.service!r}")
        if draft.action == "rollback_deploy":
            await self._validate_rollback(draft)
        elif draft.action == "scale_service":
            self._validate_scale(draft)

    async def _validate_rollback(self, draft: RemediationDraft) -> None:
        if not draft.target_version:
            raise RemediationRejectedError("rollback_deploy needs a target_version")
        deploys = await self.telemetry.recent_deploys(draft.service)
        versions = [deploy.get("version") for deploy in deploys]
        if draft.target_version not in versions:
            raise RemediationRejectedError(
                f"{draft.target_version} is not in the recent deploys of {draft.service}"
            )
        if draft.target_version == _current_version(deploys):
            raise RemediationRejectedError(
                f"{draft.target_version} is already running on {draft.service}"
            )

    def _validate_scale(self, draft: RemediationDraft) -> None:
        replicas = draft.replicas
        if replicas is None:
            raise RemediationRejectedError("scale_service needs replicas")
        if not MIN_REPLICAS <= replicas <= MAX_REPLICAS:
            raise RemediationRejectedError(
                f"replicas {replicas} is outside {MIN_REPLICAS}..{MAX_REPLICAS}"
            )

    async def _act(self, draft: RemediationDraft) -> str:
        if draft.action == "rollback_deploy" and draft.target_version is not None:
            return await self.actuator.rollback(draft.service, draft.target_version)
        if draft.action == "restart_service":
            return await self.actuator.restart(draft.service)
        if draft.action == "scale_service" and draft.replicas is not None:
            return await self.actuator.scale(draft.service, draft.replicas)
        raise RemediationRejectedError(f"action {draft.action!r} can't be dispatched")

    async def _event(
        self, proposal: Proposal, emit: EventSink, event_type: EventType, **data: Any
    ) -> None:
        await emit(
            AgentEvent(
                incident_id=proposal.incident_id,
                type=event_type,
                agent=_AGENT,
                data={"proposal_id": proposal.id, **data},
            )
        )


def _current_version(deploys: list[dict[str, Any]]) -> Any:
    """The record marked current, else the newest, since deploys are listed newest first."""
    for deploy in deploys:
        if deploy.get("current"):
            return deploy.get("version")
    return deploys[0].get("version") if deploys else None
