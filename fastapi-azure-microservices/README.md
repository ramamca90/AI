# OrderFlow: production-grade FastAPI microservices on Azure

Three FastAPI services behind an nginx gateway, communicating through events,
packaged as hardened containers and deployed to **Azure Container Apps**
with **Bicep** and **GitHub Actions**.

```
                  ┌──────────── Azure Container Apps environment ─────────────┐
 client ─HTTPS─▶  │ gateway ─┬─▶ identity-service ──┐                         │
                  │          ├─▶ orders-service ────┼─(outbox)─▶ Service Bus  │
                  │          └─▶ notification-svc ◀─┴──── topic/subscription  │
                  └───────────────────────────────────────────────────────────┘
       PostgreSQL (DB per service) · Key Vault · ACR · App Insights / Log Analytics
```

| | What it shows |
|---|---|
| **Reliability** | Transactional outbox, at-least-once delivery, idempotent consumers, dead-letter queues, `Idempotency-Key` on order creation |
| **Security** | Argon2id passwords, short-lived JWTs, per-service managed identities, Key Vault secret references, Service Bus SAS disabled, non-root images, OIDC CI (no stored cloud creds) |
| **Observability** | JSON logs, correlation IDs across HTTP *and* events, OpenTelemetry → Application Insights, liveness/readiness probes |
| **Operability** | 12-factor config with validation, RFC 7807 errors, graceful shutdown, migrations with advisory lock, autoscaling |
| **Delivery** | Lint + tests + CVE scan on PRs; main → dev → prod (approval) promoting the *same* image |

Read **[docs/architecture.md](docs/architecture.md)** for design decisions and trade-offs,
and **[docs/interview-walkthrough.md](docs/interview-walkthrough.md)** for a 15-minute demo script.

## Repository layout

```
libs/common/                 orderflow_common: the shared "paved road" platform library
  app_factory.py             builds a FastAPI app with all cross-cutting concerns
  config.py  logging.py  telemetry.py  middleware.py  errors.py  health.py
  security.py  db.py  migrations.py
  events/                    Event envelope, contracts, Redis Streams + Azure Service Bus transports
services/
  identity-service/          register, login (JWT), /users/me
  orders-service/            order lifecycle + transactional outbox relay
  notification-service/      event consumer + notifications API
  */migrations/              Alembic migrations (one DB per service)
gateway/                     nginx edge: routing, rate limits, correlation IDs, JSON access logs
docker/                      shared hardened Dockerfile, entrypoint, Postgres init
infra/                       Bicep: main.bicep + modules/ + parameters/
scripts/demo.ps1             end-to-end demo through the gateway
```

## Run locally

Prerequisites: Docker Desktop, plus [uv](https://docs.astral.sh/uv/) if you want to run the tests.

```powershell
docker compose up --build
```

| URL | What |
|---|---|
| http://localhost:8080 | Gateway (the public entry point) |
| http://localhost:8001/docs | identity-service Swagger UI |
| http://localhost:8002/docs | orders-service Swagger UI |
| http://localhost:8003/docs | notification-service Swagger UI |

Run the end-to-end scenario (register → login → idempotent order → async notification → cancel):

```powershell
./scripts/demo.ps1
```

Locally, Redis Streams stands in for Azure Service Bus (same consumer-group
semantics). Switching transports is the `EVENT_BUS_BACKEND` setting; the code doesn't change.

## Tests & lint

```powershell
uv sync --all-packages
```

```powershell
uv run pytest libs/common/tests; uv run pytest services/identity-service/tests; uv run pytest services/orders-service/tests; uv run pytest services/notification-service/tests
```

```powershell
uv run ruff check .; uv run ruff format --check .
```

Tests use SQLite + an in-memory bus, so they need no Docker and finish in seconds.

## Deploy to Azure

### One-time setup
1. Create a resource group per environment:
   `az group create -n rg-orderflow-dev -l westeurope`
2. Create an Entra ID app registration with a **federated credential** for
   this GitHub repo (environment `dev`, and `prod`), and grant it **Owner**
   (or Contributor + User Access Administrator) on the resource group. Role
   assignments for the managed identities are created by Bicep.
3. In GitHub → *Settings → Environments*, create `dev` and `prod` (add required reviewers on `prod`) with:
   * variables: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`
   * secrets: `POSTGRES_ADMIN_PASSWORD`, `JWT_SECRET` (≥ 32 chars)
4. For prod image promotion, give the prod identity `AcrPull` on the dev registry.

### Pipeline
Workflows live at the repo root (GitHub only runs workflows from there):

| Workflow | Trigger | What it does |
|---|---|---|
| [`fastapi-azure-microservices-ci.yml`](../.github/workflows/fastapi-azure-microservices-ci.yml) | PRs and pushes touching this folder | lint, tests (with a real Redis), image build + Trivy scan, Bicep lint |
| [`fastapi-azure-microservices-cd.yml`](../.github/workflows/fastapi-azure-microservices-cd.yml) | manual (*Actions -> Run workflow*) | provisions the platform, builds images *inside ACR* (`az acr build`), deploys the Container Apps, smoke-tests `/healthz`; prod waits for approval, then imports the exact dev-tested images |
| [`fastapi-azure-microservices-deploy.yml`](../.github/workflows/fastapi-azure-microservices-deploy.yml) | called by CD | reusable per-environment deployment |

CD is manual-only so commits don't trigger Azure deploys before the environments
are configured. To deploy on every merge, add a `push` trigger with a path filter on this folder.

### Manual deploy (from your machine)

```powershell
$env:POSTGRES_ADMIN_PASSWORD = "<strong password>"; $env:JWT_SECRET = "<32+ random chars>"
```

```powershell
$env:DEPLOY_APPS = "false"; az deployment group create -g rg-orderflow-dev -f infra/main.bicep -p infra/parameters/dev.bicepparam
```

```powershell
$acr = az deployment group show -g rg-orderflow-dev -n main --query properties.outputs.registryName.value -o tsv; $env:IMAGE_TAG = "v1"
az acr build -r $acr -t identity-service:v1 -f docker/python-service.Dockerfile --build-arg SERVICE=identity-service --build-arg SERVICE_MODULE=identity_service .
az acr build -r $acr -t orders-service:v1 -f docker/python-service.Dockerfile --build-arg SERVICE=orders-service --build-arg SERVICE_MODULE=orders_service .
az acr build -r $acr -t notification-service:v1 -f docker/python-service.Dockerfile --build-arg SERVICE=notification-service --build-arg SERVICE_MODULE=notification_service .
az acr build -r $acr -t gateway:v1 gateway
```

```powershell
$env:DEPLOY_APPS = "true"; az deployment group create -g rg-orderflow-dev -f infra/main.bicep -p infra/parameters/dev.bicepparam --query properties.outputs.gatewayUrl.value
```

Then run `./scripts/demo.ps1 -BaseUrl <gatewayUrl>`.

> **Cost note:** dev uses Burstable PostgreSQL, Basic ACR, Standard Service Bus and
> consumption Container Apps (roughly the price of a small VM per month). Delete the resource group when you're done:
> `az group delete -n rg-orderflow-dev`.

## API overview

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/v1/auth/register` | - | 201, publishes `identity.user.registered` |
| POST | `/v1/auth/token` | - | returns JWT (`Bearer`) |
| GET | `/v1/users/me` | JWT | |
| POST | `/v1/orders` | JWT | optional `Idempotency-Key`; 201 new / 200 replay |
| GET | `/v1/orders?status=&limit=&offset=` | JWT | paginated, own orders only |
| GET | `/v1/orders/{id}` | JWT | 404 for other customers' orders (admin sees all) |
| POST | `/v1/orders/{id}/cancel` | JWT | 409 if already cancelled |
| GET | `/v1/notifications?unread_only=` | JWT | |
| POST | `/v1/notifications/{id}/read` | JWT | |
| GET | `/health/live`, `/health/ready` | - | every service |

Errors are always `application/problem+json`:

```json
{ "type": "urn:orderflow:error:conflict", "title": "Conflict", "status": 409,
  "detail": "Order is already cancelled", "instance": "/v1/orders/…/cancel",
  "correlation_id": "4f0c…" }
```
