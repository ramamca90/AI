"""Versioned event contracts shared by producers and consumers.

Treat these like a public API: add optional fields freely, but a breaking
change means a new `schema_version` (and consumers handling both).
"""

import uuid
from decimal import Decimal

from pydantic import BaseModel


class EventTypes:
    USER_REGISTERED = "identity.user.registered"
    ORDER_CREATED = "orders.order.created"
    ORDER_CANCELLED = "orders.order.cancelled"


class UserRegisteredData(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str


class OrderCreatedData(BaseModel):
    order_id: uuid.UUID
    customer_id: uuid.UUID
    total_amount: Decimal
    currency: str
    item_count: int


class OrderCancelledData(BaseModel):
    order_id: uuid.UUID
    customer_id: uuid.UUID
    reason: str | None = None
