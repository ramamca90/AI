# Incident Copilot

A multi-agent system that investigates production alerts and proposes a fix. **Agents can
only read. Nothing changes production until a human approves it.**

An alert triggers a triage agent, then log, metric and deploy investigators working in
parallel, then a synthesizer that writes a root cause report with cited evidence. Approved
fixes run through plain, validated code rather than through a model.

## Run it

No API key, Docker or cloud account needed. The default scripted mode replays recorded
agent responses, so it costs nothing.

```bash
uv sync
```

```bash
uv run alembic upgrade head
```

```bash
uv run copilot-api
```

Open http://127.0.0.1:8000, pick a scenario, and simulate an alert. Write actions need the
API key from `.env.example`, which is `dev-only-change-me` by default.

```bash
uv run pytest
```

```bash
uv run python -m evals.run
```

To use real Claude, set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`. This spends API
credit, capped by default at $2 per incident. The cap is soft: investigators running at the
same time can each finish one call past it.

## Architecture

```
Alert -> API -> Postgres (dedupe) -> SQS -> Worker
Worker: Triage -> Logs + Metrics + Deploys (parallel) -> Synthesizer -> report and proposals
Human approves in the UI -> SQS -> RemediationExecutor (validated code) -> production
Every step is recorded as an event and streamed live to the UI.
```

| Layer | Technology |
|---|---|
| Agents | Claude API with a custom agent loop, structured outputs, prompt caching |
| Runbook search | BM25 |
| Backend | FastAPI, async SQLAlchemy, Alembic |
| Infrastructure | AWS ECS Fargate, RDS Postgres, SQS, ALB, Terraform |
| Delivery | Docker, GitHub Actions with OIDC, CloudWatch alarms |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [the decision records](docs/adr/) and
[the deployment guide](docs/DEPLOYMENT.md).

## Safety design

- **Read-only agents.** No LLM tool can change anything, and a test enforces this.
- **Deterministic execution.** Fixes are checked against an allowlist and live service state.
- **Approval checked twice.** Once when the job claims the proposal, and again in the executor.
- **Untrusted telemetry.** Tool output is marked as data, and suspected injections are flagged.
- **Citations verified.** Evidence citing anything an agent never actually saw is removed.
- **Bounded spend.** Agents have iteration caps, and each incident has a budget.

## Project status

| Area | Status |
|---|---|
| Application, on SQLite with the local queue | Tested, and run end to end over HTTP |
| Eval scorers and runbook retrieval | Tested, including planted failures |
| Real Claude API | **Not run yet.** Request format is tested offline only |
| Model diagnosis quality and injection resistance | **Not measured.** Needs `--live` evals |
| Postgres | **Not run yet.** Concurrency guarantees are proven on SQLite only |
| SQS | Tested against the moto simulator, not real AWS |
| Docker, Terraform, GitHub Actions, scripts | **Written and syntax-checked, never run** |
| AWS deployment | **Not deployed** |

Telemetry and the production actuator are simulated fixtures. Connecting a real system means
implementing the `Telemetry` and `Actuator` interfaces.

Known gaps: `decided_by` is self-declared rather than tied to a login, read endpoints and
`/metrics` are unauthenticated, and `/readyz` checks only the database.
