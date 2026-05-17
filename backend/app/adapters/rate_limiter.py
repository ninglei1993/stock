import asyncio
import time
from collections import deque


class RateLimiter:
    """Token bucket style rate limiter for JQData API calls."""

    def __init__(self, max_per_second: float = 25.0):
        self.max_per_second = max_per_second
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            while self._timestamps and now - self._timestamps[0] > 1.0:
                self._timestamps.popleft()
            if len(self._timestamps) >= self.max_per_second:
                sleep_time = 1.0 - (now - self._timestamps[0])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] > 1.0:
                    self._timestamps.popleft()
            self._timestamps.append(time.monotonic())

    def acquire_sync(self) -> None:
        now = time.monotonic()
        while self._timestamps and now - self._timestamps[0] > 1.0:
            self._timestamps.popleft()
        if len(self._timestamps) >= self.max_per_second:
            sleep_time = 1.0 - (now - self._timestamps[0])
            if sleep_time > 0:
                time.sleep(sleep_time)
            now = time.monotonic()
            while self._timestamps and now - self._timestamps[0] > 1.0:
                self._timestamps.popleft()
        self._timestamps.append(time.monotonic())


jqdata_limiter = RateLimiter()
