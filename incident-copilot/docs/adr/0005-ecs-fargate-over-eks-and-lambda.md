# 0005: ECS Fargate over EKS and Lambda

Status: accepted

## Context

We run an API and a queue worker from one image. Agent jobs can run for minutes, because each one makes
several LLM calls across parallel investigators. The API also streams events to the UI over SSE. One
person operates this, and it has to be cheap and easy to explain.

## Decision

Run both processes on ECS Fargate.

- **Lambda** has a 15-minute limit, which is uncomfortably close to our longest job, and a job that hits
  it is killed without warning. Holding SSE connections open also fits it poorly, and the API and worker
  would need different packaging.
- **EKS** charges about $73 a month for the control plane alone, about the same as this entire stack.
  It also brings Kubernetes upgrades and add-ons to run, which one small service doesn't need.

## Consequences

- Long jobs and SSE work without special handling, and one image serves both processes.
- There are no servers to patch and no cluster to upgrade.
- Terraform stays modest, with autoscaling and rollback available as built-in features.
- Fargate bills for idle time. A task runs even when the queue is empty, where Lambda would scale to zero.
- Stopping a task allows at most 120 seconds for a clean exit, which is shorter than a long job. An
  interrupted job is redelivered by SQS, and handlers use compare-and-set on status, so this is safe, but
  it does waste the work done so far.
- It ties us to AWS, though the image itself is portable.

## When we'd revisit

For EKS: if there are many services or a team that already runs Kubernetes. For Lambda or scale to zero:
if jobs turn out to be short and traffic is rare enough for idle cost to matter.
