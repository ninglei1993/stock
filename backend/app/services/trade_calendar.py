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
    return settings.effective_data_source() == "jqdata"


def normalize_to_trade_day(d: date) -> date:
    """将日期对齐到不晚于 d 的最近一个交易日。"""
    from datetime import timedelta

    from app.adapters.factory import get_adapter

    try:
        adapter = get_adapter()
        days = adapter.get_trade_days(d - timedelta(days=15), d)
        if not days:
            return d
        if d in days:
            return d
        prior = [x for x in days if x <= d]
        return prior[-1] if prior else days[0]
    except Exception:
        return d


def resolve_scan_date(requested: Optional[date] = None) -> date:
    """
    扫描/入库使用的交易日（市场交易日，非任务启动日期）。
    - Tushare/演示：默认最近开市日；指定日会对齐到交易日
    - 聚宽：默认权限内最后交易日，超出范围则截断
    """
    if not should_use_jq_bounds():
        if requested is not None:
            return normalize_to_trade_day(requested)
        return _latest_open_trade_day()

    if requested is not None:
        return normalize_to_trade_day(clamp_to_jq_range(requested))

    return latest_trade_day_in_range()


@lru_cache(maxsize=1)
def _latest_open_trade_day_cached() -> date:
    from datetime import timedelta

    from app.adapters.factory import get_adapter

    today = date.today()
    try:
        adapter = get_adapter()
        days = adapter.get_trade_days(today - timedelta(days=30), today)
        if days:
            return days[-1]
    except Exception:
        pass
    return today


def _latest_open_trade_day() -> date:
    return _latest_open_trade_day_cached()


def clear_trade_day_ui_cache() -> None:
    _jq_trade_days_cached.cache_clear()
    _latest_open_trade_day_cached.cache_clear()


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
    clear_trade_day_ui_cache()
    _ui_default_scan_range_cached.cache_clear()


def ui_default_scan_date() -> date:
    """仪表盘默认交易日（带缓存，避免 /system/status 轮询打爆 Tushare）。"""
    if should_use_jq_bounds():
        return latest_trade_day_in_range()
    return _latest_open_trade_day_cached()


def resolve_scan_trade_days(
    start: Optional[date] = None,
    end: Optional[date] = None,
    *,
    default_count: int = 10,
    quiet: bool = False,
) -> list[date]:
    """
    解析扫描日期区间。

    - 未传起止日：最近 default_count 个交易日（默认 10，非 15；结束日=最近开市日）
    - 已传起止日：严格按日历区间查询开市日，**不**向前补满 default_count 天
    - 返回结果按日期升序，便于多日扫描与日志按时间顺序输出
    """
    import logging
    from datetime import timedelta

    from app.adapters.factory import get_adapter

    log = logging.getLogger(__name__)
    adapter = get_adapter()

    if start is None and end is None:
        end_day = resolve_scan_date()
        probe_start = end_day - timedelta(days=max(default_count * 3, 30))
        days = adapter.get_trade_days(probe_start, end_day)
        if not days:
            return [end_day]
        picked = sorted(
            days[-default_count:] if len(days) > default_count else list(days)
        )
        if not quiet:
            log.info(
                "[流程] 扫描区间（默认最近%d个交易日）%s ~ %s 共%d日",
                default_count,
                picked[0],
                picked[-1],
                len(picked),
            )
        else:
            log.debug(
                "默认扫描区间（最近%d个交易日）%s ~ %s",
                default_count,
                picked[0],
                picked[-1],
            )
        return picked

    if end is None:
        end = start
    if start is None:
        start = end
    if start > end:
        start, end = end, start

    if should_use_jq_bounds():
        start = clamp_to_jq_range(start)
        end = clamp_to_jq_range(end)
        if start > end:
            raise ValueError(
                f"扫描区间 {start} ~ {end} 超出聚宽权限 {jq_data_start()} ~ {jq_data_end()}"
            )

    # 用户明确选择的日历区间：直接查 trade_cal，勿用 resolve_scan_date 单点对齐
    days = sorted(adapter.get_trade_days(start, end))
    if not days:
        raise ValueError(
            f"区间 {start} ~ {end} 内没有 A 股交易日，请确认日期在行情权限内且为开市日"
        )
    if not quiet:
        log.info(
            "[流程] 扫描区间（用户选择 %s ~ %s）实际交易日 %s ~ %s 共 %d 日: %s",
            start,
            end,
            days[0],
            days[-1],
            len(days),
            [str(d) for d in days],
        )
    return days


@lru_cache(maxsize=1)
def _ui_default_scan_range_cached() -> tuple[date, date]:
    """供 /system/status 填默认日期用（缓存，避免轮询反复打 trade_cal）。"""
    days = resolve_scan_trade_days(default_count=10, quiet=True)
    return days[0], days[-1]


def ui_default_scan_range(default_count: int = 10) -> tuple[date, date]:
    """仪表盘默认扫描起止日（最近 default_count 个交易日）。"""
    if default_count == 10:
        return _ui_default_scan_range_cached()
    days = resolve_scan_trade_days(default_count=default_count, quiet=True)
    return days[0], days[-1]
