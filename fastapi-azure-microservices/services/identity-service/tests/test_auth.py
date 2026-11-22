from fastapi import FastAPI
from httpx import AsyncClient

from orderflow_common.events.contracts import EventTypes

USER = {
    "email": "Ada@Example.com",
    "full_name": "Ada Lovelace",
    "password": "correct-horse-battery",
}


async def register_and_login(client: AsyncClient) -> str:
    await client.post("/v1/auth/register", json=USER)
    resp = await client.post(
        "/v1/auth/token", json={"email": USER["email"], "password": USER["password"]}
    )
    return resp.json()["access_token"]


async def test_register_creates_user_and_publishes_event(client: AsyncClient, app: FastAPI) -> None:
    resp = await client.post("/v1/auth/register", json=USER)

    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "ada@example.com"
    assert body["roles"] == ["customer"]
    assert "password_hash" not in body

    [event] = app.state.event_bus.published
    assert event.type == EventTypes.USER_REGISTERED
    assert event.data["user_id"] == body["id"]


async def test_duplicate_email_is_conflict(client: AsyncClient) -> None:
    await client.post("/v1/auth/register", json=USER)
    resp = await client.post("/v1/auth/register", json={**USER, "email": "ada@example.com"})

    assert resp.status_code == 409
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.json()["type"] == "urn:orderflow:error:conflict"


async def test_weak_password_is_rejected(client: AsyncClient) -> None:
    resp = await client.post("/v1/auth/register", json={**USER, "password": "short"})

    assert resp.status_code == 422
    assert resp.json()["errors"][0]["loc"] == ["body", "password"]


async def test_login_and_get_profile(client: AsyncClient) -> None:
    token = await register_and_login(client)

    resp = await client.get("/v1/users/me", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Ada Lovelace"


async def test_wrong_password_is_unauthorized(client: AsyncClient) -> None:
    await client.post("/v1/auth/register", json=USER)

    resp = await client.post(
        "/v1/auth/token", json={"email": USER["email"], "password": "wrong-password!"}
    )

    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_unknown_user_gets_same_error_as_wrong_password(client: AsyncClient) -> None:
    resp = await client.post(
        "/v1/auth/token", json={"email": "nobody@example.com", "password": "whatever-123"}
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


async def test_profile_requires_token(client: AsyncClient) -> None:
    resp = await client.get("/v1/users/me")

    assert resp.status_code == 401
    assert resp.json()["correlation_id"] == resp.headers["x-correlation-id"]


async def test_health_probes(client: AsyncClient) -> None:
    live = await client.get("/health/live")
    ready = await client.get("/health/ready")

    assert live.json()["service"] == "identity-service"
    assert ready.status_code == 200
    assert ready.json()["checks"] == {"database": "ok", "event_bus": "ok"}


async def test_correlation_id_is_propagated(client: AsyncClient) -> None:
    resp = await client.get("/health/live", headers={"X-Correlation-ID": "demo-correlation-1"})

    assert resp.headers["x-correlation-id"] == "demo-correlation-1"
    assert resp.headers["x-content-type-options"] == "nosniff"
