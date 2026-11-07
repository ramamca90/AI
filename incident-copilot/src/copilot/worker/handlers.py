"""Job handlers. Delivery is at-least-once, so every job starts with a compare-and-set that
turns a duplicate into a no-op.

Failure text saved here reaches the UI, so it is always one of the fixed strings below.
Exception details go to the logs only: they can quote telemetry or the model's output.
"""

from __future__ import annotations

import asyncio
import time

import structlog
from opentelemetry.trace import Span
from structlog.contextvars import bound_contextvars

from copilot.config import Settings
from copilot.db.repository import Repository
from copilot.domain.models import AgentEvent, Incident, IncidentStatus, Job, JobKind
from copilot.domain.ports import BudgetExceededError, EventSink, LLMRefusedError
from copilot.observability import metrics
from copilot.observability.tracing import get_tracer
from copilot.worker.runtime import RuntimeFactory

log = structlog.get_logger(__name__)

_BUDGET_EXCEEDED = "Investigation stopped: the incident budget was exceeded."
_LLM_REFUSED = "Investigation stopped: the model declined to continue."
_INVESTIGATION_FAILED = "Investigation failed with an internal error. See the worker logs."
_REMEDIATION_FAILED = (
    "Remediation failed with an internal error. Verify the service state manually."
)
_REMEDIATION_INTERRUPTED = (
    "Remediation was interrupted by a worker shutdown. Verify the service state manually."
)

_NOOP = "noop"
_OK = "ok"
_FAILED = "failed"


class JobHandlers:
    def __init__(
        self,
        repository: Repository,
        settings: Settings,
        runtime_factory: RuntimeFactory,
        rejection_errors: tuple[type[Exception], ...] = (),
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._runtime_factory = runtime_factory
        self._rejection_errors = rejection_errors

    async def handle(self, job: Job) -> None:
        started = time.perf_counter()
        outcome = "cancelled"
        span_name = f"job.{job.kind.value}"
        with (
            bound_contextvars(incident_id=job.incident_id, job=job.kind.value),
            get_tracer().start_as_current_span(span_name) as span,
        ):
            span.set_attribute("incident.id", job.incident_id)
            try:
                outcome = await self._dispatch(job, span)
            finally:
                span.set_attribute("job.outcome", outcome)
                metrics.JOB_DURATION.labels(kind=job.kind.value, outcome=outcome).observe(
                    time.perf_counter() - started
                )

    async def _dispatch(self, job: Job, span: Span) -> str:
        if job.kind is JobKind.INVESTIGATE:
            return await self._investigate(job.incident_id)
        if job.proposal_id is None:
            log.error("worker.remediate_job_without_proposal")
            return _NOOP
        span.set_attribute("proposal.id", job.proposal_id)
        return await self._remediate(job.incident_id, job.proposal_id)

    def _event_sink(self) -> EventSink:
        async def emit(event: AgentEvent) -> None:
            await self._repository.append_event(event)
            metrics.record_event(event)

        return emit

    async def _investigate(self, incident_id: str) -> str:
        claimed = await self._repository.transition_status(
            incident_id, IncidentStatus.QUEUED, IncidentStatus.INVESTIGATING
        )
        if not claimed:
            log.info("worker.duplicate_delivery")
            return _NOOP
        incident = await self._repository.get_incident(incident_id)
        if incident is None:
            log.error("worker.incident_vanished")
            return _NOOP

        try:
            runtime = self._runtime_factory(self._settings, incident.alert.scenario)
            result = await runtime.orchestrator.investigate(incident, self._event_sink())
        except BudgetExceededError as error:
            log.warning("worker.budget_exceeded", error=str(error))
            return await self._fail_investigation(incident, _BUDGET_EXCEEDED)
        except LLMRefusedError as error:
            log.warning("worker.llm_refused", error=str(error))
            return await self._fail_investigation(incident, _LLM_REFUSED)
        except asyncio.CancelledError:
            # Shutdown outran the drain. Handing the incident back lets the redelivered job
            # win the compare-and-set and start over, rather than wait for the stale sweep.
            await self._repository.transition_status(
                incident_id, IncidentStatus.INVESTIGATING, IncidentStatus.QUEUED
            )
            raise
        except Exception:
            log.exception("worker.investigation_failed")
            return await self._fail_investigation(incident, _INVESTIGATION_FAILED)

        status = await self._repository.complete_investigation(incident_id, result)
        if status is None:
            log.warning("worker.investigation_outcome_discarded")
            return _NOOP
        metrics.record_usage(result.usage)
        log.info("worker.investigation_complete", status=status.value)
        return _OK

    async def _fail_investigation(self, incident: Incident, message: str) -> str:
        # The orchestrator keeps `incident` current as it goes, so the triage, findings and
        # spend from before the failure are saved. A budget stop is the run where cost matters.
        metrics.record_usage(incident.usage)
        await self._repository.fail_incident(
            incident.id, (IncidentStatus.INVESTIGATING,), message, partial=incident
        )
        return _FAILED

    async def _remediate(self, incident_id: str, proposal_id: str) -> str:
        if not await self._repository.claim_proposal(proposal_id):
            log.info("worker.duplicate_delivery", proposal_id=proposal_id)
            return _NOOP
        incident = await self._repository.get_incident(incident_id)
        proposal = await self._repository.get_proposal(incident_id, proposal_id)
        if incident is None or proposal is None:
            log.error("worker.proposal_vanished", proposal_id=proposal_id)
            return _NOOP

        try:
            runtime = self._runtime_factory(self._settings, incident.alert.scenario)
            result = await runtime.executor.execute(proposal, self._event_sink())
        except self._rejection_errors as error:
            # The validator's own message, safe to show. It can quote fields of the draft,
            # which is why the UI renders it as text like everything else.
            log.warning("worker.remediation_rejected", error=str(error))
            return await self._finish(incident_id, proposal_id, False, str(error))
        except asyncio.CancelledError:
            await self._finish(incident_id, proposal_id, False, _REMEDIATION_INTERRUPTED)
            raise
        except Exception:
            log.exception("worker.remediation_failed")
            return await self._finish(incident_id, proposal_id, False, _REMEDIATION_FAILED)
        return await self._finish(incident_id, proposal_id, True, result)

    async def _finish(
        self, incident_id: str, proposal_id: str, succeeded: bool, result: str
    ) -> str:
        recorded = await self._repository.finish_remediation(
            incident_id, proposal_id, succeeded=succeeded, result=result
        )
        if not recorded:
            log.warning("worker.remediation_outcome_discarded", proposal_id=proposal_id)
        return _OK if succeeded else _FAILED
