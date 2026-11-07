"""HTTP routes. Writes need the API key. Reads are open, so deploy behind a private network."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from structlog.contextvars import bind_contextvars

from copilot.api.deps import ServicesDep, require_api_key
from copilot.api.errors import ApiError
from copilot.api.schemas import (
    DecisionRequest,
    DecisionResponse,
    HealthResponse,
    IncidentDetail,
    IncidentPage,
    IncidentSummary,
)
from copilot.api.sse import event_stream, parse_last_event_id
from copilot.db import DecisionConflictError, NotFoundError
from copilot.domain.models import Alert, Incident, IncidentStatus, Job, JobKind
from copilot.observability import metrics

log = structlog.get_logger(__name__)

_QUEUE_FAILED = "Could not queue the job. Retry the request."
_INCIDENT_NOT_FOUND = "Incident not found."
_PROPOSAL_NOT_FOUND = "Proposal not found."

RequireKey = Depends(require_api_key)
router = APIRouter()


async def _bind_incident(incident_id: str) -> None:
    bind_contextvars(incident_id=incident_id)


incidents = APIRouter(prefix="/v1/incidents", tags=["incidents"])
incident_scoped = [Depends(_bind_incident)]


async def _detail(services: ServicesDep, incident: Incident) -> IncidentDetail:
    proposals = await services.repository.list_proposals(incident.id)
    return IncidentDetail(**incident.model_dump(), proposals=proposals)


@router.post(
    "/v1/alerts",
    status_code=202,
    response_model=IncidentDetail,
    dependencies=[RequireKey],
    responses={200: {"description": "An active incident already has this fingerprint."}},
    tags=["alerts"],
)
async def create_alert(alert: Alert, response: Response, services: ServicesDep) -> IncidentDetail:
    incident, created = await services.repository.create_incident(alert)
    bind_contextvars(incident_id=incident.id)
    if not created:
        metrics.ALERTS.labels(outcome="duplicate").inc()
        response.status_code = 200
        return await _detail(services, incident)

    try:
        await services.queue.enqueue(Job(kind=JobKind.INVESTIGATE, incident_id=incident.id))
    except Exception as error:
        # Leaving it queued would hold the fingerprint and reject the sender's retry as a
        # duplicate. Failed frees the fingerprint, so the retry opens a fresh incident.
        log.exception("api.enqueue_failed")
        await services.repository.fail_incident(
            incident.id, (IncidentStatus.QUEUED,), _QUEUE_FAILED
        )
        metrics.ALERTS.labels(outcome="enqueue_failed").inc()
        raise ApiError(503, _QUEUE_FAILED, "queue_unavailable") from error
    metrics.ALERTS.labels(outcome="created").inc()
    return await _detail(services, incident)


@incidents.get("", response_model=IncidentPage)
async def list_incidents(
    services: ServicesDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: IncidentStatus | None = None,
) -> IncidentPage:
    items, total = await services.repository.list_incidents(limit, offset, status)
    return IncidentPage(
        items=[IncidentSummary.of(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@incidents.get("/{incident_id}", response_model=IncidentDetail, dependencies=incident_scoped)
async def get_incident(incident_id: str, services: ServicesDep) -> IncidentDetail:
    incident = await services.repository.get_incident(incident_id)
    if incident is None:
        raise ApiError(404, _INCIDENT_NOT_FOUND)
    return await _detail(services, incident)


@incidents.get(
    "/{incident_id}/events",
    response_class=StreamingResponse,
    dependencies=incident_scoped,
)
async def stream_events(
    incident_id: str,
    request: Request,
    services: ServicesDep,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """Replays events after Last-Event-ID, then follows new ones.

    The stream ends with an `end` event once the incident is terminal or awaiting approval.
    Reconnect with Last-Event-ID after a decision to follow the remediation.
    """
    if await services.repository.get_status(incident_id) is None:
        raise ApiError(404, _INCIDENT_NOT_FOUND)
    return StreamingResponse(
        event_stream(
            services.repository,
            incident_id,
            parse_last_event_id(last_event_id),
            request.is_disconnected,
            services.sse_poll_seconds,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@incidents.post(
    "/{incident_id}/proposals/{proposal_id}/approve",
    response_model=DecisionResponse,
    dependencies=[RequireKey, *incident_scoped],
)
async def approve_proposal(
    incident_id: str,
    proposal_id: str,
    decision: DecisionRequest,
    services: ServicesDep,
) -> DecisionResponse:
    repository = services.repository
    try:
        proposal = await repository.approve_proposal(incident_id, proposal_id, decision.decided_by)
    except NotFoundError as error:
        raise ApiError(404, _PROPOSAL_NOT_FOUND) from error
    except DecisionConflictError as error:
        raise ApiError(409, str(error)) from error

    log.info("api.proposal_approved", proposal_id=proposal_id, decided_by=decision.decided_by)
    job = Job(kind=JobKind.REMEDIATE, incident_id=incident_id, proposal_id=proposal_id)
    try:
        await services.queue.enqueue(job)
    except Exception as error:
        log.exception("api.enqueue_failed")
        await repository.fail_incident(incident_id, (IncidentStatus.REMEDIATING,), _QUEUE_FAILED)
        raise ApiError(503, _QUEUE_FAILED, "queue_unavailable") from error
    return DecisionResponse(proposal=proposal, incident_status=IncidentStatus.REMEDIATING)


@incidents.post(
    "/{incident_id}/proposals/{proposal_id}/reject",
    response_model=DecisionResponse,
    dependencies=[RequireKey, *incident_scoped],
)
async def reject_proposal(
    incident_id: str,
    proposal_id: str,
    decision: DecisionRequest,
    services: ServicesDep,
) -> DecisionResponse:
    try:
        proposal, status = await services.repository.reject_proposal(
            incident_id, proposal_id, decision.decided_by
        )
    except NotFoundError as error:
        raise ApiError(404, _PROPOSAL_NOT_FOUND) from error
    except DecisionConflictError as error:
        raise ApiError(409, str(error)) from error
    log.info("api.proposal_rejected", proposal_id=proposal_id, decided_by=decision.decided_by)
    return DecisionResponse(proposal=proposal, incident_status=status)


@router.get("/healthz", response_model=HealthResponse, tags=["ops"])
async def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/readyz", response_model=HealthResponse, tags=["ops"])
async def readyz(services: ServicesDep) -> HealthResponse:
    try:
        await services.repository.ping()
    except Exception as error:
        log.warning("api.not_ready", exc_info=True)
        raise ApiError(503, "Database unavailable.", "not_ready") from error
    return HealthResponse(status="ok")


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics(services: ServicesDep) -> Response:
    try:
        metrics.set_incident_counts(await services.repository.count_by_status())
    except Exception:
        # A scrape must still return the process metrics while the database is down.
        log.warning("api.metrics_db_unavailable", exc_info=True)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request) -> HTMLResponse:
    page: HTMLResponse = request.app.state.index_page
    return page


router.include_router(incidents)
