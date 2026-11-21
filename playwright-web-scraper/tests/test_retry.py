import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from webscraper.exceptions import HttpStatusError, ParseError
from webscraper.retry import backoff_delay, is_retryable, retry_async


class Flaky:
    def __init__(self, failures: list[Exception]) -> None:
        self.failures = failures
        self.calls = 0

    async def __call__(self) -> str:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return "ok"


async def test_succeeds_after_transient_failures() -> None:
    op = Flaky([PlaywrightTimeoutError("slow"), HttpStatusError("u", 503)])
    assert await retry_async(op, max_retries=3, base_delay=0) == "ok"
    assert op.calls == 3


async def test_gives_up_after_budget() -> None:
    op = Flaky([HttpStatusError("u", 503)] * 5)
    with pytest.raises(HttpStatusError):
        await retry_async(op, max_retries=2, base_delay=0)
    assert op.calls == 3


@pytest.mark.parametrize("exc", [HttpStatusError("u", 404), ParseError("layout"), ValueError()])
async def test_non_retryable_errors_fail_fast(exc: Exception) -> None:
    op = Flaky([exc])
    with pytest.raises(type(exc)):
        await retry_async(op, max_retries=5, base_delay=0)
    assert op.calls == 1


def test_retry_policy() -> None:
    assert is_retryable(HttpStatusError("u", 429))
    assert not is_retryable(HttpStatusError("u", 403))


def test_backoff_is_capped() -> None:
    assert all(0 <= backoff_delay(10, base=1, cap=5) <= 5 for _ in range(100))
