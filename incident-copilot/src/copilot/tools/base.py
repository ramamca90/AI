"""Tool abstraction and registry.

Tools are read-only by construction: the registry refuses anything not declared read-only, and
nothing in this package accepts an `Actuator`. Changes to production go through
`RemediationExecutor`, after a human approves.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from copilot.domain.ports import ToolCall, ToolSpec
from copilot.tools.envelope import ToolOutcome, error_outcome

logger = logging.getLogger(__name__)


class ToolInput(BaseModel):
    """Base for tool arguments.

    `extra="forbid"` gives `additionalProperties: false`, which strict tool use requires. As in
    the domain's LLM output models, bounds live in validators rather than `Field(ge=...)`
    because the API rejects numeric keywords in strict schemas.
    """

    model_config = ConfigDict(extra="forbid")


class ToolError(Exception):
    """An expected failure. The message is shown to the model, so it may hold no internals."""


@dataclass(frozen=True)
class Tool[InputT: ToolInput]:
    name: str
    description: str
    input_model: type[InputT]
    handler: Callable[[InputT], Awaitable[ToolOutcome]]
    read_only: bool = True

    def spec(self) -> ToolSpec:
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        return ToolSpec(name=self.name, description=self.description, input_schema=schema)

    async def run(self, raw_input: dict[str, Any]) -> ToolOutcome:
        """Never raises for a bad call: the model gets an `is_error` result and can correct it."""
        try:
            parsed = self.input_model.model_validate(raw_input)
        except ValidationError as exc:
            # include_input=False: the rejected value may have come from a poisoned log line.
            details = exc.errors(include_input=False, include_url=False, include_context=False)
            problems = "; ".join(
                f"{'.'.join(str(part) for part in error['loc']) or 'input'}: {error['msg']}"
                for error in details
            )
            return error_outcome(self.name, f"invalid input: {problems}")
        try:
            return await self.handler(parsed)
        except ToolError as exc:
            return error_outcome(self.name, str(exc))
        except Exception as exc:
            logger.exception("tool %s failed", self.name)
            return error_outcome(self.name, f"tool failed: {type(exc).__name__}")


class ToolRegistry:
    """A set of tools an agent may call. Specs are sorted by name to keep prompt caching stable."""

    def __init__(self, tools: Iterable[Tool[Any]] = ()) -> None:
        self._tools: dict[str, Tool[Any]] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool[Any]) -> None:
        if not tool.read_only:
            raise ValueError(f"tool {tool.name} is not read-only; LLM tools must be read-only")
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name} is already registered")
        self._tools[tool.name] = tool

    @property
    def tools(self) -> list[Tool[Any]]:
        return [self._tools[name] for name in sorted(self._tools)]

    def specs(self) -> list[ToolSpec]:
        return [tool.spec() for tool in self.tools]

    def subset(self, names: Iterable[str]) -> ToolRegistry:
        return ToolRegistry(self._tools[name] for name in names)

    async def execute(self, call: ToolCall) -> ToolOutcome:
        tool = self._tools.get(call.name)
        if tool is None:
            return error_outcome(call.name, f"unknown tool; available: {sorted(self._tools)}")
        return await tool.run(call.input)
