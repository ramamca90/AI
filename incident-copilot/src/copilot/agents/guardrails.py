"""Checks on model output that run as plain code, after each agent finishes.

The model can claim a citation, so a citation only counts if a tool returned that ref during
this incident. The ledger is written by the loop from real tool results, never by the model.
"""

from __future__ import annotations

from collections.abc import Sequence

from copilot.domain.models import AgentEvent, EventType, Evidence, Finding, RCAReport
from copilot.domain.ports import EventSink

_NO_EVIDENCE_CONFIDENCE_CAP = 0.3


def _discount(confidence: float, kept: int, total: int) -> float:
    """Scale confidence by the share of evidence that survived. No evidence at all caps it."""
    if total == 0:
        return min(confidence, _NO_EVIDENCE_CONFIDENCE_CAP)
    if kept == total:
        return confidence
    return round(confidence * kept / total, 4)


def _split(evidence: Sequence[Evidence], refs: set[str]) -> tuple[list[Evidence], list[str]]:
    kept = [item for item in evidence if item.ref in refs]
    dropped = [item.ref for item in evidence if item.ref not in refs]
    return kept, dropped


async def guard_finding(
    incident_id: str, agent: str, finding: Finding, refs: set[str], emit: EventSink
) -> Finding:
    kept, dropped = _split(finding.evidence, refs)
    confidence = _discount(finding.confidence, len(kept), len(finding.evidence))
    if dropped or confidence != finding.confidence:
        await _report(incident_id, agent, dropped, finding.confidence, confidence, emit)
    return finding.model_copy(update={"evidence": kept, "confidence": confidence})


async def guard_report(
    incident_id: str, agent: str, report: RCAReport, refs: set[str], emit: EventSink
) -> RCAReport:
    kept, dropped = _split(report.evidence, refs)
    runbook_refs = [ref for ref in report.runbook_refs if ref in refs]
    dropped += [ref for ref in report.runbook_refs if ref not in refs]
    confidence = _discount(report.confidence, len(kept), len(report.evidence))
    if not dropped and confidence == report.confidence:
        return report

    await _report(incident_id, agent, dropped, report.confidence, confidence, emit)
    # Put this in the report as well, so a reviewer sees it without opening the event trace.
    note = (
        f"[Guardrail: {len(dropped)} citation(s) dropped because no tool returned them; "
        f"confidence lowered from {report.confidence} to {confidence}.] "
        if dropped
        else f"[Guardrail: report cites no evidence; confidence capped at {confidence}.] "
    )
    return report.model_copy(
        update={
            "evidence": kept,
            "runbook_refs": runbook_refs,
            "confidence": confidence,
            "summary": note + report.summary,
        }
    )


async def _report(
    incident_id: str,
    agent: str,
    dropped: list[str],
    before: float,
    after: float,
    emit: EventSink,
) -> None:
    await emit(
        AgentEvent(
            incident_id=incident_id,
            type=EventType.GUARDRAIL,
            agent=agent,
            data={
                "kind": "unverified_evidence" if dropped else "no_evidence",
                "dropped_refs": dropped,
                "confidence_before": before,
                "confidence_after": after,
            },
        )
    )
