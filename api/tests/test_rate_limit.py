"""Tests for the process-local rate limiter used by the demo API."""

import pytest

from quiz_api.web.rate_limit import FixedWindowRateLimiter, RateLimitExceededError


async def test_rate_limiter_rejects_requests_after_the_configured_limit() -> None:
    """A caller cannot consume more than its allowance within one fixed window."""
    limiter = FixedWindowRateLimiter(clock=lambda: 10.0)

    await limiter.check(key="participant:1", limit=2, window_seconds=60)
    await limiter.check(key="participant:1", limit=2, window_seconds=60)

    with pytest.raises(RateLimitExceededError):
        await limiter.check(key="participant:1", limit=2, window_seconds=60)


async def test_rate_limiter_resets_an_expired_window() -> None:
    """A new fixed window restores a caller's full allowance."""
    now = 10.0
    limiter = FixedWindowRateLimiter(clock=lambda: now)
    await limiter.check(key="participant:1", limit=1, window_seconds=60)
    now = 70.0

    await limiter.check(key="participant:1", limit=1, window_seconds=60)
