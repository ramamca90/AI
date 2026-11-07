# 0002: Manual agent loop with an LLM port

Status: accepted

## Context

An agent framework would give us a loop for free, but it would also hide the things this project
cares about most: exact message history, prompt caching, cost tracking and iteration limits. We also
need to test the harness often without paying for model calls.

## Decision

We own the agent loop. It talks to an `LLMClient` port defined in `domain`, which has two
implementations: Claude, and a deterministic scripted client.

## Consequences

- The same loop runs in production and in offline tests, evals and the no-key demo
  (`LLM_PROVIDER=scripted`).
- We control the rules that are easy to break, such as appending response content unchanged and
  keeping per-request data out of system prompts.
- Budget and iteration caps sit in one place that we can read.
- We maintain the loop ourselves, and new API features need our own support.
- The port has to stay small, or it turns into a framework of our own.

## When we'd revisit

If the loop grows to reimplement what a maintained SDK gives us, such as compaction or streaming tool
execution, or if we need several providers with features the port can't express cleanly.
