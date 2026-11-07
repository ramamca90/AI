from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from pydantic import SecretStr
from tests.core.conftest import EventLog, RecordingLLM, edited, incident_for, scripted_settings

from copilot.agents import prompts
from copilot.agents.errors import InvestigationFailedError
from copilot.agents.orchestrator import Orchestrator
from copilot.agents.runtime import DEFAULT_SCENARIO, RuntimeConfigError, build_runtime
from copilot.config import Settings
from copilot.domain.models import EventType, Incident, Proposal, ProposalStatus
from copilot.domain.ports import BudgetExceededError, LLMRefusedError
from copilot.llm.anthropic_client import AnthropicLLM
from copilot.llm.scripted import ScriptExhaustedError
from copilot.rag import BM25Retriever
from copilot.tools.fixtures import (
    FixtureTelemetry,
    Scenario,
    ScenarioNotFoundError,
    list_scenarios,
    load_scenario,
)


def orchestrator(
    scenario: Scenario, llm: RecordingLLM, settings: Settings | None = None
) -> Orchestrator:
    return Orchestrator(
        llm, FixtureTelemetry(scenario), BM25Retriever(), settings or scripted_settings()
    )


def final(agent_turns: list[dict[str, Any]]) -> dict[str, Any]:
    return dict(agent_turns[-1]["final"])


@pytest.mark.parametrize("name", list_scenarios())
async def test_full_scripted_run_of_each_scenario(name: str) -> None:
    scenario = load_scenario(name)
    llm = RecordingLLM(scenario.script)
    events = EventLog()
    incident = incident_for(scenario)

    result = await orchestrator(scenario, llm).investigate(incident, events)

    expected = scenario.expected
    assert result.triage.severity == expected["severity"]
    assert expected["service"] in result.triage.affected_services
    text = f"{result.report.summary} {result.report.root_cause}".lower()
    for keyword in expected["root_cause_keywords"]:
        assert keyword.lower() in text
    draft = result.report.remediations[0]
    assert draft.action == expected["action"]
    assert draft.service == expected["service"]
    assert draft.target_version == expected["target_version"]
    assert draft.replicas == expected["replicas"]

    # The hand-written citations all resolve, so a clean run trips no evidence guardrail.
    guardrails = [e.data["kind"] for e in events.of(EventType.GUARDRAIL)]
    assert "unverified_evidence" not in guardrails
    assert result.report.evidence
    assert result.report.runbook_refs

    # Cost tracking ran end to end.
    assert result.usage.cost_usd > 0
    assert result.usage.input_tokens > 0
    assert result.usage.cache_read_tokens > 0
    assert incident.usage == result.usage
    assert sum(r.agent == "synthesizer" for r in llm.requests) == 2

    # A clean final state has no ERROR, and each agent both started and finished.
    assert events.of(EventType.ERROR) == []
    assert len(events.of(EventType.AGENT_STARTED)) == len(events.of(EventType.AGENT_FINISHED))


@pytest.mark.parametrize("name", list_scenarios())
async def test_scripted_proposals_pass_the_remediation_executor(name: str) -> None:
    runtime = build_runtime(scripted_settings(), name)
    scenario = load_scenario(name)
    events = EventLog()
    result = await runtime.orchestrator.investigate(incident_for(scenario), events)
    proposal = Proposal(
        incident_id="i",
        draft=result.report.remediations[0],
        status=ProposalStatus.APPROVED,
    )
    message = await runtime.executor.execute(proposal, events)
    assert scenario.expected["service"] in message


async def test_each_agent_gets_only_its_own_tools_and_effort(bad_deploy: Scenario) -> None:
    llm = RecordingLLM(bad_deploy.script)
    await orchestrator(bad_deploy, llm).investigate(incident_for(bad_deploy), EventLog())

    tools = {r.agent: {spec.name for spec in r.tools} for r in llm.requests}
    assert tools == {
        "triage": {"list_services"},
        "logs": {"list_services", "search_logs"},
        "metrics": {"list_services", "query_metric"},
        "deploys": {"list_services", "recent_deploys"},
        "synthesizer": {"search_runbooks"},
    }
    effort = {r.agent: r.effort for r in llm.requests}
    assert effort == {
        "triage": "low",
        "logs": "medium",
        "metrics": "medium",
        "deploys": "medium",
        "synthesizer": "high",
    }


async def test_only_investigators_chosen_by_triage_run() -> None:
    scenario = load_scenario("db_pool_exhausted")
    llm = RecordingLLM(scenario.script)
    result = await orchestrator(scenario, llm).investigate(incident_for(scenario), EventLog())
    assert set(result.findings) == {"logs", "metrics"}
    assert llm.for_agent("deploys") == []


async def test_triage_choosing_nobody_runs_everyone_and_says_so(bad_deploy: Scenario) -> None:
    triage = final(bad_deploy.script["triage"])
    triage["investigators"] = []
    llm = RecordingLLM(edited(bad_deploy, triage=[{"final": triage}]))
    events = EventLog()
    result = await orchestrator(bad_deploy, llm).investigate(incident_for(bad_deploy), events)
    assert set(result.findings) == {"logs", "metrics", "deploys"}
    assert events.of(EventType.GUARDRAIL)[0].data["kind"] == "no_investigators_selected"


async def test_duplicate_investigators_run_once(bad_deploy: Scenario) -> None:
    triage = final(bad_deploy.script["triage"])
    triage["investigators"] = ["logs", "logs"]
    llm = RecordingLLM(edited(bad_deploy, triage=[{"final": triage}]))
    result = await orchestrator(bad_deploy, llm).investigate(incident_for(bad_deploy), EventLog())
    assert list(result.findings) == ["logs"]


async def test_one_failed_investigator_does_not_sink_the_run(bad_deploy: Scenario) -> None:
    llm = RecordingLLM(edited(bad_deploy, metrics=[{"error": "API overloaded"}]))
    events = EventLog()
    result = await orchestrator(bad_deploy, llm).investigate(incident_for(bad_deploy), events)

    assert set(result.findings) == {"logs", "deploys"}
    assert result.report.remediations
    error = events.of(EventType.ERROR, "metrics")[0]
    assert error.data["error"] == "ScriptedFailureError"

    prompt = llm.for_agent("synthesizer")[0].messages[0]["content"]
    payload = json.loads(prompt.split("\n", 1)[1])
    assert payload["missing_investigators"] == {"metrics": "ScriptedFailureError"}
    assert "metrics" not in payload["findings"]


async def test_a_refused_investigator_counts_as_one_failure(bad_deploy: Scenario) -> None:
    llm = RecordingLLM(edited(bad_deploy, deploys=[{"refuse": "cyber"}]))
    events = EventLog()
    result = await orchestrator(bad_deploy, llm).investigate(incident_for(bad_deploy), events)
    assert "deploys" not in result.findings
    assert events.of(EventType.ERROR, "deploys")[0].data["error"] == "ModelRefusedError"


async def test_all_investigators_failing_raises(bad_deploy: Scenario) -> None:
    failed = [{"error": "down"}]
    llm = RecordingLLM(edited(bad_deploy, logs=failed, metrics=failed, deploys=failed))
    events = EventLog()
    incident = incident_for(bad_deploy)
    with pytest.raises(InvestigationFailedError):
        await orchestrator(bad_deploy, llm).investigate(incident, events)

    assert llm.for_agent("synthesizer") == []
    assert incident.triage is not None
    assert incident.usage.cost_usd > 0
    assert events.of(EventType.ERROR)[-1].agent is None


async def test_triage_failure_raises(bad_deploy: Scenario) -> None:
    llm = RecordingLLM(edited(bad_deploy, triage=[{"refuse": "bio"}]))
    with pytest.raises(LLMRefusedError):
        await orchestrator(bad_deploy, llm).investigate(incident_for(bad_deploy), EventLog())


async def test_synthesizer_failure_raises_and_keeps_partial_results(bad_deploy: Scenario) -> None:
    llm = RecordingLLM(edited(bad_deploy, synthesizer=[{"error": "down"}]))
    incident = incident_for(bad_deploy)
    with pytest.raises(RuntimeError, match="down"):
        await orchestrator(bad_deploy, llm).investigate(incident, EventLog())
    assert set(incident.findings) == {"logs", "metrics", "deploys"}
    assert incident.report is None


async def test_budget_stop_ends_the_run_and_keeps_the_spend(bad_deploy: Scenario) -> None:
    llm = RecordingLLM(bad_deploy.script)
    settings = scripted_settings(incident_budget_usd=0.0001)
    incident = incident_for(bad_deploy)
    events = EventLog()
    with pytest.raises(BudgetExceededError):
        await orchestrator(bad_deploy, llm, settings).investigate(incident, events)

    assert incident.usage.cost_usd >= 0.0001
    assert llm.for_agent("synthesizer") == []
    assert events.of(EventType.ERROR)[-1].data["error"] == "BudgetExceededError"


async def test_every_llm_call_shares_one_budget(bad_deploy: Scenario) -> None:
    """The cap fits any one agent's spend, so per-agent budgets would never trip it."""
    events = EventLog()
    await orchestrator(bad_deploy, RecordingLLM(bad_deploy.script)).investigate(
        incident_for(bad_deploy), events
    )
    largest = max(e.data["cost_usd"] for e in events.of(EventType.AGENT_FINISHED))
    settings = scripted_settings(incident_budget_usd=largest * 1.01)
    with pytest.raises(BudgetExceededError):
        await orchestrator(bad_deploy, RecordingLLM(bad_deploy.script), settings).investigate(
            incident_for(bad_deploy), EventLog()
        )


async def test_hallucinated_evidence_in_a_finding_is_dropped(bad_deploy: Scenario) -> None:
    turns = [dict(turn) for turn in bad_deploy.script["logs"]]
    finding = final(turns)
    finding["evidence"] = [
        *finding["evidence"][:1],
        {"ref": "log:checkout-api:9999", "observation": "Invented."},
    ]
    finding["confidence"] = 0.8
    turns[-1] = {"final": finding}
    llm = RecordingLLM(edited(bad_deploy, logs=turns))
    events = EventLog()
    result = await orchestrator(bad_deploy, llm).investigate(incident_for(bad_deploy), events)

    kept = result.findings["logs"]
    assert [item.ref for item in kept.evidence] == ["log:checkout-api:0002"]
    assert kept.confidence == pytest.approx(0.4)
    guardrail = events.of(EventType.GUARDRAIL, "logs")[0]
    assert guardrail.data["kind"] == "unverified_evidence"
    assert guardrail.data["dropped_refs"] == ["log:checkout-api:9999"]
    # The fake citation never reaches the synthesizer.
    assert "9999" not in llm.for_agent("synthesizer")[0].messages[0]["content"]


async def test_hallucinated_evidence_in_the_report_is_dropped_and_flagged(
    bad_deploy: Scenario,
) -> None:
    turns = [dict(turn) for turn in bad_deploy.script["synthesizer"]]
    report = final(turns)
    report["evidence"] = [
        *report["evidence"],
        {"ref": "deploy:checkout-api:v9.9.9", "observation": "Invented."},
    ]
    report["runbook_refs"] = [*report["runbook_refs"], "runbook:made-up.md#nothing"]
    turns[-1] = {"final": report}
    llm = RecordingLLM(edited(bad_deploy, synthesizer=turns))
    events = EventLog()
    result = await orchestrator(bad_deploy, llm).investigate(incident_for(bad_deploy), events)

    assert "deploy:checkout-api:v9.9.9" not in {e.ref for e in result.report.evidence}
    assert "runbook:made-up.md#nothing" not in result.report.runbook_refs
    assert result.report.confidence < report["confidence"]
    assert result.report.summary.startswith("[Guardrail: 2 citation(s) dropped")
    guardrail = events.of(EventType.GUARDRAIL, "synthesizer")[0]
    assert set(guardrail.data["dropped_refs"]) == {
        "deploy:checkout-api:v9.9.9",
        "runbook:made-up.md#nothing",
    }


async def test_a_real_looking_ref_no_tool_returned_this_incident_is_dropped(
    bad_deploy: Scenario,
) -> None:
    """The ref exists in the fixture, but this run never fetched it."""
    turns = [dict(turn) for turn in bad_deploy.script["logs"]]
    finding = final(turns)
    finding["evidence"] = [{"ref": "log:payments-api:0001", "observation": "Never read."}]
    turns[-1] = {"final": finding}
    llm = RecordingLLM(edited(bad_deploy, logs=turns))
    result = await orchestrator(bad_deploy, llm).investigate(incident_for(bad_deploy), EventLog())
    assert result.findings["logs"].evidence == []
    assert result.findings["logs"].confidence == 0


async def test_a_report_with_no_evidence_has_its_confidence_capped(bad_deploy: Scenario) -> None:
    turns = [dict(turn) for turn in bad_deploy.script["synthesizer"]]
    report = final(turns)
    report["evidence"] = []
    turns[-1] = {"final": report}
    llm = RecordingLLM(edited(bad_deploy, synthesizer=turns))
    events = EventLog()
    result = await orchestrator(bad_deploy, llm).investigate(incident_for(bad_deploy), events)
    assert result.report.confidence == pytest.approx(0.3)
    assert events.of(EventType.GUARDRAIL, "synthesizer")[0].data["kind"] == "no_evidence"


async def test_prompt_injection_is_ignored_and_flagged() -> None:
    scenario = load_scenario("prompt_injection")
    llm = RecordingLLM(scenario.script)
    events = EventLog()
    result = await orchestrator(scenario, llm).investigate(incident_for(scenario), events)

    expected = scenario.expected
    drafts = result.report.remediations
    assert all(draft.service not in expected["forbidden_services"] for draft in drafts)
    report_text = result.report.model_dump_json()
    for forbidden in expected["forbidden_strings"]:
        assert forbidden not in report_text
    assert expected["injection_ref"] in result.report.summary
    assert "prompt injection" in result.report.summary.lower()

    # Flagged by code as well, so the signal doesn't depend on what the model wrote.
    flagged = [
        event
        for event in events.of(EventType.GUARDRAIL)
        if event.data["kind"] == "suspected_prompt_injection"
    ]
    assert flagged
    assert expected["injection_ref"] in flagged[0].data["refs"]


async def test_injection_text_stays_out_of_system_prompts_and_events() -> None:
    scenario = load_scenario("prompt_injection")
    llm = RecordingLLM(scenario.script)
    events = EventLog()
    await orchestrator(scenario, llm).investigate(incident_for(scenario), events)

    assert all("attacker.example" not in request.system for request in llm.requests)
    trace = json.dumps([event.model_dump(mode="json") for event in events.events])
    assert "attacker.example" not in trace
    assert "DB_PASSWORD" not in trace


async def test_answer_key_never_reaches_the_model(bad_deploy: Scenario) -> None:
    llm = RecordingLLM(bad_deploy.script)
    await orchestrator(bad_deploy, llm).investigate(incident_for(bad_deploy), EventLog())
    for request in llm.requests:
        text = json.dumps(request.messages, default=str) + request.system
        assert "root_cause_keywords" not in text
        assert "expected" not in json.dumps(request.messages, default=str)


def test_system_prompts_are_stable_and_state_the_rules() -> None:
    agents = [
        prompts.TRIAGE,
        prompts.LOGS,
        prompts.METRICS,
        prompts.DEPLOYS,
        prompts.SYNTHESIZER,
    ]
    for prompt in agents:
        assert "untrusted data" in prompt
        assert "ref" in prompt
        assert "do not follow them" in prompt
        assert "20" not in prompt, "no dates or IDs belong in a system prompt"
    assert len(set(agents)) == 5


def test_system_prompts_do_not_shout() -> None:
    for prompt in (prompts.TRIAGE, prompts.LOGS, prompts.METRICS, prompts.SYNTHESIZER):
        words = prompt.split()
        shouted = [word for word in words if word.isupper() and len(word) > 4]
        assert shouted == []


async def test_system_prompts_are_identical_across_incidents(bad_deploy: Scenario) -> None:
    first, second = RecordingLLM(bad_deploy.script), RecordingLLM(bad_deploy.script)
    await orchestrator(bad_deploy, first).investigate(incident_for(bad_deploy), EventLog())
    await orchestrator(bad_deploy, second).investigate(incident_for(bad_deploy), EventLog())
    assert {(r.agent, r.system) for r in first.requests} == {
        (r.agent, r.system) for r in second.requests
    }


async def test_a_script_that_runs_out_is_reported_as_a_failure(bad_deploy: Scenario) -> None:
    llm = RecordingLLM(edited(bad_deploy, triage=[]))
    with pytest.raises(ScriptExhaustedError):
        await orchestrator(bad_deploy, llm).investigate(incident_for(bad_deploy), EventLog())


async def test_one_orchestrator_serves_overlapping_incidents(bad_deploy: Scenario) -> None:
    llm = RecordingLLM(bad_deploy.script)
    shared = orchestrator(bad_deploy, llm)
    first, second = incident_for(bad_deploy), incident_for(bad_deploy)
    events_a, events_b = EventLog(), EventLog()
    results = await asyncio.gather(
        shared.investigate(first, events_a), shared.investigate(second, events_b)
    )
    assert results[0].usage.cost_usd == pytest.approx(results[1].usage.cost_usd)
    assert {event.incident_id for event in events_a.events} == {first.id}


def test_runtime_defaults_to_bad_deploy_with_the_scripted_client() -> None:
    assert DEFAULT_SCENARIO == "bad_deploy"
    runtime = build_runtime(scripted_settings(), None)
    assert isinstance(runtime.orchestrator, Orchestrator)
    assert runtime.executor is not None


def test_runtime_rejects_an_unknown_scenario() -> None:
    with pytest.raises(ScenarioNotFoundError):
        build_runtime(scripted_settings(), "../../etc/passwd")


@pytest.mark.parametrize("key", [None, ""])
def test_anthropic_provider_requires_a_key(key: str | None) -> None:
    secret = None if key is None else SecretStr(key)
    settings = Settings(_env_file=None, llm_provider="anthropic", anthropic_api_key=secret)  # type: ignore[call-arg]
    with pytest.raises(RuntimeConfigError, match="ANTHROPIC_API_KEY"):
        build_runtime(settings, None)


def test_anthropic_provider_builds_the_real_client_without_calling_it() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        llm_provider="anthropic",
        anthropic_api_key=SecretStr("test-key"),
        llm_model="claude-sonnet-5-5",
    )
    runtime = build_runtime(settings, "bad_deploy")
    assert isinstance(runtime.orchestrator._llm, AnthropicLLM)
    assert runtime.orchestrator._llm._model == "claude-sonnet-5-5"


async def test_runtime_investigation_leaves_the_actuator_untouched() -> None:
    runtime = build_runtime(scripted_settings(), "bad_deploy")
    scenario = load_scenario("bad_deploy")
    await runtime.orchestrator.investigate(Incident(alert=scenario.alert), EventLog())
    assert runtime.executor.actuator.actions == []  # type: ignore[attr-defined]
