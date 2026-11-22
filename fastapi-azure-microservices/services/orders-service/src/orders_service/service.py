import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from orderflow_common.errors import ConflictError, NotFoundError
from orderflow_common.events import Event
from orderflow_common.events.contracts import EventTypes, OrderCancelledData, OrderCreatedData
from orderflow_common.logging import get_logger
from orderflow_common.security import Principal
from orders_service.models import Order, OrderItem, OrderStatus
from orders_service.repository import OrderRepository
from orders_service.schemas import CreateOrderRequest

logger = get_logger(__name__)

_CENT = Decimal("0.01")


class OrderService:
    def __init__(self, session: AsyncSession, source: str) -> None:
        self._session = session
        self._orders = OrderRepository(session)
        self._source = source

    async def create(
        self, principal: Principal, request: CreateOrderRequest, idempotency_key: str | None
    ) -> tuple[Order, bool]:
        """Returns (order, created). A replayed Idempotency-Key returns the
        original order instead of charging the customer twice."""
        customer_id = principal.user_id
        if idempotency_key:
            existing = await self._orders.get_by_idempotency_key(customer_id, idempotency_key)
            if existing is not None:
                logger.info("order_idempotent_replay", order_id=str(existing.id))
                return existing, False

        items = [
            OrderItem(
                id=uuid.uuid4(),
                sku=i.sku,
                name=i.name,
                quantity=i.quantity,
                unit_price=i.unit_price,
            )
            for i in request.items
        ]
        total = sum((i.unit_price * i.quantity for i in request.items), Decimal("0"))
        order = Order(
            id=uuid.uuid4(),
            customer_id=customer_id,
            status=OrderStatus.PENDING.value,
            currency=request.currency,
            total_amount=total.quantize(_CENT, rounding=ROUND_HALF_UP),
            idempotency_key=idempotency_key,
            items=items,
        )
        self._orders.add(order)
        self._orders.add_outbox_event(
            self._event(
                EventTypes.ORDER_CREATED,
                order,
                OrderCreatedData(
                    order_id=order.id,
                    customer_id=customer_id,
                    total_amount=order.total_amount,
                    currency=order.currency,
                    item_count=sum(i.quantity for i in items),
                ).model_dump(mode="json"),
            )
        )
        try:
            await self._session.commit()  # order + outbox row: one atomic transaction
        except IntegrityError:
            # Two concurrent requests with the same Idempotency-Key: the loser
            # hits the unique constraint and returns the winner's order.
            await self._session.rollback()
            if idempotency_key:
                existing = await self._orders.get_by_idempotency_key(customer_id, idempotency_key)
                if existing is not None:
                    return existing, False
            raise
        logger.info("order_created", order_id=str(order.id), total=str(order.total_amount))
        return order, True

    async def get(self, principal: Principal, order_id: uuid.UUID) -> Order:
        order = await self._orders.get(order_id)
        # 404 (not 403) for other customers' orders: don't leak that it exists.
        if order is None or (
            order.customer_id != principal.user_id and not principal.has_role("admin")
        ):
            raise NotFoundError("Order not found")
        return order

    async def list(
        self, principal: Principal, *, status: OrderStatus | None, limit: int, offset: int
    ) -> tuple[list[Order], int]:
        rows, total = await self._orders.list_for_customer(
            principal.user_id, status=status, limit=limit, offset=offset
        )
        return list(rows), total

    async def cancel(self, principal: Principal, order_id: uuid.UUID, reason: str | None) -> Order:
        order = await self.get(principal, order_id)
        if order.status == OrderStatus.CANCELLED.value:
            raise ConflictError("Order is already cancelled")
        order.status = OrderStatus.CANCELLED.value
        self._orders.add_outbox_event(
            self._event(
                EventTypes.ORDER_CANCELLED,
                order,
                OrderCancelledData(
                    order_id=order.id, customer_id=order.customer_id, reason=reason
                ).model_dump(mode="json"),
            )
        )
        await self._session.commit()
        logger.info("order_cancelled", order_id=str(order.id))
        return order

    def _event(self, event_type: str, order: Order, data: dict) -> Event:
        return Event(
            type=event_type, source=self._source, subject=str(order.customer_id), data=data
        )
