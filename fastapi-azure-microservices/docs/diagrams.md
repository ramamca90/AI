# OrderFlow process diagrams

Eleven diagrams covering the whole system: how a request travels, how events stay reliable,
what happens inside each service, and how code reaches Azure. Every number on them
(intervals, retry counts, status codes) comes from the code in this folder.
GitHub renders the Mermaid blocks below as diagrams.

- **Runtime:** [System architecture](#architecture) · [Placing an order, end to end](#place-order) · [Sign-up, login and token checks](#auth)
- **Reliability:** [Idempotency-Key: no double orders](#idempotency) · [Outbox relay loop](#outbox) · [Handling an incoming event](#consumer)
- **Inside a service:** [A request inside one service](#pipeline) · [Container start, health and shutdown](#lifecycle)
- **Delivery:** [CI: what runs on every change](#ci) · [CD: dev, then prod](#cd) · [Azure resources and permissions](#azure)

## Runtime

<a id="architecture"></a>

### System architecture

Who talks to whom. Only the gateway is reachable from outside; every service owns its own database and services never call each other.

```mermaid
flowchart LR
  client(["Client or demo script"]) -->|"HTTP :8080"| gw["gateway<br/>nginx, rate limits, correlation ID"]
  subgraph private["Private network: compose network or Container Apps environment"]
    gw -->|"/v1/auth, /v1/users"| ids["identity-service"]
    gw -->|"/v1/orders"| ord["orders-service"]
    gw -->|"/v1/notifications"| ntf["notification-service"]
    ids -->|"publishes user.registered"| bus[("Event bus<br/>topic: domain-events")]
    ord -->|"outbox relay publishes<br/>order.created, order.cancelled"| bus
    bus -->|"subscription: notification-service"| ntf
  end
  ids --- db1[("identity DB<br/>users")]
  ord --- db2[("orders DB<br/>orders, order_items, outbox")]
  ntf --- db3[("notifications DB<br/>notifications")]
```

Synchronous HTTP goes through the gateway. Everything between services travels as events on the bus. Locally the bus is Redis Streams; on Azure it is a Service Bus topic.

> **In the interview:** Database per service keeps teams independent. The price is no cross-service joins, which is why the services share facts through events instead.

<a id="place-order"></a>

### Placing an order, end to end

The full journey the demo script exercises: the HTTP request returns as soon as the order is saved, and the notification follows asynchronously.

```mermaid
sequenceDiagram
  autonumber
  actor C as Client
  participant G as gateway
  participant O as orders-service
  participant ODB as orders DB
  participant R as outbox relay
  participant B as event bus
  participant N as notification-service
  participant NDB as notifications DB
  C->>G: POST /v1/orders, Bearer token, Idempotency-Key
  G->>O: forward with X-Correlation-ID
  O->>O: verify JWT locally, compute total
  O->>ODB: one transaction: order + items + outbox row
  O-->>G: 201 Created
  G-->>C: 201 Created
  loop every 1 second
    R->>ODB: select unpublished rows, FOR UPDATE SKIP LOCKED
    R->>B: publish orders.order.created
    R->>ODB: set published_at
  end
  B->>N: deliver event, correlation ID restored
  N->>NDB: insert notification, event_id is unique
  N->>B: ack
  C->>G: GET /v1/notifications
  G->>N: forward
  N-->>C: 200 with "Order received"
```

Step 4 is the key: the order and its event are written in one transaction. The client already has its 201 before the event leaves the service.

> **In the interview:** orders-service never calls notification-service. If notifications are down, checkout still works and the notification arrives when it recovers.

<a id="auth"></a>

### Sign-up, login and token checks

identity-service is the only service that knows passwords. It signs a short-lived JWT, and every other service checks that token on its own.

```mermaid
sequenceDiagram
  actor C as Client
  participant I as identity-service
  participant IDB as identity DB
  participant O as orders-service
  C->>I: POST /v1/auth/register with email, name, password
  I->>I: Argon2id hash in a worker thread
  I->>IDB: insert user, email unique
  I-->>C: 201 user, never the hash
  C->>I: POST /v1/auth/token with email, password
  I->>IDB: find user by email
  I->>I: verify hash, dummy hash if no such user
  I-->>C: 200 JWT with iss, aud, roles, 30 min expiry
  C->>O: any /v1/orders call with Bearer JWT
  O->>O: check signature, issuer, audience, expiry
  alt token valid
    O-->>C: 200, only this user's data
  else missing, expired or tampered
    O-->>C: 401 problem+json
  end
```

Verification is local: no service calls identity-service per request. Unknown emails are checked against a dummy hash so response time does not reveal who has an account.

> **In the interview:** Next step for real production: asymmetric keys (RS256 + JWKS) or Microsoft Entra ID, so only the issuer can sign tokens. The check lives in one module, so that swap is small.

## Reliability

<a id="idempotency"></a>

### Idempotency-Key: no double orders

What orders-service does with each POST. A client that times out and retries gets the original order back instead of a second one.

```mermaid
flowchart TD
  A["POST /v1/orders"] --> B{"Idempotency-Key<br/>header sent?"}
  B -->|no| E["Create order + outbox row<br/>in one transaction"]
  B -->|yes| C{"Order with this key<br/>for this customer?"}
  C -->|yes| D["Return existing order<br/>200 OK"]
  C -->|no| E
  E --> F{"Commit succeeds?"}
  F -->|yes| G["Return new order<br/>201 Created"]
  F -->|"unique constraint hit<br/>by a concurrent request"| H["Roll back, load the<br/>winning request's order"]
  H --> D
```

The unique constraint on customer and key settles the race when two identical requests arrive at the same moment: the loser rolls back and returns the winner's order.

> **In the interview:** In the demo, the retried request returns 200 with the same order id. That is this diagram's left branch.

<a id="outbox"></a>

### Outbox relay loop

The background task inside orders-service that moves saved events to the bus. It is why an order and its event can never get out of step.

```mermaid
flowchart TD
  S(["Starts with the service"]) --> Q["Select up to 50 unpublished rows<br/>oldest first, FOR UPDATE SKIP LOCKED"]
  Q --> L{"Another row<br/>in the batch?"}
  L -->|"no"| CM["Commit"]
  L -->|"yes"| P["Publish event to bus<br/>message_id = event id"]
  P -->|"ok"| M["Set published_at"]
  M --> L
  P -->|"bus error"| X["attempts + 1, save last_error<br/>stop the batch to keep order"]
  X --> CM
  CM --> W{"Was the batch full?"}
  W -->|"yes, more waiting"| Q
  W -->|"no"| SL["Sleep 1 second"]
  SL --> Q
```

SKIP LOCKED lets every replica run this loop without sending the same row twice. On a bus error the row stays unpublished and is retried on the next tick, in order.

> **In the interview:** This solves the dual-write problem: saving to the database and publishing to a broker can't be made atomic, so the event is saved with the order and sent afterwards.

<a id="consumer"></a>

### Handling an incoming event

What notification-service does with each delivered event. Delivery is at-least-once, so the same event can arrive twice and must be harmless.

```mermaid
flowchart TD
  R["Event delivered"] --> V{"Valid event<br/>envelope?"}
  V -->|"no"| DLQ[("Dead-letter queue<br/>Redis: domain-events.dlq<br/>Service Bus: subscription DLQ")]
  V -->|"yes"| T{"Event type this<br/>service handles?"}
  T -->|"no"| ACK["Ack and ignore"]
  T -->|"yes"| DU{"event_id already<br/>stored?"}
  DU -->|"yes, duplicate"| ACK
  DU -->|"no"| H["Insert notification<br/>send through channel"]
  H -->|"ok"| ACK
  H -->|"error"| RT{"Attempts left?<br/>Redis 3 tries, Service Bus 10"}
  RT -->|"yes, back off"| R
  RT -->|"no"| DLQ
```

Dedupe happens on the stored event_id. Failures are retried, then parked in a dead-letter queue for an operator instead of blocking everything behind them.

> **In the interview:** Two safety nets against duplicates: Service Bus duplicate detection on message_id, and a unique event_id column in the consumer's own table.

## Inside a service

<a id="pipeline"></a>

### A request inside one service

Every service is built by the same app factory, so this path is identical in all three. Only the service layer is business code.

```mermaid
flowchart LR
  IN["HTTP request"] --> MW["RequestContext middleware<br/>accept or mint X-Correlation-ID"]
  MW --> RT["Router and<br/>Pydantic validation"]
  RT -->|"invalid body"| E422["422 problem+json"]
  RT --> AU["Auth dependency<br/>verify JWT"]
  AU -->|"bad or missing token"| E401["401 problem+json"]
  AU --> SV["Service layer<br/>business rules, commit"]
  SV -->|"not found or conflict"| EX["404 or 409<br/>problem+json"]
  SV --> OK["2xx JSON"]
  OK & E422 & E401 & EX --> OUT["Back through middleware:<br/>correlation + security headers,<br/>access log line"]
```

Whatever happens, the response leaves through the middleware, which adds the correlation ID and security headers and writes one access-log line.

> **In the interview:** Consistency across services is what makes a fleet operable: same error shape, same logs, same probes, without each team rebuilding them.

<a id="lifecycle"></a>

### Container start, health and shutdown

What happens from container start to shutdown, and how the platform's probes decide whether to restart a container or just stop sending it traffic.

```mermaid
flowchart TD
  ST["Container starts"] --> MG{"RUN_MIGRATIONS<br/>= true?"}
  MG -->|"yes"| LK["Take Postgres advisory lock"]
  LK --> AL["alembic upgrade head"]
  AL --> UV["uvicorn starts the app"]
  MG -->|"no"| UV
  UV --> LS["Lifespan: DB pool, event bus,<br/>outbox relay or consumer task"]
  LS --> PR{"Platform probes"}
  PR -->|"/health/live fails"| RS["Restart the container"]
  PR -->|"/health/ready fails<br/>DB or bus unreachable"| NT["Stop routing traffic to it"]
  PR -->|"both pass"| SV["Serving traffic"]
  SV -->|"SIGTERM on deploy or scale-in"| GS["Graceful shutdown: cancel tasks,<br/>close bus, close DB pool, 20 s limit"]
```

The advisory lock means several replicas can start at once and only one runs migrations. Readiness covers dependencies; liveness only covers the process itself.

> **In the interview:** Separating liveness from readiness avoids restart loops: losing the database takes a replica out of rotation instead of killing it repeatedly.

## Delivery

<a id="ci"></a>

### CI: what runs on every change

The checks GitHub Actions runs for any push or pull request that touches the project folder.

```mermaid
flowchart LR
  P(["Push or PR touching<br/>fastapi-azure-microservices/"]) --> L["lint<br/>ruff check + format"]
  P --> T["test x4 packages<br/>pytest + real Redis"]
  P --> GI["gateway-image<br/>build + nginx -t"]
  P --> BI["bicep<br/>build + lint"]
  L --> IM["images x3<br/>docker build"]
  T --> IM
  IM --> TV["Trivy scan<br/>fail on fixable HIGH or CRITICAL"]
```

Image builds wait for lint and tests. Each image is scanned with Trivy and the job fails on any HIGH or CRITICAL vulnerability that already has a fix.

> **In the interview:** Tests include a real Redis, because the two event-bus bugs found while testing this project only showed up against the real thing.

<a id="cd"></a>

### CD: dev, then prod

The manually triggered deployment. Dev builds the images; prod reuses exactly those images after a reviewer approves.

```mermaid
flowchart TD
  M(["Run workflow manually"]) --> D1
  subgraph dev["dev environment"]
    D1["Bicep: platform only<br/>deployApps = false"] --> D2["az acr build<br/>4 images, tag = git SHA"]
    D2 --> D3["Bicep: deploy Container Apps"]
    D3 --> D4["Smoke test /healthz"]
  end
  D4 --> AP{"Reviewer approves prod?"}
  AP -->|"no"| STOP(["Stops at dev"])
  AP -->|"yes"| P1
  subgraph prod["prod environment"]
    P1["Bicep: platform only"] --> P2["az acr import<br/>same images from dev registry"]
    P2 --> P3["Bicep: deploy Container Apps"]
    P3 --> P4["Smoke test /healthz"]
  end
```

Each environment first deploys the platform without apps, so the registry exists before any image is pushed. Authentication uses GitHub OIDC, so no Azure credentials are stored in GitHub.

> **In the interview:** Build once, deploy many: prod runs the exact image that passed in dev, not a rebuild that could differ.

<a id="azure"></a>

### Azure resources and permissions

What Bicep creates, and exactly what each app is allowed to touch. Every app has its own managed identity, so there are no passwords or keys in configuration.

```mermaid
flowchart LR
  subgraph apps["Container Apps, each with its own managed identity"]
    gw["gateway<br/>external HTTPS"]
    ids["identity-service"]
    ord["orders-service"]
    ntf["notification-service"]
  end
  acr[("Container Registry")]
  kv[("Key Vault<br/>JWT secret, DB URLs,<br/>App Insights string")]
  sb[("Service Bus topic<br/>key auth disabled")]
  pg[("PostgreSQL<br/>3 databases")]
  ai[("Application Insights<br/>+ Log Analytics")]
  gw & ids & ord & ntf -->|"AcrPull"| acr
  ids & ord & ntf -->|"Secrets User"| kv
  ids & ord -->|"Data Sender"| sb
  sb -->|"Data Receiver"| ntf
  ids & ord & ntf -->|"SSL connection"| pg
  ids & ord & ntf -.->|"traces, logs, metrics"| ai
```

Only identity and orders may send events; only notifications may receive them. Service Bus has key-based auth switched off, so the managed identities are the only way in.

> **In the interview:** Least privilege per service: a compromised notification-service can't publish fake order events, because it simply has no send permission.

---

Design decisions behind these flows: [architecture.md](architecture.md). Demo script: [interview-walkthrough.md](interview-walkthrough.md).
