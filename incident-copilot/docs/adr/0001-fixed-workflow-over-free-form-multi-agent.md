# 0001: Fixed workflow over free-form multi-agent

Status: accepted

## Context

An incident goes through the same stages every time: triage, gather evidence from logs, metrics and
deploys, then synthesize a report. We could let a supervisor model decide which agent runs next, or
let agents hand work to each other. That is flexible, but the path, the cost and the runtime all
become hard to predict, and a failed run is hard to replay.

## Decision

Code orchestrates and models investigate. The pipeline is a fixed workflow: Triage, then the three
investigators in parallel, then the Synthesizer. Only the tool loop inside each specialist is
model-driven.

## Consequences

- Runs are bounded and cheap to reason about. Iteration caps and the per-incident budget map directly
  onto known stages.
- The orchestration is ordinary code, so it can be tested without a model.
- Agent events and retries have clear stage boundaries.
- The system can't invent a new path for an unusual incident. A new stage is a code change.

## When we'd revisit

If real incidents regularly need steps the pipeline can't express, such as a second round of
investigation based on the first findings, and evals show that a model-chosen route does better
enough to justify the extra cost and variance.
