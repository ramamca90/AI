# 0003: No NAT gateway for the demo

Status: accepted

## Context

Fargate tasks need outbound internet access for ECR, Secrets Manager, SQS, CloudWatch and the
Anthropic API. The usual design puts tasks in private subnets behind a NAT gateway. One NAT gateway
costs about $32 a month plus data charges, and two (one per AZ, for resilience) cost about $65. The
whole demo stack costs about $70, so NAT would nearly double it for a project that runs for hours.

## Decision

No NAT gateway. Fargate tasks run in public subnets with public IPs. Security groups allow inbound
traffic to the API only from the ALB, and allow no inbound traffic to the worker. RDS stays in
private subnets with no route to the internet and `publicly_accessible = false`.

## Consequences

- Saves about $32 to $65 a month.
- The tasks can't be reached from the internet, as long as the security groups stay correct. But that
  is now the only layer. One wrong rule exposes a task directly, where a private subnet would have
  given a second layer of protection.
- Each task has a public IPv4 address, at about $3.65 a month. This is cheaper than NAT, but not free.
- Outbound traffic has no fixed source IP, so a third party can't allowlist us.
- Tasks can reach the whole internet. Without a central egress point, it is hard to restrict that.

## Production alternative

Put tasks in private subnets, and choose one of these:

- **NAT gateways**, one per AZ. This is the simplest option and gives a fixed outbound IP.
- **VPC endpoints** for ECR (`api` and `dkr`), S3, Secrets Manager, SQS and CloudWatch Logs. Traffic to
  AWS stays private, but each interface endpoint costs about $7 a month per AZ, and the Anthropic API
  still needs an outbound route.

In this module that means adding the routes or endpoints, moving the services to
`aws_subnet.private`, and setting `assign_public_ip = false`.

## When we'd revisit

As soon as this holds real data, stays up for more than a demo, needs a fixed outbound IP, or has to
pass a security review.
