"""Per-incident spend tracking, shared by every agent in one investigation."""

from __future__ import annotations

from copilot.domain.models import TokenUsage
from copilot.domain.ports import BudgetExceededError


class IncidentBudget:
    """Accumulates usage and stops new LLM calls once the cap is reached.

    It is a soft cap. The check runs before a call, and a call's price is only known after it,
    so concurrent investigators can each overshoot by one in-flight call. A model with no known
    price counts as free here, so only the iteration cap bounds it.
    """

    def __init__(self, limit_usd: float) -> None:
        self.limit_usd = limit_usd
        self.usage = TokenUsage()

    def add(self, usage: TokenUsage) -> None:
        self.usage = self.usage + usage

    def check(self) -> None:
        if self.usage.cost_usd >= self.limit_usd:
            raise BudgetExceededError(
                f"incident spent ${self.usage.cost_usd:.4f} of its ${self.limit_usd:.2f} budget"
            )
