from fastapi import FastAPI
from httpx import AsyncClient

from orderflow_common.events.contracts import EventTypes

ORDER = {
    "currency": "USD",
    "items": [
        {"sku": "KB-01", "name": "Keyboard", "quantity": 2, "unit_price": "49.99"},
        {"sku": "MS-01", "name": "Mouse", "quantity": 1, "unit_price": "19.50"},
    ],
}


async def test_create_order_computes_total(client: AsyncClient, auth_for) -> None:
    resp = await client.post("/v1/orders", json=ORDER, headers=auth_for())

    assert resp.status_code == 201
    body = resp.json()
    assert body["total_amount"] == "119.48"
    assert body["status"] == "pending"
    assert resp.headers["location"] == f"/v1/orders/{body['id']}"


async def test_idempotency_key_prevents_duplicate_orders(client: AsyncClient, auth_for) -> None:
    headers = {**auth_for(), "Idempotency-Key": "checkout-7f3a9c"}

    first = await client.post("/v1/orders", json=ORDER, headers=headers)
    replay = await client.post("/v1/orders", json=ORDER, headers=headers)
    listing = await client.get("/v1/orders", headers=headers)

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert listing.json()["total"] == 1


async def test_customers_cannot_see_each_others_orders(client: AsyncClient, auth_for) -> None:
    created = await client.post("/v1/orders", json=ORDER, headers=auth_for())

    resp = await client.get(f"/v1/orders/{created.json()['id']}", headers=auth_for())

    assert resp.status_code == 404


async def test_admin_can_see_any_order(client: AsyncClient, auth_for) -> None:
    created = await client.post("/v1/orders", json=ORDER, headers=auth_for())

    resp = await client.get(f"/v1/orders/{created.json()['id']}", headers=auth_for(roles=["admin"]))

    assert resp.status_code == 200


async def test_cancel_order_and_cancel_twice_conflicts(client: AsyncClient, auth_for) -> None:
    headers = auth_for()
    order_id = (await client.post("/v1/orders", json=ORDER, headers=headers)).json()["id"]

    first = await client.post(
        f"/v1/orders/{order_id}/cancel", json={"reason": "x"}, headers=headers
    )
    second = await client.post(f"/v1/orders/{order_id}/cancel", headers=headers)

    assert first.json()["status"] == "cancelled"
    assert second.status_code == 409


async def test_list_filters_by_status_and_paginates(client: AsyncClient, auth_for) -> None:
    headers = auth_for()
    ids = [
        (await client.post("/v1/orders", json=ORDER, headers=headers)).json()["id"]
        for _ in range(3)
    ]
    await client.post(f"/v1/orders/{ids[0]}/cancel", headers=headers)

    pending = await client.get("/v1/orders?status=pending&limit=1", headers=headers)

    assert pending.json()["total"] == 2
    assert len(pending.json()["items"]) == 1


async def test_rejects_invalid_order(client: AsyncClient, auth_for) -> None:
    bad = {"currency": "usd", "items": []}

    resp = await client.post("/v1/orders", json=bad, headers=auth_for())

    assert resp.status_code == 422
    assert {tuple(e["loc"]) for e in resp.json()["errors"]} == {
        ("body", "currency"),
        ("body", "items"),
    }


async def test_requires_authentication(client: AsyncClient) -> None:
    resp = await client.get("/v1/orders")

    assert resp.status_code == 401


async def test_outbox_relay_publishes_events_exactly_once(
    client: AsyncClient, app: FastAPI, auth_for
) -> None:
    headers = auth_for()
    order_id = (await client.post("/v1/orders", json=ORDER, headers=headers)).json()["id"]
    await client.post(f"/v1/orders/{order_id}/cancel", headers=headers)
    bus = app.state.event_bus
    assert bus.published == []  # nothing is sent until the relay runs

    assert await app.state.outbox_relay.relay_once() == 2
    assert await app.state.outbox_relay.relay_once() == 0

    assert [e.type for e in bus.published] == [EventTypes.ORDER_CREATED, EventTypes.ORDER_CANCELLED]
    assert bus.published[0].data["order_id"] == order_id
    assert bus.published[0].data["total_amount"] == "119.48"


async def test_outbox_keeps_event_when_bus_is_down(
    client: AsyncClient, app: FastAPI, auth_for
) -> None:
    await client.post("/v1/orders", json=ORDER, headers=auth_for())
    bus = app.state.event_bus
    original_publish = bus.publish

    async def broken(_event) -> None:
        raise ConnectionError("service bus unavailable")

    bus.publish = broken
    assert await app.state.outbox_relay.relay_once() == 0

    bus.publish = original_publish
    assert await app.state.outbox_relay.relay_once() == 1
