"""统一耗时日志（数据拉取 / 入库 / 评分）。"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator, Optional

logger = logging.getLogger(__name__)


@contextmanager
def log_elapsed(
    operation: str,
    *,
    logger_obj: Optional[logging.Logger] = None,
    extra: str = "",
) -> Iterator[None]:
    """记录操作起止与耗时（秒）。"""
    log = logger_obj or logger
    suffix = f" {extra}" if extra else ""
    log.info("[数据] %s 开始%s", operation, suffix)
    t0 = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - t0
        log.info("[数据] %s 完成 耗时=%.2fs%s", operation, elapsed, suffix)
