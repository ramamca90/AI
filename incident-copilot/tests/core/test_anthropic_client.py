"""AnthropicLLM against a fake HTTP transport. These assert the actual JSON on the wire.

They show what the SDK sends and how a realistic response parses. They can't show the real API
accepts it: that needs a live call.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic
import httpx2
import pytest

from copilot.agents.budget import IncidentBudget
from copilot.agents.loop import run_agent
from copilot.domain.models import AgentEvent, Finding, RCAReport, Triage
from copilot.domain.ports import LLMRefusedError, LLMRequest, ToolSpec
from copilot.llm.anthropic_client import (
    FALLBACK_BETA,
    AnthropicLLM,
    strict_output_schema,
    tool_param,
)
from copilot.llm.errors import LLMCallError, ModelRefusedError
from copilot.tools.base import Tool, ToolInput, ToolRegistry
from copilot.tools.envelope import ToolOutcome, success_outcome

SEARCH_TOOL = ToolSpec(
    name="search_logs",
    description="Search logs.",
    input_schema={
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "Service."},
            "limit": {"type": "integer", "default": 20},
        },
        "required": ["service"],
        "additionalProperties": False,
    },
)
METRIC_TOOL = ToolSpec(
    name="query_metric",
    description="Query a metric.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
)


def message_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": "{}"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 1_000,
            "cache_creation_input_tokens": 200,
        },
    }
    return {**body, **overrides}


class FakeAnthropic:
    """Answers `/v1/messages` from a queue and keeps each raw request."""

    def __init__(self, *responses: httpx2.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx2.Request] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.responses.pop(0)

    def llm(self, **kwargs: Any) -> AnthropicLLM:
        max_retries = kwargs.pop("max_retries", 0)
        client = anthropic.AsyncAnthropic(
            api_key="test-key",
            base_url="http://anthropic.test",
            max_retries=max_retries,
            http_client=anthropic.DefaultAsyncHttpxClient(
                transport=httpx2.MockTransport(self.handle)
            ),
        )
        return AnthropicLLM(client=client, **kwargs)

    def body(self, index: int = 0) -> dict[str, Any]:
        body: dict[str, Any] = json.loads(self.requests[index].content)
        return body


def ok(body: dict[str, Any], request_id: str = "req_test123") -> httpx2.Response:
    return httpx2.Response(200, json=body, headers={"request-id": request_id})


def request(**overrides: Any) -> LLMRequest:
    fields: dict[str, Any] = {
        "agent": "logs",
        "system": "You are a test.",
        "messages": [{"role": "user", "content": "hello"}],
    }
    return LLMRequest(**{**fields, **overrides})


async def test_wire_request_has_exactly_the_verified_shape() -> None:
    fake = FakeAnthropic(ok(message_body()))
    await fake.llm().complete(
        request(tools=[SEARCH_TOOL], output_schema=Triage, effort="high", max_tokens=16000)
    )

    assert fake.requests[0].url.path == "/v1/messages"
    assert fake.requests[0].headers["anthropic-beta"] == FALLBACK_BETA
    body = fake.body()
    assert body["model"] == "claude-opus-5-5"
    assert body["max_tokens"] == 16000
    assert body["fallbacks"] == "default"
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["system"] == [
        {"type": "text", "text": "You are a test.", "cache_control": {"type": "ephemeral"}}
    ]
    assert body["output_config"]["effort"] == "high"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert body["tools"][0]["strict"] is True
    assert body["tools"][0]["input_schema"]["additionalProperties"] is False
    assert "stream" not in body or body["stream"] is False


async def test_wire_request_omits_every_parameter_the_model_rejects() -> None:
    fake = FakeAnthropic(ok(message_body()))
    await fake.llm().complete(request(tools=[SEARCH_TOOL], output_schema=Finding))
    body = fake.body()
    for rejected in ("temperature", "top_p", "top_k", "thinking", "tool_choice"):
        assert rejected not in body
    assert body["messages"][-1]["role"] == "user", "a trailing assistant turn is a prefill"


async def test_without_a_schema_only_effort_is_sent() -> None:
    fake = FakeAnthropic(ok(message_body()))
    await fake.llm().complete(request(effort="low"))
    assert fake.body()["output_config"] == {"effort": "low"}
    assert "tools" not in fake.body()


async def test_tool_order_is_deterministic_so_the_cache_prefix_is_stable() -> None:
    fake = FakeAnthropic(ok(message_body()), ok(message_body()))
    llm = fake.llm()
    await llm.complete(request(tools=[SEARCH_TOOL, METRIC_TOOL]))
    await llm.complete(request(tools=[METRIC_TOOL, SEARCH_TOOL]))
    assert [tool["name"] for tool in fake.body()["tools"]] == ["query_metric", "search_logs"]
    assert fake.requests[0].content == fake.requests[1].content


def test_haiku_gets_no_fallback_because_it_has_none() -> None:
    llm = AnthropicLLM(api_key="test-key", model="claude-haiku-5-5")
    assert llm._fallback is False


async def test_fallback_can_be_switched_off() -> None:
    fake = FakeAnthropic(ok(message_body()))
    await fake.llm(refusal_fallback=False).complete(request())
    assert "fallbacks" not in fake.body()
    assert "anthropic-beta" not in fake.requests[0].headers


def _objects(schema: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            found.append(schema)
        for value in schema.values():
            found.extend(_objects(value))
    elif isinstance(schema, list):
        for value in schema:
            found.extend(_objects(value))
    return found


def _refs(schema: Any) -> list[str]:
    found: list[str] = []
    if isinstance(schema, dict):
        if isinstance(schema.get("$ref"), str):
            found.append(schema["$ref"])
        for value in schema.values():
            found.extend(_refs(value))
    elif isinstance(schema, list):
        for value in schema:
            found.extend(_refs(value))
    return found


@pytest.mark.parametrize("model", [Triage, Finding, RCAReport])
def test_output_schemas_meet_structured_output_rules(model: Any) -> None:
    schema = strict_output_schema(model)
    objects = _objects(schema)
    assert objects
    assert all(item["additionalProperties"] is False for item in objects)
    text = json.dumps(schema)
    for banned in ('"minimum"', '"maximum"', '"minLength"', '"maxLength"', '"pattern"'):
        assert banned not in text
    for ref in _refs(schema):
        assert ref.startswith("#/$defs/")
        assert ref.removeprefix("#/$defs/") in schema["$defs"]


def test_nullable_fields_stay_anyof_with_null_and_required() -> None:
    schema = strict_output_schema(RCAReport)
    draft = schema["$defs"]["RemediationDraft"]
    assert {"type": "null"} in draft["properties"]["target_version"]["anyOf"]
    assert {"type": "string"} in draft["properties"]["target_version"]["anyOf"]
    assert "target_version" in draft["required"]
    finding = strict_output_schema(Finding)
    assert {"type": "null"} in finding["properties"]["suspected_cause"]["anyOf"]


def test_tool_param_keeps_required_and_turns_defaults_into_description_text() -> None:
    param = tool_param(SEARCH_TOOL)
    assert param["input_schema"]["required"] == ["service"]
    assert "default" not in param["input_schema"]["properties"]["limit"]


async def test_tool_use_response_is_parsed_and_content_is_kept_as_returned() -> None:
    body = message_body(
        stop_reason="tool_use",
        content=[
            {"type": "thinking", "thinking": "", "signature": "sig-abc"},
            {"type": "text", "text": "Checking logs."},
            {"type": "tool_use", "id": "toolu_1", "name": "search_logs", "input": {"service": "x"}},
            {"type": "tool_use", "id": "toolu_2", "name": "query_metric", "input": {}},
        ],
    )
    fake = FakeAnthropic(ok(body, request_id="req_abc"))
    response = await fake.llm().complete(request())

    assert response.stop_reason == "tool_use"
    assert [call.name for call in response.tool_calls] == ["search_logs", "query_metric"]
    assert response.tool_calls[0].input == {"service": "x"}
    assert response.text == "Checking logs."
    assert response.request_id == "req_abc"
    assert [block.type for block in response.content] == [
        "thinking",
        "text",
        "tool_use",
        "tool_use",
    ]


async def test_replayed_content_is_byte_equivalent_on_the_wire() -> None:
    """Thinking blocks are only valid if replayed exactly, so check what actually gets sent."""
    content = [
        {"type": "thinking", "thinking": "", "signature": "sig-abc"},
        {"type": "text", "text": "Checking logs."},
        {"type": "tool_use", "id": "toolu_1", "name": "search_logs", "input": {"service": "x"}},
    ]
    fake = FakeAnthropic(
        ok(message_body(stop_reason="tool_use", content=content)), ok(message_body())
    )
    llm = fake.llm()
    first = await llm.complete(request())
    await llm.complete(
        request(
            messages=[
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": first.content},
                {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "{}"}],
                },
            ]
        )
    )
    assert fake.body(1)["messages"][1]["content"] == content


async def test_usage_comes_from_iterations_at_each_attempts_own_rate() -> None:
    body = message_body(
        model="claude-opus-4-8",
        usage={
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "iterations": [
                {
                    "type": "message",
                    "model": "claude-opus-5-5",
                    "input_tokens": 1_000,
                    "output_tokens": 10,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
                {
                    "type": "fallback_message",
                    "model": "claude-opus-4-8",
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
            ],
        },
    )
    fake = FakeAnthropic(ok(body))
    response = await fake.llm().complete(request())

    assert response.usage.input_tokens == 1_100
    assert response.usage.output_tokens == 60
    expected = (1_000 * 4 + 10 * 20 + 100 * 5 + 50 * 25) / 1_000_000
    assert response.usage.cost_usd == pytest.approx(expected)


async def test_top_level_usage_is_used_when_there_are_no_iterations() -> None:
    fake = FakeAnthropic(ok(message_body()))
    usage = (await fake.llm().complete(request())).usage
    assert (usage.input_tokens, usage.output_tokens) == (100, 50)
    assert (usage.cache_read_tokens, usage.cache_write_tokens) == (1_000, 200)
    expected = (100 * 4 + 50 * 20 + 1_000 * 0.2 + 200 * 5) / 1_000_000
    assert usage.cost_usd == pytest.approx(expected)


async def test_unpriced_fallback_model_is_flagged_rather_than_crashing() -> None:
    fake = FakeAnthropic(ok(message_body(model="claude-future-9")))
    llm = fake.llm()
    response = await llm.complete(request())
    assert response.usage.cost_usd == 0.0
    assert llm.unpriced_models == {"claude-future-9"}


async def test_refusal_raises_with_category_and_billed_usage() -> None:
    body = message_body(
        stop_reason="refusal",
        content=[],
        stop_details={"type": "refusal", "category": "cyber", "explanation": None},
    )
    fake = FakeAnthropic(ok(body, request_id="req_refused"))
    with pytest.raises(LLMRefusedError) as caught:
        await fake.llm().complete(request())

    assert isinstance(caught.value, ModelRefusedError)
    assert caught.value.category == "cyber"
    assert caught.value.request_id == "req_refused"
    assert caught.value.usage.input_tokens == 100


async def test_refusal_with_null_stop_details_still_raises() -> None:
    fake = FakeAnthropic(ok(message_body(stop_reason="refusal", content=[], stop_details=None)))
    with pytest.raises(ModelRefusedError) as caught:
        await fake.llm().complete(request())
    assert caught.value.category is None


async def test_max_tokens_does_not_turn_a_partial_tool_use_into_a_call() -> None:
    body = message_body(
        stop_reason="max_tokens",
        content=[{"type": "tool_use", "id": "toolu_1", "name": "search_logs", "input": {}}],
    )
    response = await FakeAnthropic(ok(body)).llm().complete(request())
    assert response.stop_reason == "max_tokens"
    assert response.tool_calls == []
    assert len(response.content) == 1


async def test_pause_turn_passes_through_with_its_content() -> None:
    body = message_body(stop_reason="pause_turn", content=[{"type": "text", "text": "partial"}])
    response = await FakeAnthropic(ok(body)).llm().complete(request())
    assert response.stop_reason == "pause_turn"
    assert len(response.content) == 1


async def test_output_before_a_fallback_block_is_not_treated_as_the_answer() -> None:
    body = message_body(
        model="claude-opus-4-8",
        content=[
            {"type": "text", "text": "partial from the declined model"},
            {
                "type": "fallback",
                "from": {"model": "claude-opus-5-5"},
                "to": {"model": "claude-opus-4-8"},
                "trigger": {"type": "refusal", "category": "cyber"},
            },
            {"type": "text", "text": '{"ok": true}'},
        ],
    )
    response = await FakeAnthropic(ok(body)).llm().complete(request())
    assert response.text == '{"ok": true}'
    assert len(response.content) == 3


async def test_fallback_block_replays_with_its_wire_field_names() -> None:
    block = {
        "type": "fallback",
        "from": {"model": "claude-opus-5-5"},
        "to": {"model": "claude-opus-4-8"},
        "trigger": {"type": "refusal", "category": "cyber"},
    }
    fake = FakeAnthropic(ok(message_body(content=[block])), ok(message_body()))
    llm = fake.llm()
    first = await llm.complete(request())
    await llm.complete(
        request(
            messages=[
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": first.content},
                {"role": "user", "content": "continue"},
            ]
        )
    )
    assert fake.body(1)["messages"][1]["content"] == [block]


async def test_sdk_retries_a_429_then_succeeds() -> None:
    fake = FakeAnthropic(
        httpx2.Response(
            429,
            json={"type": "error", "error": {"type": "rate_limit_error", "message": "slow"}},
            headers={"retry-after-ms": "1"},
        ),
        ok(message_body()),
    )
    response = await fake.llm(max_retries=1).complete(request())
    assert len(fake.requests) == 2
    assert response.stop_reason == "end_turn"


@pytest.mark.parametrize(
    ("status", "kind"),
    [(400, "invalid_request_error"), (401, "authentication_error")],
)
async def test_client_errors_are_typed_and_not_retried(status: int, kind: str) -> None:
    def error() -> httpx2.Response:
        return httpx2.Response(
            status,
            json={"type": "error", "error": {"type": kind, "message": "secret request text"}},
            headers={"request-id": "req_err"},
        )

    fake = FakeAnthropic(error(), error())
    with pytest.raises(LLMCallError) as caught:
        await fake.llm(max_retries=1).complete(request())

    assert len(fake.requests) == 1
    assert caught.value.status_code == status
    assert caught.value.request_id == "req_err"
    assert "secret request text" not in str(caught.value)


async def test_the_real_loop_runs_over_the_wire_client() -> None:
    """Scripted runs use dict blocks; this replays the SDK's own block objects through the loop."""
    tool_turn = message_body(
        stop_reason="tool_use",
        content=[
            {"type": "thinking", "thinking": "", "signature": "sig-1"},
            {"type": "tool_use", "id": "toolu_1", "name": "ping", "input": {}},
            {"type": "tool_use", "id": "toolu_2", "name": "ping", "input": {}},
        ],
    )
    finding = {
        "summary": "Done.",
        "suspected_cause": None,
        "evidence": [{"ref": "log:1", "observation": "Seen."}],
        "confidence": 0.5,
    }
    final_turn = message_body(content=[{"type": "text", "text": json.dumps(finding)}])
    fake = FakeAnthropic(ok(tool_turn), ok(final_turn))

    class NoArgs(ToolInput):
        pass

    async def ping(_: NoArgs) -> ToolOutcome:
        return success_outcome("ping", [{"ref": "log:1"}], limit=1)

    tool: Tool[NoArgs] = Tool(name="ping", description="Ping.", input_model=NoArgs, handler=ping)
    refs: set[str] = set()
    budget = IncidentBudget(10.0)

    async def discard(_: AgentEvent) -> None:
        return None

    result = await run_agent(
        agent="logs",
        incident_id="inc-1",
        llm=fake.llm(),
        system="system",
        prompt="go",
        tools=ToolRegistry([tool]),
        emit=discard,
        budget=budget,
        refs=refs,
        max_iterations=3,
        output_schema=Finding,
    )

    assert isinstance(result.output, Finding)
    assert refs == {"log:1"}
    assert budget.usage.input_tokens == 200
    sent = fake.body(1)["messages"]
    assert [message["role"] for message in sent] == ["user", "assistant", "user"]
    assert sent[1]["content"] == tool_turn["content"]
    assert [block["tool_use_id"] for block in sent[2]["content"]] == ["toolu_1", "toolu_2"]
    assert all(block["type"] == "tool_result" for block in sent[2]["content"])
