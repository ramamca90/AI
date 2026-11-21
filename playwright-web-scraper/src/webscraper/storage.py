"""Streaming, atomic writers for scraped records.

Records are written as they arrive (constant memory) to ``<file>.part`` and the file is
atomically renamed into place only when the run finishes - so consumers never see a
half-written file, and a crashed run leaves the previous output untouched.
"""

from __future__ import annotations

import csv
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any, Literal, Protocol

from pydantic import BaseModel

logger = logging.getLogger(__name__)

OutputFormat = Literal["jsonl", "csv"]


class RecordWriter(Protocol):
    count: int

    def write(self, record: BaseModel) -> None: ...


class JsonlWriter:
    def __init__(self, fh: IO[str]) -> None:
        self._fh = fh
        self.count = 0

    def write(self, record: BaseModel) -> None:
        self._fh.write(record.model_dump_json() + "\n")
        self.count += 1


class CsvWriter:
    LIST_SEPARATOR = "|"

    def __init__(self, fh: IO[str]) -> None:
        self._fh = fh
        self._writer: csv.DictWriter[str] | None = None
        self.count = 0

    @classmethod
    def _flatten(cls, row: dict[str, Any]) -> dict[str, Any]:
        return {
            k: cls.LIST_SEPARATOR.join(map(str, v)) if isinstance(v, list) else v
            for k, v in row.items()
        }

    def write(self, record: BaseModel) -> None:
        row = self._flatten(record.model_dump(mode="json"))
        if self._writer is None:
            self._writer = csv.DictWriter(self._fh, fieldnames=list(row))
            self._writer.writeheader()
        self._writer.writerow(row)
        self.count += 1


@contextmanager
def open_writer(path: Path, fmt: OutputFormat) -> Iterator[RecordWriter]:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    writer: RecordWriter
    try:
        with tmp.open("w", encoding="utf-8", newline="") as fh:
            writer = JsonlWriter(fh) if fmt == "jsonl" else CsvWriter(fh)
            yield writer
        os.replace(tmp, path)
        logger.info("Wrote %d records to %s", writer.count, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
