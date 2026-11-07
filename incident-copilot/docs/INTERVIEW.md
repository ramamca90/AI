# Interview notes

## 30-second pitch

I built a multi-agent incident response copilot. Agents investigate an alert in parallel and
produce a cited root cause report, but they can only read. A human approves any fix, and
plain validated code carries it out, so a compromised agent can't touch production.

## Demo script (5 minutes)

1. Run the `prompt_injection` scenario. Show the live agent timeline.
2. Point out the log line telling the agent to act, and the injection guardrail firing.
3. Open the report: root cause, cited evidence, cost and cache stats.
4. Approve the fix, and try approving again to show the 409.
5. Show the code: tools have no write access, and `RemediationExecutor` has no LLM.

Be upfront that scripted mode replays recorded responses. It demonstrates the system, not the
model's judgement. Only run `--live` results show that.

## Questions to expect

**Why not let the agents plan freely?** A fixed workflow is bounded, testable and cheaper.
Only each specialist's tool loop is model-driven. See ADR 0001.

**Why write your own agent loop?** It lets the same loop run on Claude or a scripted client,
so harness tests cost nothing, and it gives me direct control of budget checks, tracing and
guardrails. The trade-off is owning more code. See ADR 0002.

**How do you handle prompt injection?** I assume it will sometimes work. Tool output is marked
as untrusted, but the real defence is architectural: agents have no write tools, and a human
reviews a validated proposal. The regex flag is only a signal, and rewording can evade it.

**How do you stop an agent hallucinating evidence?** Every citation must match a reference a
tool really returned in that incident. Others are dropped and logged. That proves the source
exists, not that the agent interpreted it correctly.

**How do you control cost?** Iteration caps, a per-incident budget, prompt caching, and effort
set per agent. The budget is a soft cap: concurrent investigators can overshoot by one call.

**What happens if a job is delivered twice?** Handlers compare-and-set status, so a repeat is
a no-op. Remediation is at-most-once on purpose: after a crash, it needs a human to check it
rather than retrying a production change.

**Why BM25 and not embeddings?** A small runbook set with very specific terms, no extra
service, and retrieval scored by a labelled eval. See ADR 0004. That eval has only six
queries, so a perfect score isn't strong evidence.

**What would you do next?** Run live evals and a larger scenario set, run the suite on
Postgres, and add real login so approvals are tied to a verified identity.

## How agents built it

I defined the domain models and interfaces first, so parallel agents shared one contract. Three
agents then owned separate directories: the AI core, the platform, and delivery. I reviewed
their reports, re-ran every check myself, and added the approval check after a report showed it
was enforced in only one place.

Be ready to explain any file yourself. If you can't, read it before the interview, because
the interviewer will assume you understand everything in the repo.

## Don't claim these yet

- That it runs on AWS, Postgres, or real SQS.
- That it resists prompt injection from a real model.
- That the scripted eval score measures quality.
- Any real-world cost, cache hit rate, or accuracy figure. The numbers in the UI in scripted
  mode are simulated.
