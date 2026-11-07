# Deployment

This takes Incident Copilot from an empty AWS account to a live URL on ECS Fargate, and back to
nothing after the demo. It is one environment, built for low cost. The trade-offs are recorded in
`docs/adr/`.

Run the `scripts/` commands from the repository root. On Windows, use Git Bash and prefix them
with `bash`, for example `bash scripts/bootstrap.sh`.

## Run it locally first

No keys and no AWS needed:

```bash
docker compose up --build
curl http://localhost:8000/readyz
```

This starts Postgres, ElasticMQ (a local SQS), a one-shot migration, the API and the worker, with
`LLM_PROVIDER=scripted`.

## Prerequisites

- An AWS account you can administer, with credentials configured (`aws sts get-caller-identity`
  works). The stack creates IAM roles, so a limited user won't do.
- Terraform 1.10 or later, AWS CLI v2, Docker with the daemon running, `jq`, `curl`.
- The code in a GitHub repository, if you want the deploy workflow.
- Optional: an ACM certificate in the same region and a domain, for HTTPS.
- Optional: an Anthropic API key. The default `scripted` provider doesn't need one.

## How a deployment is ordered

ECS can't start a task whose secret is empty, and the app needs its tables before it can pass
`/readyz`. So the first deployment has a fixed order, and the services are created last:

1. `bootstrap.sh` creates everything except the ECS services.
2. `set-secrets.sh` fills the secrets.
3. `deploy.sh` pushes the image, runs the migration, and only then creates the services.

## From zero to a live URL

**1. Configure.**

```bash
cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
```

Set `github_repo` to your `owner/name`, and set `alarm_email` if you want alerts. For live agents,
set `llm_provider = "anthropic"`. If the account already has a GitHub OIDC provider, set
`create_github_oidc_provider = false`.

**2. Create the foundation.** Review the plan and answer `yes`. RDS takes about 10 minutes.

```bash
scripts/bootstrap.sh
```

Commit `infra/terraform/.terraform.lock.hcl` afterwards, so that provider versions stay fixed.

**3. Set the secrets.** Each command prompts without echoing the value. Keep the API key somewhere
safe, because you will need it to call the API.

```bash
openssl rand -hex 32               # generates a value to paste at the next prompt
scripts/set-secrets.sh api-key
scripts/set-secrets.sh anthropic   # only with llm_provider = "anthropic"
```

Commit your code first: the image is tagged with the git SHA. Uncommitted changes get a `-dirty`
tag.

**4. Deploy.** This builds and pushes the image, runs the migration, asks you to approve a
Terraform plan that adds the services, waits for them, and tests `/readyz`.

```bash
scripts/deploy.sh
```

**5. Get the URL.**

```bash
terraform -chdir=infra/terraform output -raw base_url
```

**6. Optional: turn on GitHub deploys.** Add each entry of this output as a repository variable
(Settings, Secrets and variables, Actions, Variables). None of them is a secret.

```bash
terraform -chdir=infra/terraform output -json github_actions_variables
```

After that, Actions, Deploy, Run workflow on `main` does a full deploy. It never runs on its own.
It can't run on another branch, because the IAM role trusts only `main`.

## Verify it

```bash
BASE_URL="$(terraform -chdir=infra/terraform output -raw base_url)"
curl -i "$BASE_URL/healthz"    # 200: the process is up
curl -i "$BASE_URL/readyz"     # 200: the database is reachable
```

Then check these:

- **Tasks:** ECS console, cluster `incident-copilot-demo`. Each service should show one running task.
- **Logs:** `aws logs tail /ecs/incident-copilot-demo/api --follow`, and the same for `worker`.
  Migrations are in `/ecs/incident-copilot-demo/migrate`.
- **Target health:** EC2 console, Target Groups. The target should be healthy.
- **Queue:** the dead-letter queue should be empty, and a message there sets off an alarm.
- **End to end:** send a test alert to the API with your `X-API-Key` header, then watch the worker log
  and the incident's status reach `awaiting_approval`.

**About plain HTTP:** without `acm_certificate_arn`, the `X-API-Key` header crosses the internet
unencrypted and anyone on the path can read it. For a short demo, use a throwaway key and set
`allowed_ingress_cidrs` to your own IP. Otherwise set `acm_certificate_arn` and `public_hostname`,
point a DNS record at the ALB, and apply. HTTP then redirects to HTTPS.

## Later deploys

Run `scripts/deploy.sh` or the GitHub workflow. The steps always run in this order:

1. **Push** the image, tagged with the git SHA. Tags are immutable.
2. **Migrate.** A failed migration stops the deploy before any service changes.
3. **Roll out** the API, then the worker. If the circuit breaker rolls one back, the deploy fails.
4. **Smoke test** `/readyz`.

The migration runs while the old version is still serving, so migrations must work with the old
code: add first, remove in a later release. The rollback restores old code, not the old schema.

After changing a secret, restart the services, since tasks read secrets at start:

```bash
aws ecs update-service --cluster incident-copilot-demo --service incident-copilot-demo-api --force-new-deployment
aws ecs update-service --cluster incident-copilot-demo --service incident-copilot-demo-worker --force-new-deployment
```

Changes to environment variables in Terraform reach the services on the next deploy, not on
`terraform apply`, because deploys own the running task definition.

## Monthly cost estimate

This is an **estimate** for us-east-1 with the default sizes, one API task and one worker running
all month, and light traffic. Prices change, so **verify it in the
[AWS Pricing Calculator](https://calculator.aws/)**. Free-tier credits are not counted.

| Item | Basis | USD per month |
|---|---|---|
| Application Load Balancer | $0.0225/hour plus light LCU usage | 18 |
| Fargate, API | 0.25 vCPU, 0.5 GB | 9 |
| Fargate, worker | 0.25 vCPU, 1 GB | 11 |
| Public IPv4 addresses | 4 (2 ALB, 2 tasks) at $0.005/hour | 15 |
| RDS db.t4g.micro | $0.016/hour, single AZ | 12 |
| RDS storage | 20 GB gp3 | 2 |
| Secrets Manager | 3 secrets at $0.40 | 1 |
| CloudWatch | Light logs, about 8 alarms | 2 |
| ECR | Under 5 GB of images | under 1 |
| SQS, SNS, Budgets | Within the free allowances | 0 |
| Data transfer | Light | 1 |
| **Total** | | **about 70** |

That is about $2.30 a day, or $0.10 an hour. Scaling out adds about $0.45 a day for each extra
task, including its public IP. The Anthropic API is billed separately, and each incident is capped by
`incident_budget_usd`. With `scripted`, it is zero.

The budget in `monthly_budget_usd` alerts at 80% of actual spend and 100% of forecast. It covers
the whole account, and it warns but doesn't stop anything.

## Tear down right after the demo

```bash
scripts/teardown.sh
```

Type the stack name when asked. With the default settings, this **permanently deletes the database, the
images and the secrets**. It takes about 15 minutes. If you set `deletion_protection = true`,
set it back to false and apply first.

Then check:

- **Billing:** look at Cost Explorer a day or two later. Costs lag, so a charge for the demo days
  is expected.
- **Final snapshot:** if you set `skip_final_snapshot = false`, a snapshot stays and costs money
  until you delete it.
- **Leftovers:** inactive task definition revisions may remain. They cost nothing.
- **GitHub variables:** they are harmless, but they point at a stack that no longer exists.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Task stops with `ResourceInitializationError` | A secret has no value | Run `scripts/set-secrets.sh`, then redeploy |
| Migration fails | Read the log group for `migrate` | Fix it and redeploy. Services were not changed |
| `/readyz` returns 503 from the ALB | No healthy target | Check the API log and the target group |
| Deploy says the service was rolled back | New tasks failed health checks | Read the service events and the API log |
| GitHub deploy fails at the credentials step | Wrong branch, or `github_repo` mismatch | Run on `main` and check the role trust |
| `EntityAlreadyExists` for the OIDC provider | The account already has one | Set `create_github_oidc_provider = false` |
| A worker stops mid-job on scale-in or deploy | Normal, if rare | SQS redelivers after the visibility timeout |

Terraform state is stored locally and contains the database password. Keep it off shared drives
and out of git. To move it to S3, use the commented backend in `infra/terraform/versions.tf`.
