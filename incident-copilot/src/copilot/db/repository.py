"""All SQL lives here. Methods take and return domain models, and each is one transaction.

Portable locking: a transaction that must serialize with other writers on an incident starts
with an UPDATE of that incident's row. That takes the row lock on Postgres and the database
write lock on SQLite. A leading `SELECT ... FOR UPDATE` would not work: SQLite has no such
clause, and pysqlite only opens a transaction at the first write.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from copilot.db.models import TERMINAL_STATUSES, EventRow, IncidentRow, ProposalRow
from copilot.domain.models import (
    AgentEvent,
    Alert,
    EventType,
    Finding,
    Incident,
    IncidentStatus,
    InvestigationResult,
    Proposal,
    ProposalStatus,
    RCAReport,
    RemediationDraft,
    TokenUsage,
    Triage,
    new_id,
    utcnow,
)

_SYSTEM_ACTOR = "system"
# A racing insert can hit the index and then find nothing, because the incident it collided
# with resolved in between. Trying again is correct, and a third race is vanishingly unlikely.
_CREATE_ATTEMPTS = 3
_SUPERSEDED = "Not executed: the incident was closed by another outcome."
_OUTCOME_UNKNOWN = "Execution was interrupted or never started. Verify the service state manually."


class NotFoundError(LookupError):
    """The incident or proposal does not exist."""


class DecisionConflictError(RuntimeError):
    """The proposal was already decided, or its incident no longer accepts decisions."""


@dataclass(frozen=True)
class StoredEvent:
    """An event plus its database id, which is the SSE cursor."""

    id: int
    event: AgentEvent


def _rowcount(result: Any) -> int:
    return cast("CursorResult[Any]", result).rowcount


def _incident(row: IncidentRow) -> Incident:
    return Incident(
        id=row.id,
        alert=Alert.model_validate(row.alert),
        status=IncidentStatus(row.status),
        triage=Triage.model_validate(row.triage) if row.triage else None,
        findings={key: Finding.model_validate(value) for key, value in row.findings.items()},
        report=RCAReport.model_validate(row.report) if row.report else None,
        usage=TokenUsage.model_validate(row.usage),
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _proposal(row: ProposalRow) -> Proposal:
    return Proposal(
        id=row.id,
        incident_id=row.incident_id,
        draft=RemediationDraft.model_validate(row.draft),
        status=ProposalStatus(row.status),
        decided_by=row.decided_by,
        decided_at=row.decided_at,
        result=row.result,
    )


def _stored_event(row: EventRow) -> StoredEvent:
    return StoredEvent(
        id=row.id,
        event=AgentEvent(
            incident_id=row.incident_id,
            type=EventType(row.type),
            agent=row.agent,
            data=row.data,
            at=row.at,
        ),
    )


class Repository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    # Health and metrics

    async def ping(self) -> None:
        async with self._sessions() as session:
            await session.execute(select(1))

    async def count_by_status(self) -> dict[IncidentStatus, int]:
        statement = select(IncidentRow.status, func.count()).group_by(IncidentRow.status)
        async with self._sessions() as session:
            rows = (await session.execute(statement)).all()
        return {IncidentStatus(status): count for status, count in rows}

    # Incidents

    async def create_incident(self, alert: Alert) -> tuple[Incident, bool]:
        """Create an incident, or return the active one for this fingerprint.

        The partial unique index decides the winner of a race. The leading lookup is only a
        fast path that spares Postgres a logged constraint violation on every redelivery.
        """
        for _ in range(_CREATE_ATTEMPTS):
            existing = await self.get_active_by_fingerprint(alert.fingerprint)
            if existing is not None:
                return existing, False
            incident = Incident(alert=alert)
            try:
                async with self._sessions.begin() as session:
                    session.add(
                        IncidentRow(
                            id=incident.id,
                            fingerprint=alert.fingerprint,
                            service=alert.service,
                            alert=alert.model_dump(mode="json"),
                            status=incident.status.value,
                            triage=None,
                            findings={},
                            report=None,
                            usage=incident.usage.model_dump(mode="json"),
                            error=None,
                            created_at=incident.created_at,
                            updated_at=incident.updated_at,
                        )
                    )
                    await session.flush()
                    await self._insert_status_event(session, incident.id, incident.status)
            except IntegrityError:
                continue
            return incident, True
        raise RuntimeError(f"could not create incident for fingerprint {alert.fingerprint!r}")

    async def get_active_by_fingerprint(self, fingerprint: str) -> Incident | None:
        statement = select(IncidentRow).where(
            IncidentRow.fingerprint == fingerprint,
            IncidentRow.status.not_in([status.value for status in TERMINAL_STATUSES]),
        )
        async with self._sessions() as session:
            row = (await session.execute(statement)).scalar_one_or_none()
        return _incident(row) if row else None

    async def get_incident(self, incident_id: str) -> Incident | None:
        async with self._sessions() as session:
            row = await session.get(IncidentRow, incident_id)
        return _incident(row) if row else None

    async def get_status(self, incident_id: str) -> IncidentStatus | None:
        statement = select(IncidentRow.status).where(IncidentRow.id == incident_id)
        async with self._sessions() as session:
            status = (await session.execute(statement)).scalar_one_or_none()
        return IncidentStatus(status) if status else None

    async def list_incidents(
        self, limit: int, offset: int, status: IncidentStatus | None = None
    ) -> tuple[list[Incident], int]:
        """Newest first, with the total for the pager."""
        rows_query = select(IncidentRow)
        count_query = select(func.count()).select_from(IncidentRow)
        if status is not None:
            rows_query = rows_query.where(IncidentRow.status == status.value)
            count_query = count_query.where(IncidentRow.status == status.value)
        rows_query = (
            rows_query.order_by(IncidentRow.created_at.desc(), IncidentRow.id.desc())
            .limit(limit)
            .offset(offset)
        )
        async with self._sessions() as session:
            rows = (await session.execute(rows_query)).scalars().all()
            total = (await session.execute(count_query)).scalar_one()
        return [_incident(row) for row in rows], total

    async def transition_status(
        self, incident_id: str, expected: IncidentStatus, new: IncidentStatus
    ) -> bool:
        """Atomic compare-and-set. False means another actor moved the incident first."""
        async with self._sessions.begin() as session:
            moved = await self._compare_and_set(session, incident_id, (expected,), new)
            if moved:
                await self._insert_status_event(session, incident_id, new)
        return moved

    async def complete_investigation(
        self, incident_id: str, result: InvestigationResult
    ) -> IncidentStatus | None:
        """Save the outcome and its proposals in one step. None if the CAS was lost."""
        new = (
            IncidentStatus.AWAITING_APPROVAL
            if result.report.remediations
            else IncidentStatus.CLOSED_NO_ACTION
        )
        async with self._sessions.begin() as session:
            moved = await self._compare_and_set(
                session,
                incident_id,
                (IncidentStatus.INVESTIGATING,),
                new,
                triage=result.triage.model_dump(mode="json"),
                findings={k: v.model_dump(mode="json") for k, v in result.findings.items()},
                report=result.report.model_dump(mode="json"),
                usage=result.usage.model_dump(mode="json"),
            )
            if not moved:
                return None
            session.add_all(
                ProposalRow(
                    id=new_id(),
                    incident_id=incident_id,
                    position=position,
                    draft=draft.model_dump(mode="json"),
                    status=ProposalStatus.PENDING.value,
                )
                for position, draft in enumerate(result.report.remediations)
            )
            await session.flush()
            await self._insert_status_event(session, incident_id, new)
        return new

    async def fail_incident(
        self,
        incident_id: str,
        expected: Iterable[IncidentStatus],
        message: str,
        *,
        partial: Incident | None = None,
    ) -> bool:
        """Move to failed with a user-safe message, closing any undecided proposals.

        `partial` carries what an interrupted investigation managed to produce.
        """
        values: dict[str, Any] = {"error": message}
        if partial is not None:
            values.update(
                triage=partial.triage.model_dump(mode="json") if partial.triage else None,
                findings={k: v.model_dump(mode="json") for k, v in partial.findings.items()},
                usage=partial.usage.model_dump(mode="json"),
            )
        async with self._sessions.begin() as session:
            moved = await self._compare_and_set(
                session, incident_id, tuple(expected), IncidentStatus.FAILED, **values
            )
            if not moved:
                return False
            await self._close_open_proposals(session, incident_id)
            await self._insert_event(
                session,
                AgentEvent(incident_id=incident_id, type=EventType.ERROR, data={"error": message}),
            )
            await self._insert_status_event(session, incident_id, IncidentStatus.FAILED)
        return True

    async def stale_incidents(
        self, statuses: Iterable[IncidentStatus], updated_before: datetime
    ) -> list[Incident]:
        statement = select(IncidentRow).where(
            IncidentRow.status.in_([status.value for status in statuses]),
            IncidentRow.updated_at < updated_before,
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).scalars().all()
        return [_incident(row) for row in rows]

    async def touch_incident(self, incident_id: str) -> None:
        """Reset the staleness clock."""
        async with self._sessions.begin() as session:
            await self._lock_incident(session, incident_id)

    # Proposals

    async def list_proposals(self, incident_id: str) -> list[Proposal]:
        statement = (
            select(ProposalRow)
            .where(ProposalRow.incident_id == incident_id)
            .order_by(ProposalRow.position)
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).scalars().all()
        return [_proposal(row) for row in rows]

    async def get_proposal(self, incident_id: str, proposal_id: str) -> Proposal | None:
        async with self._sessions() as session:
            row = await session.get(ProposalRow, proposal_id)
        return _proposal(row) if row and row.incident_id == incident_id else None

    async def approve_proposal(
        self, incident_id: str, proposal_id: str, decided_by: str
    ) -> Proposal:
        """Record the approval and take the incident to remediating, or change nothing.

        Only one action runs per incident. The incident CAS comes first, so two approvals of
        different proposals serialize on it and the loser gets a conflict. If this proposal
        turns out to be decided already, `_decide` raises and that rolls the CAS back.
        """
        await self._require_proposal(incident_id, proposal_id)
        async with self._sessions.begin() as session:
            moved = await self._compare_and_set(
                session,
                incident_id,
                (IncidentStatus.AWAITING_APPROVAL,),
                IncidentStatus.REMEDIATING,
            )
            if not moved:
                raise DecisionConflictError("incident is not awaiting approval")
            await self._decide(session, proposal_id, ProposalStatus.APPROVED, decided_by)
            await self._insert_status_event(
                session,
                incident_id,
                IncidentStatus.REMEDIATING,
                proposal_id=proposal_id,
                decided_by=decided_by,
            )
        return await self._require_proposal(incident_id, proposal_id)

    async def reject_proposal(
        self, incident_id: str, proposal_id: str, decided_by: str
    ) -> tuple[Proposal, IncidentStatus]:
        """Record a rejection. The last pending rejection closes the incident.

        The incident lock makes two concurrent last rejections serialize. Without it each
        could see the other's proposal still pending, and neither would close the incident.
        """
        await self._require_proposal(incident_id, proposal_id)
        async with self._sessions.begin() as session:
            locked = await self._lock_incident(
                session, incident_id, IncidentStatus.AWAITING_APPROVAL
            )
            if not locked:
                raise DecisionConflictError("incident is not awaiting approval")
            await self._decide(session, proposal_id, ProposalStatus.REJECTED, decided_by)
            await self._insert_event(
                session,
                AgentEvent(
                    incident_id=incident_id,
                    type=EventType.STATUS,
                    data={
                        "status": IncidentStatus.AWAITING_APPROVAL.value,
                        "rejected_proposal_id": proposal_id,
                        "decided_by": decided_by,
                    },
                ),
            )
            pending = await session.execute(
                select(func.count())
                .select_from(ProposalRow)
                .where(
                    ProposalRow.incident_id == incident_id,
                    ProposalRow.status == ProposalStatus.PENDING.value,
                )
            )
            status = IncidentStatus.AWAITING_APPROVAL
            if pending.scalar_one() == 0:
                status = IncidentStatus.CLOSED_NO_ACTION
                await self._compare_and_set(
                    session, incident_id, (IncidentStatus.AWAITING_APPROVAL,), status
                )
                await self._insert_status_event(session, incident_id, status)
        return await self._require_proposal(incident_id, proposal_id), status

    async def claim_proposal(self, proposal_id: str) -> bool:
        """Win the single right to execute an approved proposal.

        At-most-once by design: a crash after the claim leaves the action unretried, because
        repeating a production change is worse than asking a human to re-check it.
        """
        statement = (
            update(ProposalRow)
            .where(
                ProposalRow.id == proposal_id,
                ProposalRow.status == ProposalStatus.APPROVED.value,
                ProposalRow.execution_started_at.is_(None),
            )
            .values(execution_started_at=utcnow())
        )
        async with self._sessions.begin() as session:
            return _rowcount(await session.execute(statement)) == 1

    async def finish_remediation(
        self, incident_id: str, proposal_id: str, *, succeeded: bool, result: str
    ) -> bool:
        """Record the outcome and settle the incident. Other proposals stop being actionable."""
        proposal_status = ProposalStatus.EXECUTED if succeeded else ProposalStatus.FAILED
        incident_status = IncidentStatus.RESOLVED if succeeded else IncidentStatus.FAILED
        async with self._sessions.begin() as session:
            moved = await self._compare_and_set(
                session,
                incident_id,
                (IncidentStatus.REMEDIATING,),
                incident_status,
                error=None if succeeded else result,
            )
            if not moved:
                return False
            await session.execute(
                update(ProposalRow)
                .where(
                    ProposalRow.id == proposal_id,
                    ProposalRow.status == ProposalStatus.APPROVED.value,
                )
                .values(status=proposal_status.value, result=result)
            )
            await self._close_open_proposals(session, incident_id)
            if not succeeded:
                await self._insert_event(
                    session,
                    AgentEvent(
                        incident_id=incident_id,
                        type=EventType.ERROR,
                        data={"error": result, "proposal_id": proposal_id},
                    ),
                )
            await self._insert_status_event(
                session, incident_id, incident_status, proposal_id=proposal_id
            )
        return True

    # Events

    async def append_event(self, event: AgentEvent) -> int:
        async with self._sessions.begin() as session:
            return await self._insert_event(session, event)

    async def list_events(
        self, incident_id: str, after_id: int = 0, limit: int = 500
    ) -> list[StoredEvent]:
        statement = (
            select(EventRow)
            .where(EventRow.incident_id == incident_id, EventRow.id > after_id)
            .order_by(EventRow.id)
            .limit(limit)
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).scalars().all()
        return [_stored_event(row) for row in rows]

    # Internals. These run inside the caller's transaction.

    async def _require_proposal(self, incident_id: str, proposal_id: str) -> Proposal:
        proposal = await self.get_proposal(incident_id, proposal_id)
        if proposal is None:
            raise NotFoundError(proposal_id)
        return proposal

    async def _compare_and_set(
        self,
        session: AsyncSession,
        incident_id: str,
        expected: tuple[IncidentStatus, ...],
        new: IncidentStatus,
        **values: Any,
    ) -> bool:
        statement = (
            update(IncidentRow)
            .where(
                IncidentRow.id == incident_id,
                IncidentRow.status.in_([status.value for status in expected]),
            )
            .values(status=new.value, updated_at=utcnow(), **values)
        )
        return _rowcount(await session.execute(statement)) == 1

    async def _lock_incident(
        self, session: AsyncSession, incident_id: str, status: IncidentStatus | None = None
    ) -> bool:
        statement = (
            update(IncidentRow).where(IncidentRow.id == incident_id).values(updated_at=utcnow())
        )
        if status is not None:
            statement = statement.where(IncidentRow.status == status.value)
        return _rowcount(await session.execute(statement)) == 1

    async def _decide(
        self,
        session: AsyncSession,
        proposal_id: str,
        status: ProposalStatus,
        decided_by: str,
    ) -> None:
        statement = (
            update(ProposalRow)
            .where(
                ProposalRow.id == proposal_id,
                ProposalRow.status == ProposalStatus.PENDING.value,
            )
            .values(status=status.value, decided_by=decided_by, decided_at=utcnow())
        )
        if _rowcount(await session.execute(statement)) != 1:
            raise DecisionConflictError("proposal has already been decided")

    async def _close_open_proposals(self, session: AsyncSession, incident_id: str) -> None:
        await session.execute(
            update(ProposalRow)
            .where(
                ProposalRow.incident_id == incident_id,
                ProposalRow.status == ProposalStatus.PENDING.value,
            )
            .values(
                status=ProposalStatus.REJECTED.value,
                decided_by=_SYSTEM_ACTOR,
                decided_at=utcnow(),
                result=_SUPERSEDED,
            )
        )
        await session.execute(
            update(ProposalRow)
            .where(
                ProposalRow.incident_id == incident_id,
                ProposalRow.status == ProposalStatus.APPROVED.value,
            )
            .values(status=ProposalStatus.FAILED.value, result=_OUTCOME_UNKNOWN)
        )

    async def _insert_event(self, session: AsyncSession, event: AgentEvent) -> int:
        """Insert under the incident's row lock.

        SSE readers advance a cursor past the highest id they have seen. A Postgres sequence
        hands out ids at insert, not at commit, so two unserialized writers could commit out
        of order and a reader would skip the lower id forever. Holding the row lock from
        before the id is allocated until commit makes commit order equal id order within an
        incident, across every process that writes events.
        """
        if not await self._lock_incident(session, event.incident_id):
            raise NotFoundError(event.incident_id)
        result = await session.execute(
            insert(EventRow)
            .values(
                incident_id=event.incident_id,
                type=event.type.value,
                agent=event.agent,
                data=event.model_dump(mode="json")["data"],
                at=event.at,
            )
            .returning(EventRow.id)
        )
        return result.scalar_one()

    async def _insert_status_event(
        self,
        session: AsyncSession,
        incident_id: str,
        status: IncidentStatus,
        **extra: str,
    ) -> int:
        return await self._insert_event(
            session,
            AgentEvent(
                incident_id=incident_id,
                type=EventType.STATUS,
                data={"status": status.value, **extra},
            ),
        )
