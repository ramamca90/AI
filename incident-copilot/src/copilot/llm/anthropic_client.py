"""`LLMClient` on the Claude Messages API (beta surface, non-streaming)."""

from __future__ import annotations

import logging
from functools import cache
from typing import Any, cast

import anthropic
from anthropic.types.beta import BetaMessage
from pydantic import BaseModel

from copilot.domain.models import TokenUsage
from copilot.domain.ports import LLMRequest, LLMResponse, ToolCall, ToolSpec
from copilot.llm.errors import LLMCallError, ModelRefusedError
from copilot.llm.pricing import normalize_model, priced_usage

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_MAX_RETRIES = 3
FALLBACK_BETA = "server-side-fallback-2026-07-01"
EPHEMERAL: dict[str, str] = {"type": "ephemeral"}

# Haiku 5.5 has no server-side fallback, so sending the parameter there is a 400.
_MODELS_WITHOUT_FALLBACK = ("claude-haiku-",)


@cache
def strict_output_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic schema reshaped for structured outputs.

    The SDK's `transform_schema` sets `additionalProperties: false` on every object, keeps
    `$defs` and `$ref`, keeps nullable fields as `anyOf` with null, and moves keywords the API
    rejects (numeric bounds and the like) into the description.
    """
    return anthropic.transform_schema(model)


def tool_param(spec: ToolSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        "input_schema": anthropic.transform_schema(spec.input_schema),
        "strict": True,
    }


def supports_fallback(model: str) -> bool:
    return not normalize_model(model).startswith(_MODELS_WITHOUT_FALLBACK)


class AnthropicLLM:
    """Claude client.

    Retries, including 429 and 5xx, belong to the SDK through `max_retries`. Prompt caching is
    a breakpoint on the system prompt plus automatic caching of the last block, so successive
    turns of a tool loop reuse the growing prefix.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = DEFAULT_MODEL,
        max_retries: int = DEFAULT_MAX_RETRIES,
        refusal_fallback: bool = True,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self._client = client or anthropic.AsyncAnthropic(api_key=api_key, max_retries=max_retries)
        self._model = model
        self._fallback = refusal_fallback and supports_fallback(model)
        # Models billed in this process that have no price. Their cost is reported as zero, so
        # the incident budget can't see them.
        self.unpriced_models: set[str] = set()

    async def complete(self, request: LLMRequest) -> LLMResponse:
        try:
            message = cast(BetaMessage, await self._send(request))
        except anthropic.APIStatusError as exc:
            raise LLMCallError(
                f"Anthropic API returned {exc.status_code} for agent {request.agent}",
                status_code=exc.status_code,
                request_id=exc.request_id,
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMCallError(
                f"could not reach Anthropic API for agent {request.agent}: {type(exc).__name__}"
            ) from exc

        usage = self._billed_usage(message)
        request_id = message._request_id
        logger.info(
            "llm call agent=%s model=%s stop=%s request_id=%s cost_usd=%.6f",
            request.agent,
            message.model,
            message.stop_reason,
            request_id,
            usage.cost_usd,
        )

        # Check the stop reason before touching content: a refusal may have none at all.
        stop_reason = message.stop_reason or "unknown"
        if stop_reason == "refusal":
            category = message.stop_details.category if message.stop_details else None
            raise ModelRefusedError(
                category, usage=usage, model=message.model, request_id=request_id
            )

        tool_calls: list[ToolCall] = []
        text = ""
        # A cut-off tool_use block has partial input, so it must not be parsed into a call.
        if stop_reason in ("end_turn", "tool_use"):
            tool_calls, text = _read_content(message.content)
        return LLMResponse(
            content=message.content,
            stop_reason=stop_reason,
            usage=usage,
            model=message.model,
            tool_calls=tool_calls,
            text=text,
            request_id=request_id,
        )

    async def _send(self, request: LLMRequest) -> Any:
        output_config: dict[str, Any] = {"effort": request.effort}
        if request.output_schema is not None:
            output_config["format"] = {
                "type": "json_schema",
                "schema": strict_output_schema(request.output_schema),
            }

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": request.max_tokens,
            "system": [{"type": "text", "text": request.system, "cache_control": EPHEMERAL}],
            "messages": request.messages,
            "cache_control": EPHEMERAL,
            "output_config": output_config,
        }
        if request.tools:
            ordered = sorted(request.tools, key=lambda spec: spec.name)
            kwargs["tools"] = [tool_param(spec) for spec in ordered]
        if self._fallback:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        return await self._client.beta.messages.create(**kwargs)

    def _billed_usage(self, message: BetaMessage) -> TokenUsage:
        """Sum every attempt. Top-level usage covers only the attempt that produced `message`,
        and each attempt bills at the rate of the model that ran it."""
        usage = message.usage
        entries: list[Any] = list(usage.iterations) if usage.iterations else [usage]
        total = TokenUsage()
        for entry in entries:
            model = getattr(entry, "model", None) or message.model
            entry_usage, priced = priced_usage(
                model,
                input_tokens=entry.input_tokens,
                output_tokens=entry.output_tokens,
                cache_read_tokens=entry.cache_read_input_tokens or 0,
                cache_write_tokens=entry.cache_creation_input_tokens or 0,
            )
            if not priced:
                self.unpriced_models.add(model)
            total = total + entry_usage
        return total


def _read_content(content: list[Any]) -> tuple[list[ToolCall], str]:
    """Extract tool calls and text.

    Anything before a `fallback` block belongs to the model that declined, so reading restarts
    there. The blocks themselves stay in `LLMResponse.content` unchanged.
    """
    tool_calls: list[ToolCall] = []
    text: list[str] = []
    for block in content:
        if block.type == "fallback":
            tool_calls.clear()
            text.clear()
        elif block.type == "tool_use":
            tool_calls.append(ToolCall(id=block.id, name=block.name, input=dict(block.input)))
        elif block.type == "text":
            text.append(block.text)
    return tool_calls, "".join(text)
