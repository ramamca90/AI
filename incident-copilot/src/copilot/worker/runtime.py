"""The worker's view of the agent core.

The Protocols state exactly what the platform uses. The real implementation is imported on
first use, so nothing here pulls in the LLM stack at import time, and tests inject a fake.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Protocol

from copilot.config import Settings
from copilot.domain.models import Incident, InvestigationResult, Proposal
from copilot.domain.ports import EventSink


class Orchestrator(Protocol):
    async def investigate(self, incident: Incident, emit: EventSink) -> InvestigationResult: ...


class Executor(Protocol):
    async def execute(self, proposal: Proposal, emit: EventSink) -> str: ...


class AgentRuntime(Protocol):
    @property
    def orchestrator(self) -> Orchestrator: ...

    @property
    def executor(self) -> Executor: ...


RuntimeFactory = Callable[[Settings, str | None], AgentRuntime]


def default_runtime_factory(settings: Settings, scenario: str | None) -> AgentRuntime:
    module = importlib.import_module("copilot.agents.runtime")
    runtime: AgentRuntime = module.build_runtime(settings, scenario)
    return runtime


def default_rejection_errors() -> tuple[type[Exception], ...]:
    """Exceptions that mean the executor refused a draft, as opposed to crashing."""
    try:
        module = importlib.import_module("copilot.agents.remediation")
    except ImportError:
        return ()
    return (module.RemediationRejectedError,)
