"""Small process-local rate limiter used by the single-instance demo API."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True, slots=True)
class _RateLimitWindow:
    """Count and expiry of one client's current fixed-rate window."""

    count: int
    expires_at: float


class RateLimitExceededError(Exception):
    """Raised when a caller exhausts its configured request allowance."""


class FixedWindowRateLimiter:
    """Apply bounded in-memory fixed windows safely across concurrent requests.

    This protects the local demo process. Production deployment replaces this
    implementation with an atomic Redis operation so limits span API instances.
    """

    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        """Create an empty limiter using the supplied monotonic clock."""
        self._clock = clock
        self._lock = asyncio.Lock()
        self._windows: dict[str, _RateLimitWindow] = {}

    async def check(self, *, key: str, limit: int, window_seconds: int) -> None:
        """Consume one request allowance or raise without incrementing the count."""
        now = self._clock()
        async with self._lock:
            existing = self._windows.get(key)
            if existing is None or existing.expires_at <= now:
                self._windows[key] = _RateLimitWindow(count=1, expires_at=now + window_seconds)
                return
            if existing.count >= limit:
                raise RateLimitExceededError
            self._windows[key] = _RateLimitWindow(
                count=existing.count + 1,
                expires_at=existing.expires_at,
            )
