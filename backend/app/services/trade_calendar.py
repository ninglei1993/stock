"""聚宽账号数据权限日期范围（默认 2025-02-06 ~ 2026-02-13）。"""

from datetime import date
from functools import lru_cache
from typing import Optional

from app.config import settings


def jq_data_start() -> date:
    return settings.jqdata_data_start


def jq_data_end() -> date:
    return settings.jqdata_data_end


def jq_range_label() -> str:
    return f"{jq_data_start()} ~ {jq_data_end()}"


def clamp_to_jq_range(d: date) -> date:
    if d < jq_data_start():
        return jq_data_start()
    if d > jq_data_end():
        return jq_data_end()
    return d


def should_use_jq_bounds() -> bool:
    return settings.jq_configured() and not settings.use_demo_data()


def resolve_scan_date(requested: Optional[date] = None) -> date:
    """
    扫描/入库使用的交易日。
    - 演示模式：可用今天或指定日
    - 聚宽模式：默认权限内最后一个交易日，超出范围则截断
    """
    if not should_use_jq_bounds():
        return requested or date.today()

    if requested is not None:
        return clamp_to_jq_range(requested)

    return latest_trade_day_in_range()


@lru_cache(maxsize=1)
def _jq_trade_days_cached() -> tuple[date, ...]:
    from app.adapters.factory import get_adapter

    adapter = get_adapter()
    if adapter.__class__.__name__ != "JQDataAdapter":
        return ()
    days = adapter.get_trade_days(jq_data_start(), jq_data_end())
    return tuple(days)


def latest_trade_day_in_range() -> date:
    days = _jq_trade_days_cached()
    if days:
        return days[-1]
    return jq_data_end()


def earliest_trade_day_in_range() -> date:
    days = _jq_trade_days_cached()
    if days:
        return days[0]
    return jq_data_start()


def clamp_backtest_range(start: date, end: date) -> tuple[date, date]:
    if not should_use_jq_bounds():
        return start, end
    s = clamp_to_jq_range(start)
    e = clamp_to_jq_range(end)
    if s > e:
        s, e = e, s
    days = _jq_trade_days_cached()
    if days:
        s = next((d for d in days if d >= s), days[0])
        e = next((d for d in reversed(days) if d <= e), days[-1])
        if s > e:
            s = e
    return s, e


def clear_trade_days_cache() -> None:
    _jq_trade_days_cached.cache_clear()
