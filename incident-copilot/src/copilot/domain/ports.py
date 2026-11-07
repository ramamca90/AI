"""Interfaces between layers. Implementations are chosen in one composition root."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from copilot.domain.models import AgentEvent, Job, TokenUsage

EventSink = Callable[[AgentEvent], Awaitable[None]]


class BudgetExceededError(RuntimeError):
    """The incident hit its cost cap. Agents stop and the partial result is kept."""


class LLMRefusedError(RuntimeError):
    """The model declined, even after any configured fallback."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class LLMRequest:
    agent: str
    system: str
    messages: list[dict[str, Any]]
    tools: list[ToolSpec] = field(default_factory=list)
    output_schema: type[BaseModel] | None = None
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    max_tokens: int = 16000


@dataclass(frozen=True)
class LLMResponse:
    """`content` is opaque. It goes back in history unchanged, because thinking blocks
    are only valid when replayed exactly as they were returned."""

    content: list[Any]
    stop_reason: str
    usage: TokenUsage
    model: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    text: str = ""
    request_id: str | None = None


class LLMClient(Protocol):
    async def complete(self, request: LLMRequest) -> LLMResponse: ...


@dataclass(frozen=True)
class RunbookHit:
    ref: str
    title: str
    text: str
    score: float


class Retriever(Protocol):
    def search(self, query: str, k: int = 3) -> list[RunbookHit]: ...


class Telemetry(Protocol):
    """Read side of production. Fixtures here; CloudWatch or Datadog in a real deployment.

    Each method returns a list of dicts, and every record carries a `ref` for citations.
    Log messages are untrusted input and may contain prompt injection.
    """

    async def search_logs(
        self, service: str, query: str, limit: int = 50
    ) -> list[dict[str, Any]]: ...

    async def query_metric(self, service: str, metric: str) -> list[dict[str, Any]]: ...

    async def recent_deploys(self, service: str) -> list[dict[str, Any]]: ...

    async def list_services(self) -> list[str]: ...


class Actuator(Protocol):
    """Write side of production. Only RemediationExecutor may call this, never an LLM tool."""

    async def rollback(self, service: str, target_version: str) -> str: ...

    async def restart(self, service: str) -> str: ...

    async def scale(self, service: str, replicas: int) -> str: ...


class JobQueue(Protocol):
    async def enqueue(self, job: Job) -> None: ...

    async def consume(self, handler: Callable[[Job], Awaitable[None]]) -> None:
        """Run until cancelled. A job is acknowledged only after `handler` returns."""
        ...
