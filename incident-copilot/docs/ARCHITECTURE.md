# Architecture

## Flow

```
Alert webhook -> API -> Postgres (dedupe on fingerprint) -> SQS -> Worker
Worker: Triage -> Logs + Metrics + Deploys investigators (parallel) -> Synthesizer
Report and proposals saved -> status awaiting_approval -> human approves in UI
Approval -> SQS -> RemediationExecutor (deterministic code) -> Actuator
Every step emits an AgentEvent, stored in Postgres and streamed to the UI over SSE.
```

## Layering

| Package | Owns | May import |
|---|---|---|
| `domain` | Models and ports | stdlib, pydantic |
| `llm` | `LLMClient` implementations, pricing | `domain` |
| `tools`, `rag` | Read-only agent tools, runbook search, fixtures | `domain` |
| `agents` | Agent loop, prompts, orchestrator, remediation executor | `domain`, `tools`, `rag` |
| `db`, `queue`, `observability` | Infrastructure adapters | `domain` |
| `api`, `worker` | Entry points and composition | everything |

`agents/runtime.py` is the one exception: it is the composition root for the AI core, so it
also imports `llm` and `config`.

## Key decisions

1. **Code orchestrates; models investigate.** The pipeline is a fixed workflow. Only each
   specialist's tool loop is model-driven, so runs stay bounded, testable and cheap.
2. **We own the agent loop.** An `LLMClient` port lets the same loop run on Claude or on a
   deterministic scripted client, which makes the harness testable without spending money.
3. **Agents can't act.** LLM tools are read-only. A report contains only *drafts*.
   `RemediationExecutor` is plain code that validates a draft against an allowlist and live
   service state, and it runs only after a human approves.
4. **Telemetry is untrusted.** Logs can carry prompt injection. Because tools can't write,
   a successful injection can at worst produce a bad draft, which a human still reviews.
   Tool output is wrapped as data, and the injection eval tracks the behaviour.
5. **Bounded spend.** Each agent has an iteration cap and each incident has a dollar budget.
6. **At-least-once jobs.** Handlers use compare-and-set on status, so redelivery is harmless.
