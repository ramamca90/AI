import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from orders_service.models import OrderStatus


class OrderItemIn(BaseModel):
    sku: str = Field(min_length=1, max_length=64, examples=["SKU-KEYBOARD-01"])
    name: str = Field(min_length=1, max_length=200, examples=["Mechanical keyboard"])
    quantity: int = Field(ge=1, le=1000)
    unit_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2, examples=["89.99"])


class CreateOrderRequest(BaseModel):
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    items: list[OrderItemIn] = Field(min_length=1, max_length=100)


class CancelOrderRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku: str
    name: str
    quantity: int
    unit_price: Decimal


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    status: OrderStatus
    currency: str
    total_amount: Decimal
    items: list[OrderItemOut]
    created_at: datetime
    updated_at: datetime


class OrderPage(BaseModel):
    items: list[OrderResponse]
    total: int
    limit: int
    offset: int
