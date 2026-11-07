"""BM25 search over the markdown runbooks, one chunk per heading."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]

from copilot.domain.ports import RunbookHit

RUNBOOK_DIR = Path(__file__).resolve().parent.parent / "runbooks"

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_TOKEN = re.compile(r"[a-z0-9]+")
_NON_SLUG = re.compile(r"[^a-z0-9]+")
_STOPWORDS = frozenset(
    "a an and are as at be by for from if in into is it of on or that the then this to with".split()
)


@dataclass(frozen=True)
class Chunk:
    ref: str
    title: str
    text: str


def tokenize(text: str) -> list[str]:
    return [token for token in _TOKEN.findall(text.lower()) if token not in _STOPWORDS]


def slugify(text: str) -> str:
    return _NON_SLUG.sub("-", text.lower()).strip("-") or "section"


def chunk_markdown(file_name: str, markdown: str) -> list[Chunk]:
    """Split on headings. Sections with no body and text above the first heading are dropped."""
    document_title = file_name
    sections: list[tuple[str, list[str]]] = []
    for line in markdown.splitlines():
        heading = _HEADING.match(line)
        if heading is None:
            if sections:
                sections[-1][1].append(line)
            continue
        if len(heading.group(1)) == 1:
            document_title = heading.group(2)
        sections.append((heading.group(2), []))

    chunks: list[Chunk] = []
    slugs: dict[str, int] = {}
    for heading_text, lines in sections:
        body = "\n".join(lines).strip()
        if not body:
            continue
        slug = slugify(heading_text)
        slugs[slug] = slugs.get(slug, 0) + 1
        if slugs[slug] > 1:
            slug = f"{slug}-{slugs[slug]}"
        title = f"{document_title}: {heading_text}"
        chunks.append(Chunk(ref=f"runbook:{file_name}#{slug}", title=title, text=body))
    return chunks


class BM25Retriever:
    """Implements the `Retriever` port. The index is built once, on construction."""

    def __init__(self, directory: Path = RUNBOOK_DIR) -> None:
        self._chunks = [
            chunk
            for path in sorted(directory.glob("*.md"))
            for chunk in chunk_markdown(path.name, path.read_text(encoding="utf-8"))
        ]
        if not self._chunks:
            raise ValueError(f"no runbook chunks found in {directory}")
        # Titles are indexed with the body so "memory leak" finds every section of that runbook.
        self._bm25 = BM25Okapi([tokenize(f"{c.title}\n{c.text}") for c in self._chunks])

    def search(self, query: str, k: int = 3) -> list[RunbookHit]:
        tokens = tokenize(query)
        if not tokens or k < 1:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(
            zip(scores, self._chunks, strict=True),
            key=lambda pair: (-float(pair[0]), pair[1].ref),
        )
        return [
            RunbookHit(ref=chunk.ref, title=chunk.title, text=chunk.text, score=float(score))
            for score, chunk in ranked[:k]
            if score > 0
        ]
