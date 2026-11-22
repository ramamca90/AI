import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from orderflow_common.db import get_session
from orderflow_common.security import CurrentPrincipal
from orders_service.models import OrderStatus
from orders_service.schemas import CancelOrderRequest, CreateOrderRequest, OrderPage, OrderResponse
from orders_service.service import OrderService

router = APIRouter(prefix="/v1/orders", tags=["orders"])


def get_order_service(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> OrderService:
    return OrderService(session, source=request.app.state.settings.service_name)


Service = Annotated[OrderService, Depends(get_order_service)]


@router.post(
    "",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Place an order (idempotent with Idempotency-Key)",
    responses={200: {"description": "Replay of a previous request with the same key"}},
)
async def create_order(
    body: CreateOrderRequest,
    principal: CurrentPrincipal,
    service: Service,
    response: Response,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=8, max_length=100)
    ] = None,
) -> OrderResponse:
    order, created = await service.create(principal, body, idempotency_key)
    if not created:
        response.status_code = status.HTTP_200_OK
    response.headers["Location"] = f"/v1/orders/{order.id}"
    return OrderResponse.model_validate(order)


@router.get("", response_model=OrderPage, summary="List my orders")
async def list_orders(
    principal: CurrentPrincipal,
    service: Service,
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OrderPage:
    orders, total = await service.list(principal, status=status_filter, limit=limit, offset=offset)
    return OrderPage(
        items=[OrderResponse.model_validate(o) for o in orders],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{order_id}", response_model=OrderResponse, summary="Get one order")
async def get_order(
    order_id: uuid.UUID, principal: CurrentPrincipal, service: Service
) -> OrderResponse:
    return OrderResponse.model_validate(await service.get(principal, order_id))


@router.post("/{order_id}/cancel", response_model=OrderResponse, summary="Cancel an order")
async def cancel_order(
    order_id: uuid.UUID,
    principal: CurrentPrincipal,
    service: Service,
    body: CancelOrderRequest | None = None,
) -> OrderResponse:
    order = await service.cancel(principal, order_id, body.reason if body else None)
    return OrderResponse.model_validate(order)
