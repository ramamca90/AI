"""The agent loop: call the model, run its tools, repeat, then validate the final answer."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from copilot.agents.budget import IncidentBudget
from copilot.agents.errors import (
    AgentError,
    InvalidOutputError,
    IterationLimitError,
    TruncatedOutputError,
)
from copilot.domain.models import AgentEvent, EventType, TokenUsage
from copilot.domain.ports import (
    EventSink,
    LLMClient,
    LLMRefusedError,
    LLMRequest,
    LLMResponse,
    ToolCall,
)
from copilot.tools.base import ToolRegistry
from copilot.tools.envelope import ToolOutcome

Effort = Literal["low", "medium", "high", "xhigh", "max"]

_MAX_PREVIEW_CHARS = 80
_MAX_EVENT_REFS = 20
_SECRET = re.compile(
    r"sk-[A-Za-z0-9_-]{8,}"
    r"|AKIA[0-9A-Z]{12,}"
    r"|(?i:(password|passwd|secret|token|api[_-]?key)\s*[=:]\s*\S+)"
)
_REASK = (
    "That response was not valid output for the required schema. Problems: {problems}. "
    "Reply again with only the JSON object that matches the schema."
)


@dataclass(frozen=True)
class AgentResult[T: BaseModel]:
    output: T | None
    text: str
    iterations: int
    tool_calls: int
    messages: list[dict[str, Any]]
    # Usage of this agent alone. The incident total is on the shared `IncidentBudget`.
    usage: TokenUsage


async def run_agent[T: BaseModel](
    *,
    agent: str,
    incident_id: str,
    llm: LLMClient,
    system: str,
    prompt: str,
    tools: ToolRegistry,
    emit: EventSink,
    budget: IncidentBudget,
    refs: set[str],
    max_iterations: int,
    output_schema: type[T] | None = None,
    effort: Effort = "medium",
) -> AgentResult[T]:
    """Run one agent until it produces a final answer.

    `refs` is the incident's ledger of citable refs: every ref a tool returns is added, and the
    guardrail later checks citations against it. Failures raise, after an AGENT_FINISHED event
    that records them. `LLMRefusedError` and `BudgetExceededError` pass through unchanged.
    """
    run: _Run[T] = _Run(
        agent, incident_id, llm, system, tools, emit, budget, refs, output_schema, effort
    )
    await run.event(EventType.AGENT_STARTED, max_iterations=max_iterations, effort=effort)
    try:
        result = await run.loop(prompt, max_iterations)
    except Exception as exc:
        await run.event(
            EventType.AGENT_FINISHED, status="failed", error=type(exc).__name__, **run.stats()
        )
        raise
    await run.event(EventType.AGENT_FINISHED, status="ok", **run.stats())
    return result


class _Run[T: BaseModel]:
    """State of one `run_agent` call. History here only ever grows."""

    def __init__(
        self,
        agent: str,
        incident_id: str,
        llm: LLMClient,
        system: str,
        tools: ToolRegistry,
        emit: EventSink,
        budget: IncidentBudget,
        refs: set[str],
        output_schema: type[T] | None,
        effort: Effort,
    ) -> None:
        self.agent = agent
        self.incident_id = incident_id
        self.llm = llm
        self.system = system
        self.tools = tools
        self.emit = emit
        self.budget = budget
        self.refs = refs
        self.output_schema = output_schema
        self.effort = effort
        self.messages: list[dict[str, Any]] = []
        self.usage = TokenUsage()
        self.iterations = 0
        self.tool_call_count = 0
        self.reasked = False

    async def event(self, event_type: EventType, **data: Any) -> None:
        await self.emit(
            AgentEvent(incident_id=self.incident_id, type=event_type, agent=self.agent, data=data)
        )

    def stats(self) -> dict[str, Any]:
        return {
            "iterations": self.iterations,
            "tool_calls": self.tool_call_count,
            "input_tokens": self.usage.input_tokens,
            "output_tokens": self.usage.output_tokens,
            "cache_read_tokens": self.usage.cache_read_tokens,
            "cache_write_tokens": self.usage.cache_write_tokens,
            "cost_usd": self.usage.cost_usd,
        }

    async def loop(self, prompt: str, max_iterations: int) -> AgentResult[T]:
        self.messages.append({"role": "user", "content": prompt})
        for _ in range(max_iterations):
            self.budget.check()
            self.iterations += 1
            response = await self.complete()
            result = await self.handle(response)
            if result is not None:
                return result
        raise IterationLimitError(f"{self.agent} hit its limit of {max_iterations} iterations")

    async def complete(self) -> LLMResponse:
        request = LLMRequest(
            agent=self.agent,
            system=self.system,
            # A copy, so a client that keeps the request never sees later turns.
            messages=list(self.messages),
            tools=self.tools.specs(),
            output_schema=self.output_schema,
            effort=self.effort,
        )
        try:
            response = await self.llm.complete(request)
        except LLMRefusedError as exc:
            # A refused call can still be billed.
            usage = getattr(exc, "usage", None)
            if isinstance(usage, TokenUsage):
                self.record_usage(usage)
            raise
        self.record_usage(response.usage)
        return response

    def record_usage(self, usage: TokenUsage) -> None:
        self.usage = self.usage + usage
        self.budget.add(usage)

    async def handle(self, response: LLMResponse) -> AgentResult[T] | None:
        """Act on one response. Returns a result when the agent is done, else None."""
        stop_reason = response.stop_reason
        if stop_reason == "refusal":
            raise LLMRefusedError(f"model refused the request for agent {self.agent}")
        if stop_reason == "max_tokens":
            raise TruncatedOutputError(f"{self.agent} stopped at max_tokens")
        if stop_reason not in ("end_turn", "tool_use", "pause_turn"):
            raise AgentError(f"{self.agent} stopped with unexpected reason {stop_reason!r}")

        self.messages.append({"role": "assistant", "content": response.content})
        if stop_reason == "pause_turn":
            return None
        if stop_reason == "tool_use" or response.tool_calls:
            if not response.tool_calls:
                raise AgentError(f"{self.agent} stopped for tool_use with no tool call")
            await self.run_tools(response.tool_calls)
            return None
        return self.finish(response)

    async def run_tools(self, calls: Sequence[ToolCall]) -> None:
        """Run a turn's calls concurrently, and answer all of them in one user message."""
        self.tool_call_count += len(calls)
        for call in calls:
            await self.event(
                EventType.TOOL_CALL,
                tool=call.name,
                tool_use_id=call.id,
                input=_input_preview(call.input),
            )

        # `execute` turns tool failures into is_error results, so one bad call can't cancel
        # its siblings, and gather keeps results in call order.
        outcomes = await asyncio.gather(*(self.tools.execute(call) for call in calls))

        blocks: list[dict[str, Any]] = []
        for call, outcome in zip(calls, outcomes, strict=True):
            self.refs.update(outcome.refs)
            block: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": outcome.content,
            }
            if outcome.is_error:
                block["is_error"] = True
            blocks.append(block)
            await self.event(EventType.TOOL_RESULT, **_outcome_summary(call, outcome))
            if outcome.suspected_injection_refs:
                await self.event(
                    EventType.GUARDRAIL,
                    kind="suspected_prompt_injection",
                    tool=call.name,
                    refs=list(outcome.suspected_injection_refs),
                )
        self.messages.append({"role": "user", "content": blocks})

    def finish(self, response: LLMResponse) -> AgentResult[T] | None:
        """Accept the final turn, or queue one re-ask, or fail if that was already used."""
        output: T | None = None
        if self.output_schema is None:
            if not response.text.strip():
                raise InvalidOutputError(f"{self.agent} returned no tool call and no text")
        else:
            try:
                output = self.output_schema.model_validate_json(response.text)
            except ValidationError as exc:
                if self.reasked:
                    raise InvalidOutputError(f"{self.agent} returned invalid output twice") from exc
                self.reasked = True
                self.messages.append(
                    {"role": "user", "content": _REASK.format(problems=_problems(exc))}
                )
                return None
        return AgentResult(
            output=output,
            text=response.text,
            iterations=self.iterations,
            tool_calls=self.tool_call_count,
            messages=self.messages,
            usage=self.usage,
        )


def _problems(exc: ValidationError) -> str:
    errors = exc.errors(include_input=False, include_url=False, include_context=False)
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'response'}: {error['msg']}"
        for error in errors[:10]
    )


def _safe_text(value: str) -> str:
    return _SECRET.sub("[redacted]", value)[:_MAX_PREVIEW_CHARS]


def _input_preview(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Tool arguments for the event trace: short, scalar and with secret-like text removed."""
    preview: dict[str, Any] = {}
    for key in sorted(tool_input):
        value = tool_input[key]
        if isinstance(value, str):
            preview[key] = _safe_text(value)
        elif isinstance(value, bool | int | float) or value is None:
            preview[key] = value
    return preview


def _outcome_summary(call: ToolCall, outcome: ToolOutcome) -> dict[str, Any]:
    """Metadata only: the trace holds refs and counts, never the log bodies themselves."""
    return {
        "tool": call.name,
        "tool_use_id": call.id,
        "is_error": outcome.is_error,
        "returned": outcome.returned,
        "total": outcome.total,
        "truncated": outcome.truncated,
        "refs": list(outcome.refs[:_MAX_EVENT_REFS]),
    }
