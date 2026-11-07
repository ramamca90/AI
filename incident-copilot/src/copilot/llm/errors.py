"""Errors raised by `LLMClient` implementations."""

from __future__ import annotations

from copilot.domain.models import TokenUsage
from copilot.domain.ports import LLMRefusedError


class ModelRefusedError(LLMRefusedError):
    """A refusal that keeps what the bare domain error can't: why it happened and what it cost.

    A refused call can still be billed, so `usage` has to reach the incident budget.
    `category` is None for refusals with no named policy category, which the API allows.
    """

    def __init__(
        self,
        category: str | None,
        *,
        usage: TokenUsage | None = None,
        model: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(f"model refused the request (category={category})")
        self.category = category
        self.usage = usage if usage is not None else TokenUsage()
        self.model = model
        self.request_id = request_id


class LLMCallError(RuntimeError):
    """The API call failed after SDK retries. Keeps the status, never the request body."""

    def __init__(
        self, message: str, *, status_code: int | None = None, request_id: str | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id
