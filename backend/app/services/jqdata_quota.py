"""JQData batch fetch scheduling with rate limiting and retry."""
import logging
import time
from collections.abc import Callable
from typing import TypeVar

from app.adapters.rate_limiter import jqdata_limiter

logger = logging.getLogger(__name__)
T = TypeVar("T")


def fetch_with_retry(
    fn: Callable[[], T],
    retries: int = 3,
    delay: float = 1.0,
) -> T:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            jqdata_limiter.acquire_sync()
            return fn()
        except Exception as exc:
            last_exc = exc
            logger.warning("JQData fetch attempt %s failed: %s", attempt + 1, exc)
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
    if last_exc:
        raise last_exc
    raise RuntimeError("fetch_with_retry failed")


async def batch_fetch(
    items: list,
    fetch_one: Callable,
    batch_size: int = 50,
) -> list:
    """Process items in batches with rate limiting between batches."""
    results = []
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        for item in batch:
            results.append(fetch_with_retry(lambda item=item: fetch_one(item)))
        if i + batch_size < len(items):
            time.sleep(0.05)
    return results
