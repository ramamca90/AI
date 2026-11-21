"""Pure text-normalisation helpers (no browser needed, trivially unit-testable)."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from webscraper.exceptions import ParseError

_PRICE_RE = re.compile(r"(\d+(?:[.,]\d+)?)")
_STOCK_COUNT_RE = re.compile(r"\((\d+)\s+available\)", re.IGNORECASE)
_RATING_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def parse_price(text: str) -> Decimal:
    """'£51.77' -> Decimal('51.77')."""
    match = _PRICE_RE.search(text.replace(",", ""))
    if not match:
        raise ParseError(f"No price found in {text!r}")
    try:
        return Decimal(match.group(1)).quantize(Decimal("0.01"))
    except InvalidOperation as exc:  # pragma: no cover - regex guarantees digits
        raise ParseError(f"Bad price {text!r}") from exc


def parse_rating(css_class: str) -> int:
    """'star-rating Three' -> 3."""
    for token in css_class.split():
        if (value := _RATING_WORDS.get(token.lower())) is not None:
            return value
    raise ParseError(f"No rating word in class {css_class!r}")


def parse_availability(text: str) -> tuple[bool, int]:
    """'In stock (22 available)' -> (True, 22); 'Out of stock' -> (False, 0)."""
    normalised = " ".join(text.split()).lower()
    in_stock = normalised.startswith("in stock")
    match = _STOCK_COUNT_RE.search(normalised)
    count = int(match.group(1)) if match else 0
    return in_stock, count


def clean_quote(text: str) -> str:
    """Strip whitespace and the decorative curly quotes around a quotation."""
    return text.strip().strip('“”"').strip()
