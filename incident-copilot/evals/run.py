"""Run the eval suite.

    uv run python -m evals.run           Scripted, free. Tests the harness, not the model.
    uv run python -m evals.run --live    Real Claude. Spends API credit; needs a key.

Only `--live` results say anything about diagnosis quality or injection resistance.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from copilot.agents.runtime import build_runtime
from copilot.config import Settings
from copilot.domain.models import AgentEvent, Incident
from copilot.rag.bm25 import BM25Retriever
from copilot.tools.fixtures import list_scenarios, load_scenario
from evals.scoring import Check, score

RESULTS_DIR = Path(__file__).parent / "results"

# Query -> the runbook that should answer it. Worded unlike the runbook titles on purpose.
RETRIEVAL_CASES = {
    "new release causing errors, how do we go back to the previous version": "deploy-rollback",
    "threads waiting for a free database connection, HikariPool timeouts": (
        "db-connection-pool-exhaustion"
    ),
    "pods OOMKilled and heap keeps growing after restart": "memory-leak-oom",
    "upstream dependency slow, requests hitting gateway timeout": "downstream-timeouts",
    "volume at 100 percent, no space left on device": "disk-full",
    "TLS handshake failures because the certificate is no longer valid": "certificate-expiry",
}


def retrieval_metrics(k: int = 3) -> dict[str, float]:
    retriever = BM25Retriever()
    hits_at_k = 0
    reciprocal_ranks = 0.0
    for query, runbook in RETRIEVAL_CASES.items():
        refs = [hit.ref for hit in retriever.search(query, k=k)]
        rank = next((i for i, ref in enumerate(refs, 1) if f":{runbook}.md" in ref), None)
        if rank is not None:
            hits_at_k += 1
            reciprocal_ranks += 1 / rank
    total = len(RETRIEVAL_CASES)
    return {f"recall_at_{k}": hits_at_k / total, "mrr": reciprocal_ranks / total}


async def run_scenario(settings: Settings, name: str) -> tuple[list[Check], float]:
    scenario = load_scenario(name)
    runtime = build_runtime(settings, name)
    events: list[AgentEvent] = []

    async def collect(event: AgentEvent) -> None:
        events.append(event)

    result = await runtime.orchestrator.investigate(Incident(alert=scenario.alert), collect)
    return score(scenario.expected, result, events), result.usage.cost_usd


async def run_all(settings: Settings) -> dict[str, list[Check]]:
    results: dict[str, list[Check]] = {}
    for name in list_scenarios():
        checks, cost = await run_scenario(settings, name)
        results[name] = checks
        print(f"\n{name} (${cost:.4f})")
        for check in checks:
            print(f"  {'PASS' if check.passed else 'FAIL'}  {check.name}: {check.detail}")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="call real Claude; spends API credit")
    args = parser.parse_args()

    if args.live:
        settings = Settings(llm_provider="anthropic")
        if settings.anthropic_api_key is None:
            print("--live needs ANTHROPIC_API_KEY.", file=sys.stderr)
            return 2
    else:
        settings = Settings(llm_provider="scripted")

    print(f"Mode: {'LIVE' if args.live else 'SCRIPTED (harness only, not model quality)'}")
    results = asyncio.run(run_all(settings))
    retrieval = retrieval_metrics()
    print(f"\nretrieval: {retrieval}")

    all_checks = [check for checks in results.values() for check in checks]
    passed = sum(check.passed for check in all_checks)
    print(f"\n{passed}/{len(all_checks)} checks passed")

    RESULTS_DIR.mkdir(exist_ok=True)
    output = {
        "mode": "live" if args.live else "scripted",
        "retrieval": retrieval,
        "scenarios": {name: [vars(check) for check in checks] for name, checks in results.items()},
    }
    (RESULTS_DIR / f"{output['mode']}.json").write_text(json.dumps(output, indent=2))
    return 0 if passed == len(all_checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
