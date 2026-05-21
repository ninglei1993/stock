"""当前扫盘任务的交易日边界（线程内共享，供 adapter 限制回溯范围）。"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

_allowed_days: Optional[tuple[date, ...]] = None
_calendar_start: Optional[date] = None
_calendar_end: Optional[date] = None
_market_cache_stats: dict[str, int] = {}


def set_scan_bounds(
    trade_days: list[date],
    *,
    calendar_start: Optional[date] = None,
    calendar_end: Optional[date] = None,
) -> None:
    """
    设置本次扫描边界。
    - trade_days：区间内实际开市日（扫描循环只跑这些日）
    - calendar_start/end：用户输入的日历起止（仅用于展示，不额外追加交易日）
    """
    global _allowed_days, _calendar_start, _calendar_end
    if not trade_days:
        _allowed_days = None
        _calendar_start = calendar_start
        _calendar_end = calendar_end
        return
    _allowed_days = tuple(sorted(trade_days))
    _calendar_start = calendar_start or _allowed_days[0]
    _calendar_end = calendar_end or _allowed_days[-1]
    logger.info(
        "[流程] 扫描边界 用户输入 %s ~ %s | 实际开市日 %s ~ %s 共 %d 日",
        _calendar_start,
        _calendar_end,
        _allowed_days[0],
        _allowed_days[-1],
        len(_allowed_days),
    )


def set_allowed_trade_days(days: Optional[list[date]]) -> None:
    set_scan_bounds(days or [])


def get_allowed_trade_days() -> Optional[list[date]]:
    if _allowed_days is None:
        return None
    return list(_allowed_days)


def get_calendar_bounds() -> tuple[Optional[date], Optional[date]]:
    return _calendar_start, _calendar_end


def clear_scan_context() -> None:
    global _allowed_days, _calendar_start, _calendar_end, _market_cache_stats
    _allowed_days = None
    _calendar_start = None
    _calendar_end = None
    _market_cache_stats = {}


def set_market_cache_stats(stats: dict[str, int]) -> None:
    global _market_cache_stats
    _market_cache_stats = dict(stats or {})


def pop_market_cache_stats() -> dict[str, int]:
    global _market_cache_stats
    stats = dict(_market_cache_stats)
    _market_cache_stats = {}
    return stats


def lookback_trade_days(anchor: date, lookback: int) -> list[date]:
    """
    在 anchor 及之前取最多 lookback 个交易日。
    若已设置扫描边界，仅使用边界内日期（不拉取用户区间外的数据）。
    """
    lb = max(1, lookback)
    allowed = get_allowed_trade_days()
    if allowed:
        prior = [d for d in allowed if d <= anchor]
        if not prior:
            return []
        return prior[-lb:]
    from datetime import timedelta

    from app.adapters.factory import get_adapter

    start = anchor - timedelta(days=lb * 3)
    days = sorted(get_adapter().get_trade_days(start, anchor))
    if not days:
        return [anchor]
    return days[-lb:]
