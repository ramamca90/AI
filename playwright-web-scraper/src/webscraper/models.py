"""Validated output records. Scraped data is untrusted until it passes these models."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Record(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    scraped_at: datetime = Field(default_factory=_utcnow)


class Book(Record):
    url: HttpUrl
    title: str = Field(min_length=1)
    category: str = Field(min_length=1)
    upc: str = Field(min_length=1)
    price_gbp: Decimal = Field(ge=0, decimal_places=2)
    rating: int = Field(ge=0, le=5)
    in_stock: bool
    stock_count: int = Field(ge=0)
    description: str | None = None
    image_url: HttpUrl | None = None


class Quote(Record):
    text: str = Field(min_length=1)
    author: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
