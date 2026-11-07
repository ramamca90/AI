# 0004: BM25 runbook retrieval before embeddings

Status: accepted

## Context

Agents need to find relevant runbooks. The usual answer is embeddings and a vector store, which adds
an embedding provider, an index to keep up to date, more infrastructure, and more cost. Our corpus is
small, and runbooks are full of exact terms that matter, such as service names, error codes and metric
names.

## Decision

Use BM25 keyword retrieval (`rank-bm25`) behind the `Retriever` port. The index is built in process,
and there is no extra infrastructure.

## Consequences

- There is nothing to deploy or pay for, and results are deterministic, which suits offline tests.
- Exact terms match well, and scores are easy to explain.
- It misses matches that use different words. A query about "latency" won't find a runbook that only says
  "slow responses".
- The index is in memory, which is fine for a small corpus and would not suit a large one.

## When we'd revisit

If retrieval evals show that relevant runbooks are being missed because of vocabulary differences, or if
the corpus grows past what fits comfortably in memory. Because of the port, embeddings or a hybrid
search can replace BM25 without changing the agents.
