"""Deterministic offline `LLMClient`.

This tests the harness, not model quality. Every tool call and final answer below is written
by hand in a scenario file, so a passing scripted run shows the loop, tool dispatch, budget,
guardrails and orchestration work. It says nothing about whether Claude would diagnose the
incident. Only an eval against the real API can show that.

Each agent has a list of turns in its script:

    {"tool_calls": [{"name": "search_logs", "input": {...}}]}   a tool_use turn
    {"final": {...}}                                            end_turn with that JSON
    {"text": "..."}                                             end_turn with raw text
    {"text": "...", "stop_reason": "max_tokens"}                any other stop reason
    {"refuse": "cyber"}                                         raises a refusal
    {"error": "..."}                                            raises `ScriptedFailureError`
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from copilot.domain.models import TokenUsage
from copilot.domain.ports import LLMRequest, LLMResponse, ToolCall
from copilot.llm.errors import ModelRefusedError
from copilot.llm.pricing import priced_usage

_CHARS_PER_TOKEN = 4
_PRICED_AS = "claude-opus-5-5"
MODEL_LABEL = f"scripted:{_PRICED_AS}"

Script = Mapping[str, Sequence[Mapping[str, Any]]]


class ScriptExhaustedError(RuntimeError):
    """The harness asked for a turn the script doesn't have, or a tool it doesn't offer."""


class ScriptedFailureError(RuntimeError):
    """A failure the script asked for, standing in for an API error."""


class ScriptedLLM:
    """Replays a script.

    The next turn is derived from the assistant turns already in `request.messages`, so the
    client holds no state, one instance can serve overlapping incidents, and the replay only
    advances if the loop really appended the previous response to history.
    """

    def __init__(self, script: Script) -> None:
        self._script = script

    async def complete(self, request: LLMRequest) -> LLMResponse:
        turn = self._next_turn(request)
        if "error" in turn:
            raise ScriptedFailureError(str(turn["error"]))
        if "refuse" in turn:
            raise ModelRefusedError(
                str(turn["refuse"]), usage=_usage(request, ""), model=MODEL_LABEL
            )

        content, tool_calls, text = _render(request, turn)
        default_stop = "tool_use" if tool_calls else "end_turn"
        return LLMResponse(
            content=content,
            stop_reason=str(turn.get("stop_reason", default_stop)),
            usage=_usage(request, json.dumps(content, sort_keys=True)),
            model=MODEL_LABEL,
            tool_calls=tool_calls,
            text=text,
            request_id=f"scripted-{request.agent}-{_turn_index(request)}",
        )

    def _next_turn(self, request: LLMRequest) -> Mapping[str, Any]:
        turns = self._script.get(request.agent)
        if turns is None:
            raise ScriptExhaustedError(f"no script for agent {request.agent}")
        index = _turn_index(request)
        if index >= len(turns):
            raise ScriptExhaustedError(f"script for {request.agent} ended after {len(turns)} turns")
        return turns[index]


def _turn_index(request: LLMRequest) -> int:
    return sum(1 for message in request.messages if message["role"] == "assistant")


def _render(
    request: LLMRequest, turn: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[ToolCall], str]:
    index = _turn_index(request)
    # A thinking block goes first, as on the real API, so that replaying `content` untouched
    # is exercised offline as well.
    content: list[dict[str, Any]] = [
        {"type": "thinking", "thinking": "", "signature": f"scripted-{request.agent}-{index}"}
    ]
    calls = turn.get("tool_calls", [])
    if calls:
        offered = {spec.name for spec in request.tools}
        tool_calls: list[ToolCall] = []
        for position, call in enumerate(calls):
            if call["name"] not in offered:
                raise ScriptExhaustedError(
                    f"{request.agent} scripted {call['name']}, which it was not offered"
                )
            tool_call = ToolCall(
                id=f"toolu_{request.agent}_{index}_{position}",
                name=call["name"],
                input=dict(call["input"]),
            )
            tool_calls.append(tool_call)
            content.append(
                {
                    "type": "tool_use",
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "input": tool_call.input,
                }
            )
        return content, tool_calls, ""

    text = json.dumps(turn["final"], sort_keys=True) if "final" in turn else str(turn["text"])
    content.append({"type": "text", "text": text})
    return content, [], text


def _usage(request: LLMRequest, output: str) -> TokenUsage:
    """Estimate tokens at 4 chars each and model the caching of system prompt and tools."""
    tools = json.dumps([spec.input_schema for spec in request.tools], sort_keys=True)
    prefix = (len(request.system) + len(tools)) // _CHARS_PER_TOKEN
    history = len(json.dumps(request.messages, sort_keys=True, default=str)) // _CHARS_PER_TOKEN
    first_turn = _turn_index(request) == 0
    usage, _ = priced_usage(
        _PRICED_AS,
        input_tokens=max(history, 1),
        output_tokens=len(output) // _CHARS_PER_TOKEN + 1,
        cache_read_tokens=0 if first_turn else prefix,
        cache_write_tokens=prefix if first_turn else 0,
    )
    return usage
