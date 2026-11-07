from __future__ import annotations

from pathlib import Path

import pytest

from copilot.rag import BM25Retriever
from copilot.rag.bm25 import RUNBOOK_DIR, chunk_markdown, slugify


def test_there_are_runbooks_for_each_expected_failure_mode() -> None:
    names = {path.name for path in RUNBOOK_DIR.glob("*.md")}
    assert len(names) >= 6


def test_chunks_are_split_by_heading_with_stable_refs() -> None:
    chunks = chunk_markdown(
        "sample.md", "# Title\n\n## First part\nalpha\n\n## Second: part!\nbeta\n"
    )
    assert [chunk.ref for chunk in chunks] == [
        "runbook:sample.md#first-part",
        "runbook:sample.md#second-part",
    ]
    assert chunks[0].title == "Title: First part"
    assert chunks[0].text == "alpha"


def test_repeated_headings_get_unique_refs() -> None:
    chunks = chunk_markdown("s.md", "# T\n\n## Verify\none\n\n## Verify\ntwo\n")
    assert [chunk.ref for chunk in chunks] == ["runbook:s.md#verify", "runbook:s.md#verify-2"]


def test_slugify_handles_punctuation() -> None:
    assert slugify("  Mitigate: Capacity & Leaks ") == "mitigate-capacity-leaks"


@pytest.mark.parametrize(
    ("query", "runbook"),
    [
        ("roll back a bad release, new stack traces after deploy", "deploy-rollback.md"),
        ("HikariCP connection is not available pool timed out", "db-connection-pool-exhaustion.md"),
        ("OOMKilled exit code 137 heap OutOfMemoryError", "memory-leak-oom.md"),
        ("circuit breaker open read timeout dependency 504", "downstream-timeouts.md"),
        ("No space left on device WAL log rotation", "disk-full.md"),
        ("x509 certificate has expired TLS handshake", "certificate-expiry.md"),
    ],
)
def test_each_failure_mode_retrieves_its_own_runbook(
    retriever: BM25Retriever, query: str, runbook: str
) -> None:
    hits = retriever.search(query)
    assert hits
    assert hits[0].ref.startswith(f"runbook:{runbook}#")


def test_search_is_deterministic_and_ordered(retriever: BM25Retriever) -> None:
    first = retriever.search("rollback memory timeout", k=5)
    assert first == retriever.search("rollback memory timeout", k=5)
    assert [hit.score for hit in first] == sorted((hit.score for hit in first), reverse=True)


def test_k_limits_results(retriever: BM25Retriever) -> None:
    assert len(retriever.search("connection pool", k=2)) == 2


@pytest.mark.parametrize("query", ["", "   ", "the and of", "zzzzqqq"])
def test_queries_with_no_signal_return_nothing(retriever: BM25Retriever, query: str) -> None:
    assert retriever.search(query) == []


def test_empty_directory_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no runbook chunks"):
        BM25Retriever(tmp_path)
