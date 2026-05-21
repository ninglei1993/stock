"""回测任务线程内上下文（板块池，不写入 scan-sectors 配置）。"""

from __future__ import annotations

import threading
from typing import Optional

_lock = threading.Lock()
_sector_codes: Optional[list[str]] = None


def set_backtest_sector_codes(codes: list[str]) -> None:
    global _sector_codes
    with _lock:
        _sector_codes = list(codes) if codes else []


def get_backtest_sector_codes() -> Optional[list[str]]:
    with _lock:
        if _sector_codes is None:
            return None
        return list(_sector_codes)


def clear_backtest_context() -> None:
    global _sector_codes
    with _lock:
        _sector_codes = None
