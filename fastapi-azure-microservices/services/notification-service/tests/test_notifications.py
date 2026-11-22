import uuid

from fastapi import FastAPI
from httpx import AsyncClient

from orderflow_common.events import Event
from orderflow_common.events.contracts import EventTypes


def order_created(customer_id: uuid.UUID) -> Event:
    return Event(
        type=EventTypes.ORDER_CREATED,
        source="orders-service",
        data={
            "order_id": str(uuid.uuid4()),
            "customer_id": str(customer_id),
            "total_amount": "119.48",
            "currency": "USD",
            "item_count": 3,
        },
    )


async def test_event_becomes_notification(client: AsyncClient, app: FastAPI, auth_for) -> None:
    user_id = uuid.uuid4()
    await app.state.processor.handle(order_created(user_id))

    resp = await client.get("/v1/notifications", headers=auth_for(user_id))

    body = resp.json()
    assert body["total"] == 1
    assert body["unread"] == 1
    assert body["items"][0]["title"] == "Order received"
    assert "119.48 USD" in body["items"][0]["message"]


async def test_redelivered_event_is_processed_once(
    client: AsyncClient, app: FastAPI, auth_for
) -> None:
    user_id = uuid.uuid4()
    event = order_created(user_id)

    await app.state.processor.handle(event)
    await app.state.processor.handle(event)  # at-least-once delivery => duplicates happen

    resp = await client.get("/v1/notifications", headers=auth_for(user_id))
    assert resp.json()["total"] == 1


async def test_unknown_events_are_ignored(client: AsyncClient, app: FastAPI, auth_for) -> None:
    user_id = uuid.uuid4()
    await app.state.processor.handle(Event(type="inventory.restocked", source="x", data={}))

    resp = await client.get("/v1/notifications", headers=auth_for(user_id))
    assert resp.json()["total"] == 0


async def test_users_only_see_their_own(client: AsyncClient, app: FastAPI, auth_for) -> None:
    await app.state.processor.handle(order_created(uuid.uuid4()))

    resp = await client.get("/v1/notifications", headers=auth_for(uuid.uuid4()))
    assert resp.json()["total"] == 0


async def test_mark_read(client: AsyncClient, app: FastAPI, auth_for) -> None:
    user_id = uuid.uuid4()
    await app.state.processor.handle(
        Event(
            type=EventTypes.USER_REGISTERED,
            source="identity-service",
            data={"user_id": str(user_id), "email": "a@b.com", "full_name": "Ada"},
        )
    )
    headers = auth_for(user_id)
    notification_id = (await client.get("/v1/notifications", headers=headers)).json()["items"][0][
        "id"
    ]

    resp = await client.post(f"/v1/notifications/{notification_id}/read", headers=headers)
    unread = await client.get("/v1/notifications?unread_only=true", headers=headers)

    assert resp.json()["read_at"] is not None
    assert unread.json()["total"] == 0


async def test_consumer_loop_end_to_end(settings, auth_for) -> None:
    """Runs the real background consumer against the in-memory bus."""
    import asyncio

    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport

    from notification_service.main import create_app
    from notification_service.models import Base

    app = create_app(settings.model_copy(update={"consumer_enabled": True}))
    async with LifespanManager(app):
        async with app.state.db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        user_id = uuid.uuid4()
        await app.state.event_bus.publish(order_created(user_id))
        await asyncio.wait_for(app.state.event_bus._queue.join(), timeout=5)

        token, _ = app.state.token_service.issue(subject=str(user_id), email=None, roles=[])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.get("/v1/notifications", headers={"Authorization": f"Bearer {token}"})
    assert resp.json()["total"] == 1
