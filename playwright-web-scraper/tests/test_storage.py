import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest

from webscraper.models import Book, Quote
from webscraper.storage import open_writer


def _book() -> Book:
    return Book(
        url="https://x.test/b",
        title=" Title ",
        category="Poetry",
        upc="U1",
        price_gbp=Decimal("1.50"),
        rating=4,
        in_stock=True,
        stock_count=3,
    )


def test_jsonl_roundtrip(tmp_path: Path) -> None:
    out = tmp_path / "out" / "books.jsonl"
    with open_writer(out, "jsonl") as w:
        w.write(_book())
        w.write(_book())
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    row = json.loads(lines[0])
    assert row["title"] == "Title"  # whitespace stripped by the model
    assert Book.model_validate_json(lines[1]).price_gbp == Decimal("1.50")


def test_csv_flattens_lists(tmp_path: Path) -> None:
    out = tmp_path / "quotes.csv"
    with open_writer(out, "csv") as w:
        w.write(Quote(text="Hi", author="Me", tags=["a", "b"]))
    with out.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["tags"] == "a|b"
    assert rows[0]["author"] == "Me"


def test_failed_run_leaves_no_partial_file(tmp_path: Path) -> None:
    out = tmp_path / "books.jsonl"
    out.write_text("previous good output", encoding="utf-8")
    with pytest.raises(RuntimeError), open_writer(out, "jsonl") as w:
        w.write(_book())
        raise RuntimeError("crash mid-run")
    assert out.read_text(encoding="utf-8") == "previous good output"
    assert not list(tmp_path.glob("*.part"))
