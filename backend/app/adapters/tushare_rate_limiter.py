import threading
import time

from app.config import settings


class TushareRateLimiter:
    """Tushare 按分钟频次限制，默认约 170 次/分钟（留余量）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._min_interval = 60.0 / max(settings.tushare_rate_limit, 1.0)
        self._last = 0.0

    def acquire_sync(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()


tushare_limiter = TushareRateLimiter()
