from decimal import Decimal

import pytest

from webscraper.exceptions import ParseError
from webscraper.parsing import clean_quote, parse_availability, parse_price, parse_rating


@pytest.mark.parametrize(
    ("text", "expected"),
    [("£51.77", "51.77"), ("  £0.5 ", "0.50"), ("Â£1,234.00", "1234.00"), ("12", "12.00")],
)
def test_parse_price(text: str, expected: str) -> None:
    assert parse_price(text) == Decimal(expected)


def test_parse_price_rejects_garbage() -> None:
    with pytest.raises(ParseError):
        parse_price("free!")


@pytest.mark.parametrize(
    ("css", "expected"),
    [("star-rating Three", 3), ("star-rating five", 5), ("Zero star-rating", 0)],
)
def test_parse_rating(css: str, expected: int) -> None:
    assert parse_rating(css) == expected


def test_parse_rating_missing() -> None:
    with pytest.raises(ParseError):
        parse_rating("star-rating")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("In stock (22 available)", (True, 22)),
        ("\n   In stock  (1 available)\n", (True, 1)),
        ("In stock", (True, 0)),
        ("Out of stock", (False, 0)),
    ],
)
def test_parse_availability(text: str, expected: tuple[bool, int]) -> None:
    assert parse_availability(text) == expected


def test_clean_quote() -> None:
    assert clean_quote("  “Hello world.” ") == "Hello world."
