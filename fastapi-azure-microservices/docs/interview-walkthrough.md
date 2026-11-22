# Interview walkthrough (about 15 minutes)

A suggested order for presenting this project to a hiring manager. Manager
rounds care about **why** more than **how**: trade-offs, risk, operability
and team scalability. Lead with that.

## 1. The 60-second pitch
> "OrderFlow is a small e-commerce backend split into three FastAPI services
> behind a gateway, deployed to Azure Container Apps with Bicep and GitHub
> Actions. I built it to show the things that make microservices work in
> production rather than just in a diagram: reliable messaging with an outbox,
> idempotency, zero-secret deployments with managed identity, and end-to-end
> observability."

## 2. Show it running (5 min)
1. `docker compose up --build`, then `./scripts/demo.ps1`.
2. Point out in the output:
   * the retried order returns the **same id**, so a network retry can't double-charge;
   * notifications arrive **asynchronously**: orders never called the notification service;
   * the unauthenticated call returns a **consistent problem+json** error with a correlation id.
3. `docker compose logs orders-service notification-service | Select-String <correlation-id>`
   shows one ID across both services and the async hop.
4. Kill the consumer: `docker compose stop notification-service`, place an
   order, start it again. The notification still arrives: **no lost events**.

## 3. Architecture (5 min)
Use the diagram in `docs/architecture.md`. Talk about the trade-offs:
* Why database-per-service, and what it costs (no joins, eventual consistency).
* Dual-write problem -> transactional outbox. Why identity-service *doesn't*
  use it (deliberate, cost/benefit).
* At-least-once delivery means **consumers must be idempotent** (unique `event_id`).

## 4. Production readiness (3 min)
* **Security:** per-service managed identities, least-privilege RBAC, SAS
  keys disabled on Service Bus, Key Vault references, OIDC from GitHub, non-root
  containers, CVE scan in CI.
* **Operability:** liveness vs readiness, structured logs, App Insights
  traces, graceful shutdown, migrations behind an advisory lock.
* **Delivery:** PR -> lint/test/scan; main -> dev automatically -> prod with
  approval, **promoting the same image** (build once, deploy many).

## 5. What I'd do next (2 min). Shows judgement.
Private networking, Front Door/WAF or APIM, Entra ID instead of self-issued
JWTs, KEDA scaling on queue depth, alerts and SLOs, contract tests on events.
(See the hardening roadmap in `docs/architecture.md`.)

## Likely questions and crisp answers

| Question | Answer |
|---|---|
| Why not one monolith? | For a team this size a modular monolith is often right. Microservices earn their cost when teams need to deploy independently and scale parts differently. This project shows the patterns you need *if* you split. |
| How do you avoid a distributed transaction? | Local transaction + outbox + events. Each service is consistent on its own; the system becomes eventually consistent. Compensating actions (a saga) handle multi-step flows. |
| What if Service Bus is down? | Orders still succeed; events wait in the outbox and the relay catches up when the bus is back. The relay logs `outbox_publish_failed`, and `attempts`/`last_error` on the outbox rows show the backlog (alert on unpublished-row age). |
| What if a message keeps failing? | Retries with backoff, then the dead-letter queue, plus an alert on DLQ depth. Fix it and replay. |
| How do you trace a request? | Correlation ID at the edge, propagated over HTTP and inside the event envelope, plus OpenTelemetry trace context in App Insights. |
| How do you roll back? | Container Apps revisions: shift traffic back to the previous revision. Migrations are expand/contract, so the old code still works. |
| How would you onboard a new team/service? | Start from the shared platform lib + Dockerfile + Bicep module. A new service is mostly business code, and the paved road gives it logging, auth, health and deployment for free. |
