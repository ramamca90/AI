import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from orderflow_common.events import Event
from orders_service.models import Order, OrderStatus, OutboxMessage


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, order: Order) -> None:
        self._session.add(order)

    async def get(self, order_id: uuid.UUID) -> Order | None:
        return await self._session.get(Order, order_id)

    async def get_by_idempotency_key(self, customer_id: uuid.UUID, key: str) -> Order | None:
        return await self._session.scalar(
            select(Order).where(Order.customer_id == customer_id, Order.idempotency_key == key)
        )

    async def list_for_customer(
        self, customer_id: uuid.UUID, *, status: OrderStatus | None, limit: int, offset: int
    ) -> tuple[Sequence[Order], int]:
        stmt = select(Order).where(Order.customer_id == customer_id)
        if status is not None:
            stmt = stmt.where(Order.status == status.value)
        total = await self._session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = await self._session.scalars(
            stmt.order_by(Order.created_at.desc(), Order.id).limit(limit).offset(offset)
        )
        return rows.all(), int(total or 0)

    def add_outbox_event(self, event: Event) -> None:
        self._session.add(
            OutboxMessage(id=event.id, event_type=event.type, payload=event.model_dump(mode="json"))
        )
