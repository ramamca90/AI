"""Shared helpers. Everything here is offline."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

import pytest

from copilot.config import Settings
from copilot.domain.models import AgentEvent, EventType, Incident
from copilot.domain.ports import LLMRequest, LLMResponse
from copilot.llm.scripted import ScriptedLLM
from copilot.rag import BM25Retriever
from copilot.tools.catalog import build_registry
from copilot.tools.fixtures import FixtureTelemetry, Scenario, load_scenario


class EventLog:
    """An `EventSink` that keeps what it receives."""

    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    async def __call__(self, event: AgentEvent) -> None:
        self.events.append(event)

    def of(self, event_type: EventType, agent: str | None = None) -> list[AgentEvent]:
        return [
            event
            for event in self.events
            if event.type == event_type and (agent is None or event.agent == agent)
        ]


class RecordingLLM(ScriptedLLM):
    """A scripted client that keeps every request it was sent."""

    def __init__(self, script: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
        super().__init__(script)
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return await super().complete(request)

    def for_agent(self, agent: str) -> list[LLMRequest]:
        return [request for request in self.requests if request.agent == agent]


def scripted_settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, llm_provider="scripted", **overrides)  # type: ignore[call-arg]


def incident_for(scenario: Scenario) -> Incident:
    return Incident(alert=scenario.alert)


def edited(scenario: Scenario, **agent_scripts: list[dict[str, Any]]) -> dict[str, Any]:
    """The scenario's script with some agents' turns replaced."""
    return {**scenario.script, **agent_scripts}


@pytest.fixture
def bad_deploy() -> Scenario:
    return load_scenario("bad_deploy")


@pytest.fixture
def telemetry(bad_deploy: Scenario) -> FixtureTelemetry:
    return FixtureTelemetry(bad_deploy)


@pytest.fixture
def retriever() -> BM25Retriever:
    return BM25Retriever()


@pytest.fixture
def registry(telemetry: FixtureTelemetry, retriever: BM25Retriever) -> Any:
    return build_registry(telemetry, retriever)


@pytest.fixture
def events() -> EventLog:
    return EventLog()


Sink = Callable[[AgentEvent], Awaitable[None]]
