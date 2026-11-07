"""Token cost calculation. Prices are USD per million tokens.

Cache writes are the 5-minute TTL rate, 1.25x input. The client never asks for the 1-hour TTL.
Haiku 5.5 moves to a higher tier above 100K prompt tokens; that tier is not modelled because no
agent here sends prompts that large.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from copilot.domain.models import TokenUsage

logger = logging.getLogger(__name__)

_PER_TOKEN = 1 / 1_000_000
_CACHE_WRITE_MULTIPLIER = 1.25


@dataclass(frozen=True)
class ModelPrice:
    input: float
    output: float
    cache_read: float

    @property
    def cache_write(self) -> float:
        return self.input * _CACHE_WRITE_MULTIPLIER


PRICES: dict[str, ModelPrice] = {
    "claude-opus-5-5": ModelPrice(input=4.0, output=20.0, cache_read=0.20),
    "claude-sonnet-5-5": ModelPrice(input=2.0, output=10.0, cache_read=0.20),
    "claude-haiku-5-5": ModelPrice(input=0.10, output=0.50, cache_read=0.01),
    # Refusal fallback targets. A fallback attempt bills at its own model's rate, so without
    # these a rescued request would count as free and the incident budget would under-report.
    "claude-opus-5": ModelPrice(input=5.0, output=25.0, cache_read=0.50),
    "claude-opus-4-8": ModelPrice(input=5.0, output=25.0, cache_read=0.50),
}


@dataclass(frozen=True)
class Cost:
    usd: float
    # False means the model is not in PRICES, so `usd` is 0 and says nothing about real spend.
    priced: bool


def normalize_model(model: str) -> str:
    """Map `sonnet-5-5` and dated IDs like `claude-opus-5-5-20261001` onto the price table."""
    stripped = re.sub(r"-\d{8}$", "", model)
    return stripped if stripped.startswith("claude-") else f"claude-{stripped}"


def compute_cost(
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> Cost:
    price = PRICES.get(normalize_model(model))
    if price is None:
        logger.warning("no price for model %s; reporting zero cost", model)
        return Cost(usd=0.0, priced=False)
    usd = _PER_TOKEN * (
        input_tokens * price.input
        + output_tokens * price.output
        + cache_read_tokens * price.cache_read
        + cache_write_tokens * price.cache_write
    )
    return Cost(usd=usd, priced=True)


def priced_usage(
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> tuple[TokenUsage, bool]:
    """Build a `TokenUsage`, returning alongside it whether the model had a known price."""
    cost = compute_cost(
        model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
    )
    usage = TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        cost_usd=cost.usd,
    )
    return usage, cost.priced
