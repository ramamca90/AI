from __future__ import annotations

import logging

import pytest

from copilot.llm.pricing import compute_cost, priced_usage


@pytest.mark.parametrize(
    ("model", "input_price", "output_price", "cache_read", "cache_write"),
    [
        ("claude-opus-5-5", 4.0, 20.0, 0.20, 5.0),
        ("claude-sonnet-5-5", 2.0, 10.0, 0.20, 2.5),
        ("claude-haiku-5-5", 0.10, 0.50, 0.01, 0.125),
    ],
)
def test_each_token_class_uses_its_own_rate(
    model: str, input_price: float, output_price: float, cache_read: float, cache_write: float
) -> None:
    million = 1_000_000
    assert compute_cost(model, input_tokens=million).usd == pytest.approx(input_price)
    assert compute_cost(model, output_tokens=million).usd == pytest.approx(output_price)
    assert compute_cost(model, cache_read_tokens=million).usd == pytest.approx(cache_read)
    assert compute_cost(model, cache_write_tokens=million).usd == pytest.approx(cache_write)


def test_a_mixed_call_sums_all_classes() -> None:
    cost = compute_cost(
        "claude-opus-5-5",
        input_tokens=1_000,
        output_tokens=500,
        cache_read_tokens=10_000,
        cache_write_tokens=2_000,
    )
    expected = (1_000 * 4 + 500 * 20 + 10_000 * 0.2 + 2_000 * 5) / 1_000_000
    assert cost.usd == pytest.approx(expected)
    assert cost.priced


@pytest.mark.parametrize("model", ["sonnet-5-5", "claude-sonnet-5-5-20261001"])
def test_short_and_dated_ids_resolve(model: str) -> None:
    assert compute_cost(model, input_tokens=1_000_000).usd == pytest.approx(2.0)


def test_unknown_model_is_zero_cost_flagged_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        usage, priced = priced_usage("claude-unreleased-9", input_tokens=1_000)
    assert usage.cost_usd == 0.0
    assert usage.input_tokens == 1_000
    assert priced is False
    assert "claude-unreleased-9" in caplog.text


def test_fallback_targets_are_priced() -> None:
    # A fallback attempt bills at its own rate, so these must not count as free.
    assert compute_cost("claude-opus-4-8", input_tokens=1_000_000).usd == pytest.approx(5.0)
    assert compute_cost("claude-opus-5", output_tokens=1_000_000).usd == pytest.approx(25.0)
