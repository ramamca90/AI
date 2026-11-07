"""Prometheus metrics.

API and worker are separate processes, so each exposes its own counters: the API on /metrics
and the worker on WORKER_METRICS_PORT. `INCIDENTS_BY_STATUS` is the exception. It is read from
the database at scrape time, which makes it correct regardless of which process did the work.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

from copilot.domain.models import AgentEvent, EventType, IncidentStatus, TokenUsage

INCIDENTS_BY_STATUS = Gauge("copilot_incidents", "Incidents currently in each status", ["status"])
ALERTS = Counter("copilot_alerts_total", "Alerts received", ["outcome"])
JOB_DURATION = Histogram(
    "copilot_job_duration_seconds",
    "Job handling time",
    ["kind", "outcome"],
    buckets=(0.1, 0.5, 1, 5, 15, 30, 60, 120, 300, 600),
)
LLM_COST = Counter("copilot_llm_cost_usd_total", "LLM spend in US dollars")
LLM_TOKENS = Counter("copilot_llm_tokens_total", "LLM tokens by type", ["type"])
TOOL_CALLS = Counter("copilot_tool_calls_total", "Agent tool calls", ["tool"])
GUARDRAIL_EVENTS = Counter("copilot_guardrail_events_total", "Guardrail events", ["kind"])

# Tool names come from model output, and logs can steer a model. Capping the distinct values
# stops an injected stream of made-up tool names from growing a label without bound.
_MAX_TOOL_LABELS = 32
_seen_tools: set[str] = set()


def _tool_label(name: str) -> str:
    if name in _seen_tools:
        return name
    if len(_seen_tools) >= _MAX_TOOL_LABELS:
        return "other"
    _seen_tools.add(name)
    return name


def set_incident_counts(counts: dict[IncidentStatus, int]) -> None:
    for status in IncidentStatus:
        INCIDENTS_BY_STATUS.labels(status=status.value).set(counts.get(status, 0))


def record_usage(usage: TokenUsage) -> None:
    LLM_COST.inc(usage.cost_usd)
    LLM_TOKENS.labels(type="input").inc(usage.input_tokens)
    LLM_TOKENS.labels(type="output").inc(usage.output_tokens)
    LLM_TOKENS.labels(type="cache_read").inc(usage.cache_read_tokens)
    LLM_TOKENS.labels(type="cache_write").inc(usage.cache_write_tokens)


def record_event(event: AgentEvent) -> None:
    if event.type is EventType.TOOL_CALL:
        TOOL_CALLS.labels(tool=_tool_label(str(event.data.get("tool", "unknown")))).inc()
    elif event.type is EventType.GUARDRAIL:
        GUARDRAIL_EVENTS.labels(kind=str(event.data.get("kind", "unknown"))).inc()
