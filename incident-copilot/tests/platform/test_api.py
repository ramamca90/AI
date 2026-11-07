from __future__ import annotations

import asyncio
import json
import logging

import pytest
import structlog
from tests.platform.support import AUTH, Platform, make_alert, make_result

from copilot.api.app import warn_on_default_api_key
from copilot.api.sse import event_stream, parse_last_event_id
from copilot.config import Settings
from copilot.domain.models import IncidentStatus, Job, JobKind, ProposalStatus


def alert_body(fingerprint: str = "fp-1") -> dict[str, object]:
    return make_alert(fingerprint).model_dump(mode="json")


def parse_sse(text: str) -> list[dict[str, str]]:
    frames = []
    for block in text.split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if not line.startswith(":")
        )
        if fields:
            frames.append(fields)
    return frames


async def approve(platform: Platform, incident_id: str, proposal_id: str, who: str = "ann"):
    return await platform.client.post(
        f"/v1/incidents/{incident_id}/proposals/{proposal_id}/approve",
        json={"decided_by": who},
        headers=AUTH,
    )


async def reject(platform: Platform, incident_id: str, proposal_id: str, who: str = "ann"):
    return await platform.client.post(
        f"/v1/incidents/{incident_id}/proposals/{proposal_id}/reject",
        json={"decided_by": who},
        headers=AUTH,
    )


# Alerts


async def test_alert_is_accepted_and_investigated(platform: Platform) -> None:
    response = await platform.client.post("/v1/alerts", json=alert_body(), headers=AUTH)
    assert response.status_code == 202
    assert response.json()["status"] == "queued"

    await platform.queue.join()
    assert platform.runtime.investigate_calls == [response.json()["id"]]


async def test_duplicate_alert_returns_the_existing_incident(platform: Platform) -> None:
    incident_id = await platform.fire()
    response = await platform.client.post("/v1/alerts", json=alert_body(), headers=AUTH)
    assert response.status_code == 200
    assert response.json()["id"] == incident_id
    assert len(response.json()["proposals"]) == 1


async def test_concurrent_duplicate_alerts_create_one_incident(platform: Platform) -> None:
    responses = await asyncio.gather(
        *(platform.client.post("/v1/alerts", json=alert_body(), headers=AUTH) for _ in range(10))
    )
    assert sorted(r.status_code for r in responses) == [200] * 9 + [202]
    assert len({r.json()["id"] for r in responses}) == 1
    await platform.queue.join()
    assert len(platform.runtime.investigate_calls) == 1


async def test_a_new_alert_opens_a_new_incident_after_resolution(platform: Platform) -> None:
    first = await platform.fire()
    proposal = (await platform.proposals(first))[0]
    await approve(platform, first, proposal.id)
    await platform.queue.join()
    assert await platform.status(first) is IncidentStatus.RESOLVED

    second = await platform.fire()
    assert second != first


async def test_a_failed_enqueue_returns_503_and_frees_the_fingerprint(
    platform: Platform, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(_job: Job) -> None:
        raise ConnectionError("queue down")

    with monkeypatch.context() as patch:
        patch.setattr(platform.queue, "enqueue", down)
        response = await platform.client.post("/v1/alerts", json=alert_body(), headers=AUTH)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "queue_unavailable"
    assert "queue down" not in response.text

    retried = await platform.client.post("/v1/alerts", json=alert_body(), headers=AUTH)
    assert retried.status_code == 202


async def test_invalid_alert_gets_a_validation_error_without_echoing_input(
    platform: Platform,
) -> None:
    body = alert_body()
    body["fingerprint"] = ""
    body["description"] = "x" * 4001
    response = await platform.client.post("/v1/alerts", json=body, headers=AUTH)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert {detail["field"] for detail in error["details"]} == {
        "body.fingerprint",
        "body.description",
    }
    assert "xxxx" not in response.text


# Authentication


@pytest.mark.parametrize(
    "headers",
    [{}, {"X-API-Key": "wrong"}, {"X-API-Key": ""}, {"X-API-Key": "café"}],
)
async def test_write_endpoints_reject_a_bad_key(
    platform: Platform, headers: dict[str, str]
) -> None:
    encoded = {key: value.encode("utf-8") for key, value in headers.items()}
    response = await platform.client.post("/v1/alerts", json=alert_body(), headers=encoded)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("verb", ["approve", "reject"])
async def test_decisions_need_a_key(platform: Platform, verb: str) -> None:
    incident_id = await platform.fire()
    proposal = (await platform.proposals(incident_id))[0]
    response = await platform.client.post(
        f"/v1/incidents/{incident_id}/proposals/{proposal.id}/{verb}",
        json={"decided_by": "mallory"},
    )
    assert response.status_code == 401
    assert (await platform.proposals(incident_id))[0].status is ProposalStatus.PENDING


def test_the_default_key_logs_a_loud_warning(settings: Settings) -> None:
    default = Settings(_env_file=None)  # type: ignore[call-arg]
    with structlog.testing.capture_logs() as logs:
        warn_on_default_api_key(settings)
        assert logs == []
        warn_on_default_api_key(default)
    assert logs[0]["log_level"] == "warning"
    assert "SECURITY WARNING" in logs[0]["event"]


# Reads


async def test_list_incidents_paginates_newest_first(platform: Platform) -> None:
    ids = [await platform.fire(f"fp-{n}") for n in range(3)]

    response = await platform.client.get("/v1/incidents", params={"limit": 2})
    body = response.json()
    assert body["total"] == 3
    assert [item["id"] for item in body["items"]] == [ids[2], ids[1]]

    next_page = await platform.client.get("/v1/incidents", params={"limit": 2, "offset": 2})
    assert [item["id"] for item in next_page.json()["items"]] == [ids[0]]


async def test_list_incidents_rejects_an_oversized_page(platform: Platform) -> None:
    response = await platform.client.get("/v1/incidents", params={"limit": 101})
    assert response.status_code == 422


async def test_list_incidents_filters_by_status(platform: Platform) -> None:
    await platform.fire()
    response = await platform.client.get("/v1/incidents", params={"status": "resolved"})
    assert response.json()["total"] == 0


async def test_incident_detail_includes_proposals_and_report(platform: Platform) -> None:
    incident_id = await platform.fire()
    body = (await platform.client.get(f"/v1/incidents/{incident_id}")).json()
    assert body["status"] == "awaiting_approval"
    assert body["report"]["root_cause"] == "Connection leak"
    assert body["usage"]["cache_read_tokens"] == 50
    assert body["proposals"][0]["status"] == "pending"


async def test_unknown_incident_is_a_404_in_the_error_shape(platform: Platform) -> None:
    response = await platform.client.get("/v1/incidents/nope")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"] == response.headers["X-Request-ID"]


async def test_unknown_route_uses_the_same_error_shape(platform: Platform) -> None:
    response = await platform.client.get("/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# Decisions


async def test_approve_runs_the_remediation(platform: Platform) -> None:
    incident_id = await platform.fire()
    proposal = (await platform.proposals(incident_id))[0]

    response = await approve(platform, incident_id, proposal.id)
    assert response.status_code == 200
    assert response.json()["proposal"]["decided_by"] == "ann"
    assert response.json()["incident_status"] == "remediating"

    await platform.queue.join()
    assert await platform.status(incident_id) is IncidentStatus.RESOLVED
    assert platform.runtime.execute_calls == [proposal.id]


async def test_a_second_approval_is_a_409_and_runs_nothing_extra(platform: Platform) -> None:
    incident_id = await platform.fire()
    proposal = (await platform.proposals(incident_id))[0]
    assert (await approve(platform, incident_id, proposal.id)).status_code == 200

    second = await approve(platform, incident_id, proposal.id, "bob")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "conflict"

    await platform.queue.join()
    assert platform.runtime.execute_calls == [proposal.id]
    assert (await platform.proposals(incident_id))[0].decided_by == "ann"


async def test_approving_after_rejection_is_a_409(platform: Platform) -> None:
    platform.runtime.result = make_result(remediations=2)
    incident_id = await platform.fire()
    first, _ = await platform.proposals(incident_id)
    assert (await reject(platform, incident_id, first.id)).status_code == 200
    assert (await approve(platform, incident_id, first.id)).status_code == 409
    assert (await reject(platform, incident_id, first.id)).status_code == 409


async def test_rejecting_every_proposal_closes_the_incident(platform: Platform) -> None:
    platform.runtime.result = make_result(remediations=2)
    incident_id = await platform.fire()
    first, second = await platform.proposals(incident_id)

    response = await reject(platform, incident_id, first.id)
    assert response.json()["incident_status"] == "awaiting_approval"

    response = await reject(platform, incident_id, second.id)
    assert response.json()["incident_status"] == "closed_no_action"
    assert await platform.status(incident_id) is IncidentStatus.CLOSED_NO_ACTION
    assert platform.runtime.execute_calls == []


async def test_unknown_proposal_is_a_404(platform: Platform) -> None:
    incident_id = await platform.fire()
    assert (await approve(platform, incident_id, "nope")).status_code == 404
    assert (await reject(platform, incident_id, "nope")).status_code == 404


async def test_decided_by_is_required(platform: Platform) -> None:
    incident_id = await platform.fire()
    proposal = (await platform.proposals(incident_id))[0]
    response = await platform.client.post(
        f"/v1/incidents/{incident_id}/proposals/{proposal.id}/approve",
        json={"decided_by": ""},
        headers=AUTH,
    )
    assert response.status_code == 422


async def test_a_failed_enqueue_after_approval_returns_503_and_fails_the_incident(
    platform: Platform, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident_id = await platform.fire()
    proposal = (await platform.proposals(incident_id))[0]

    async def down(_job: Job) -> None:
        raise ConnectionError("queue down")

    monkeypatch.setattr(platform.queue, "enqueue", down)
    response = await approve(platform, incident_id, proposal.id)

    assert response.status_code == 503
    assert await platform.status(incident_id) is IncidentStatus.FAILED
    assert (await platform.proposals(incident_id))[0].status is ProposalStatus.FAILED


# Server-sent events


async def test_sse_replays_all_events_and_ends_at_awaiting_approval(platform: Platform) -> None:
    incident_id = await platform.fire()
    response = await platform.client.get(f"/v1/incidents/{incident_id}/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = parse_sse(response.text)
    assert frames[-1]["event"] == "end"
    assert json.loads(frames[-1]["data"]) == {"status": "awaiting_approval"}

    events = frames[:-1]
    ids = [int(frame["id"]) for frame in events]
    assert ids == sorted(ids)
    statuses = [
        json.loads(frame["data"])["data"]["status"]
        for frame in events
        if frame["event"] == "status"
    ]
    assert statuses == ["queued", "investigating", "awaiting_approval"]
    assert "tool_call" in [frame["event"] for frame in events]


async def test_sse_resumes_after_last_event_id(platform: Platform) -> None:
    incident_id = await platform.fire()
    full = parse_sse((await platform.client.get(f"/v1/incidents/{incident_id}/events")).text)
    resume_from = full[1]["id"]

    response = await platform.client.get(
        f"/v1/incidents/{incident_id}/events", headers={"Last-Event-ID": resume_from}
    )

    assert parse_sse(response.text) == full[2:]


async def test_sse_ignores_an_unreadable_last_event_id(platform: Platform) -> None:
    incident_id = await platform.fire()
    full = (await platform.client.get(f"/v1/incidents/{incident_id}/events")).text
    response = await platform.client.get(
        f"/v1/incidents/{incident_id}/events", headers={"Last-Event-ID": "garbage"}
    )
    assert response.text == full


async def test_sse_continues_to_terminal_after_a_decision(platform: Platform) -> None:
    incident_id = await platform.fire()
    first_stream = parse_sse(
        (await platform.client.get(f"/v1/incidents/{incident_id}/events")).text
    )
    proposal = (await platform.proposals(incident_id))[0]
    await approve(platform, incident_id, proposal.id)
    await platform.queue.join()

    response = await platform.client.get(
        f"/v1/incidents/{incident_id}/events",
        headers={"Last-Event-ID": first_stream[-2]["id"]},
    )

    frames = parse_sse(response.text)
    assert json.loads(frames[-1]["data"]) == {"status": "resolved"}
    statuses = [
        json.loads(frame["data"])["data"].get("status")
        for frame in frames[:-1]
        if frame["event"] == "status"
    ]
    assert "remediating" in statuses
    assert statuses[-1] == "resolved"


async def test_sse_follows_a_running_job_to_the_end(platform: Platform) -> None:
    platform.runtime.gate = asyncio.Event()
    response = await platform.client.post("/v1/alerts", json=alert_body(), headers=AUTH)
    incident_id = response.json()["id"]
    await platform.runtime.started.wait()

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in event_stream(
                platform.repository,
                incident_id,
                0,
                _never_disconnected,
                poll_seconds=0,
            )
        ]

    stream = asyncio.create_task(collect())
    await asyncio.sleep(0)  # Let the stream reach its polling loop before the job finishes.
    platform.runtime.gate.set()
    chunks = await stream

    assert any("awaiting_approval" in chunk for chunk in chunks[:-1])
    assert chunks[-1].startswith("event: end")


async def _never_disconnected() -> bool:
    return False


async def test_sse_stops_polling_when_the_client_disconnects(platform: Platform) -> None:
    platform.runtime.gate = asyncio.Event()
    response = await platform.client.post("/v1/alerts", json=alert_body(), headers=AUTH)
    incident_id = response.json()["id"]
    await platform.runtime.started.wait()
    checks = 0

    async def disconnected_after_three_checks() -> bool:
        nonlocal checks
        checks += 1
        return checks > 3

    chunks = [
        chunk
        async for chunk in event_stream(
            platform.repository,
            incident_id,
            0,
            disconnected_after_three_checks,
            poll_seconds=0,
        )
    ]

    assert not any(chunk.startswith("event: end") for chunk in chunks)
    assert checks == 4
    platform.runtime.gate.set()


async def test_sse_on_an_unknown_incident_is_a_404(platform: Platform) -> None:
    response = await platform.client.get("/v1/incidents/nope/events")
    assert response.status_code == 404


def test_an_event_cannot_forge_sse_frames_with_newlines() -> None:
    from copilot.api.sse import format_event
    from copilot.db import StoredEvent
    from copilot.domain.models import AgentEvent, EventType

    frame = format_event(
        StoredEvent(
            1,
            AgentEvent(
                incident_id="i",
                type=EventType.TOOL_RESULT,
                data={"log": "ok\n\nevent: status\ndata: {}\n\n"},
            ),
        )
    )
    assert frame.count("\n\n") == 1
    assert frame.endswith("\n\n")


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, 0), ("12", 12), ("", 0), ("-1", 0), ("1.5", 0), ("٣", 0)],
)
def test_parse_last_event_id(value: str | None, expected: int) -> None:
    assert parse_last_event_id(value) == expected


# Operations


async def test_healthz(platform: Platform) -> None:
    response = await platform.client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_checks_the_database(
    platform: Platform, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (await platform.client.get("/readyz")).status_code == 200

    async def broken() -> None:
        raise OSError("connection string with password")

    monkeypatch.setattr(platform.repository, "ping", broken)
    response = await platform.client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "not_ready"
    assert "password" not in response.text


async def test_metrics_reports_incidents_by_status(platform: Platform) -> None:
    await platform.fire()
    response = await platform.client.get("/metrics")
    assert response.status_code == 200
    assert 'copilot_incidents{status="awaiting_approval"} 1.0' in response.text
    assert "copilot_job_duration_seconds_bucket" in response.text


async def test_request_id_is_echoed_when_safe_and_replaced_when_not(platform: Platform) -> None:
    kept = await platform.client.get("/healthz", headers={"X-Request-ID": "abc-123"})
    assert kept.headers["X-Request-ID"] == "abc-123"

    replaced = await platform.client.get("/healthz", headers={"X-Request-ID": "bad id\tvalue"})
    assert replaced.headers["X-Request-ID"] != "bad id\tvalue"
    assert len(replaced.headers["X-Request-ID"]) == 32


async def test_unhandled_errors_are_a_clean_500_with_a_request_id(
    settings: Settings, queue: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    from copilot.api.app import create_app

    app = create_app(settings, queue=queue)  # type: ignore[arg-type]
    async with app.router.lifespan_context(app):

        async def boom(*_: object, **__: object) -> None:
            raise RuntimeError("internal detail")

        monkeypatch.setattr(app.state.services.repository, "list_incidents", boom)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/v1/incidents", headers={"X-Request-ID": "req-1"})

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "internal_error",
        "message": "Internal server error.",
        "request_id": "req-1",
    }
    assert response.headers["X-Request-ID"] == "req-1"


async def test_ui_is_served_with_a_hash_based_csp(platform: Platform) -> None:
    response = await platform.client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    policy = response.headers["Content-Security-Policy"]
    assert "script-src 'sha256-" in policy
    assert "unsafe-inline" not in policy


async def test_ui_never_uses_html_injection_sinks(platform: Platform) -> None:
    text = (await platform.client.get("/")).text
    script = text.split("<script>")[1]
    for sink in ("innerHTML =", ".outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert sink not in script


async def test_job_for_remediate_kind_is_enqueued_on_approval(platform: Platform) -> None:
    jobs: list[Job] = []
    enqueue = platform.queue.enqueue

    async def spy(job: Job) -> None:
        jobs.append(job)
        await enqueue(job)

    platform.queue.enqueue = spy  # type: ignore[method-assign]
    incident_id = await platform.fire()
    proposal = (await platform.proposals(incident_id))[0]
    await approve(platform, incident_id, proposal.id)
    await platform.queue.join()

    assert [job.kind for job in jobs] == [JobKind.INVESTIGATE, JobKind.REMEDIATE]
    assert jobs[1].proposal_id == proposal.id


def test_logging_configuration_is_json_with_context(capsys: pytest.CaptureFixture[str]) -> None:
    from copilot.observability import configure_logging

    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    try:
        structlog.reset_defaults()
        configure_logging("INFO")
        with structlog.contextvars.bound_contextvars(request_id="r1", incident_id="i1"):
            structlog.get_logger("test").info("hello", extra_field=1)
            logging.getLogger("stdlib").warning("from stdlib")
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)
        structlog.reset_defaults()

    assert lines[0]["event"] == "hello"
    assert lines[0]["request_id"] == "r1"
    assert lines[0]["incident_id"] == "i1"
    assert lines[1]["event"] == "from stdlib"
    assert lines[1]["request_id"] == "r1"
