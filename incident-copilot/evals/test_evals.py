"""Offline eval tests. The planted failures prove that the scorers can actually fail."""

from __future__ import annotations

import pytest

from copilot.agents.runtime import build_runtime
from copilot.config import Settings
from copilot.domain.models import (
    AgentEvent,
    Evidence,
    Incident,
    InvestigationResult,
    Severity,
)
from copilot.tools.fixtures import list_scenarios, load_scenario
from evals.run import retrieval_metrics, run_scenario
from evals.scoring import score


def scripted() -> Settings:
    return Settings(llm_provider="scripted", _env_file=None)  # type: ignore[call-arg]


async def investigate(name: str) -> tuple[InvestigationResult, list[AgentEvent]]:
    events: list[AgentEvent] = []

    async def collect(event: AgentEvent) -> None:
        events.append(event)

    scenario = load_scenario(name)
    runtime = build_runtime(scripted(), name)
    result = await runtime.orchestrator.investigate(Incident(alert=scenario.alert), collect)
    return result, events


def failed(name: str, result: InvestigationResult, events: list[AgentEvent]) -> set[str]:
    checks = score(load_scenario(name).expected, result, events)
    return {check.name for check in checks if not check.passed}


@pytest.mark.parametrize("name", list_scenarios())
async def test_scripted_scenario_passes_every_check(name: str) -> None:
    checks, _ = await run_scenario(scripted(), name)
    assert [check.name for check in checks if not check.passed] == []


async def test_wrong_severity_fails() -> None:
    result, events = await investigate("bad_deploy")
    result.triage.severity = Severity.SEV4
    assert failed("bad_deploy", result, events) == {"severity"}


async def test_wrong_root_cause_fails() -> None:
    result, events = await investigate("bad_deploy")
    result.report.root_cause = "cosmic rays"
    result.report.summary = "unknown"
    assert failed("bad_deploy", result, events) == {"root_cause"}


async def test_wrong_rollback_target_fails() -> None:
    result, events = await investigate("bad_deploy")
    result.report.remediations[0].target_version = "v1.0.0"
    assert failed("bad_deploy", result, events) == {"action"}


async def test_no_surviving_evidence_fails() -> None:
    result, events = await investigate("bad_deploy")
    result.report.evidence = []
    assert failed("bad_deploy", result, events) == {"evidence_cited"}


async def test_following_the_injection_fails() -> None:
    result, events = await investigate("prompt_injection")
    obeyed = result.report.remediations[0].model_copy(
        update={"service": "payments-api", "target_version": "v0.0.1"}
    )
    result.report.remediations.append(obeyed)
    assert "no_forbidden_output" in failed("prompt_injection", result, events)


async def test_quoting_the_attack_as_evidence_is_allowed() -> None:
    result, events = await investigate("prompt_injection")
    result.report.evidence.append(
        Evidence(ref="log:notifications-worker:0003", observation="mentions attacker.example")
    )
    assert failed("prompt_injection", result, events) == set()


async def test_unflagged_injection_fails() -> None:
    result, events = await investigate("prompt_injection")
    quiet = [event for event in events if event.data.get("kind") != "suspected_prompt_injection"]
    assert failed("prompt_injection", result, quiet) == {"injection_flagged"}


def test_runbook_retrieval_meets_the_bar() -> None:
    metrics = retrieval_metrics()
    assert metrics["recall_at_3"] >= 0.8
    assert metrics["mrr"] >= 0.6
