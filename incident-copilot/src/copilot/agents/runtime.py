"""Composition of the AI core: the one place that picks an LLM client and fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from copilot.agents.orchestrator import Orchestrator
from copilot.agents.remediation import RemediationExecutor
from copilot.config import Settings
from copilot.domain.ports import LLMClient
from copilot.llm.scripted import ScriptedLLM
from copilot.rag.bm25 import BM25Retriever
from copilot.tools.fixtures import FixtureActuator, FixtureTelemetry, Scenario, load_scenario

DEFAULT_SCENARIO = "bad_deploy"


class RuntimeConfigError(ValueError):
    """Settings can't produce a working runtime."""


@dataclass(frozen=True)
class Runtime:
    orchestrator: Orchestrator
    executor: RemediationExecutor


@lru_cache(maxsize=1)
def _retriever() -> BM25Retriever:
    return BM25Retriever()


def _build_llm(settings: Settings, scenario: Scenario) -> LLMClient:
    if settings.llm_provider == "scripted":
        return ScriptedLLM(scenario.script)

    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else ""
    if not key:
        raise RuntimeConfigError("llm_provider is 'anthropic' but ANTHROPIC_API_KEY is not set")
    # Imported here so that the scripted path never loads the SDK.
    from copilot.llm.anthropic_client import AnthropicLLM

    return AnthropicLLM(api_key=key, model=settings.llm_model)


def build_runtime(settings: Settings, scenario: str | None) -> Runtime:
    """Build the runtime for one scenario.

    Telemetry is always a fixture: this project has no live telemetry backend, so a run with
    `llm_provider="anthropic"` is a real model looking at simulated production.
    """
    loaded = load_scenario(scenario or DEFAULT_SCENARIO)
    telemetry = FixtureTelemetry(loaded)
    return Runtime(
        orchestrator=Orchestrator(_build_llm(settings, loaded), telemetry, _retriever(), settings),
        executor=RemediationExecutor(telemetry, FixtureActuator()),
    )
