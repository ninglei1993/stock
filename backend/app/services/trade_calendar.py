"""交易日工具（基于 Tushare 交易日历）。"""

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from typing import Optional

from app.config import settings


def _today_cn() -> date:
    return datetime.now(timezone(timedelta(hours=8))).date()


def _latest_cached_market_day(max_day: date) -> Optional[date]:
    if not settings.market_cache_enabled:
        return None
    try:
        from app.services.market_cache import get_market_cache

        days = [d for d in get_market_cache().list_trade_days() if d <= max_day]
        return days[-1] if days else None
    except Exception:
        return None


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
    - 默认最近开市日；指定日会对齐到交易日
    """
    completed = _latest_completed_trade_day()
    if requested is not None:
        aligned = normalize_to_trade_day(requested)
        return aligned if aligned <= completed else completed
    return completed


@lru_cache(maxsize=1)
def _latest_open_trade_day_cached() -> date:
    from datetime import timedelta

    from app.adapters.factory import get_adapter

    today = _today_cn()
    try:
        adapter = get_adapter()
        days = adapter.get_trade_days(today - timedelta(days=30), today)
        if days:
            return days[-1]
    except Exception:
        pass
    cached = _latest_cached_market_day(today)
    if cached is not None:
        return cached
    return today


def _latest_open_trade_day() -> date:
    return _latest_open_trade_day_cached()


def _latest_completed_trade_day() -> date:
    """
    最近一个“已收盘”交易日。
    规则：按北京时间判断，15:00 前不把当日视作可回测完成日。
    """
    latest = _latest_open_trade_day_cached()
    now_cn = datetime.now(timezone(timedelta(hours=8)))
    if latest == now_cn.date() and now_cn.time() < time(15, 0):
        from app.adapters.factory import get_adapter

        try:
            adapter = get_adapter()
            prior = adapter.get_trade_days(latest - timedelta(days=30), latest - timedelta(days=1))
            if prior:
                return prior[-1]
        except Exception:
            pass
        cached_prior = _latest_cached_market_day(latest - timedelta(days=1))
        if cached_prior is not None:
            return cached_prior
        return latest - timedelta(days=1)
    return latest


def latest_completed_trade_day() -> date:
    """最近一个已收盘交易日（对外公开）。"""
    return _latest_completed_trade_day()


def clear_trade_day_ui_cache() -> None:
    _latest_open_trade_day_cached.cache_clear()


def clamp_backtest_range(start: date, end: date) -> tuple[date, date]:
    s, e = (start, end) if start <= end else (end, start)

    # 无论数据源，结束日都不应超过“最近已收盘交易日”。
    completed = _latest_completed_trade_day()
    if e > completed:
        e = completed
    if s > e:
        s = e
    return s, e


def clear_trade_days_cache() -> None:
    clear_trade_day_ui_cache()
    _ui_default_scan_range_cached.cache_clear()


def ui_default_scan_date() -> date:
    """仪表盘默认交易日（带缓存，避免 /system/status 轮询打爆 Tushare）。"""
    return _latest_completed_trade_day()


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

    completed = _latest_completed_trade_day()
    if start is None and end is None:
        # 默认区间：当前时间前一个月 ~ 今天（再映射为区间内交易日）
        end_day = completed
        start_day = end_day - timedelta(days=30)
        if should_use_jq_bounds():
            start_day = clamp_to_jq_range(start_day)
            end_day = clamp_to_jq_range(end_day)
            if start_day > end_day:
                start_day = end_day
        days = sorted(adapter.get_trade_days(start_day, end_day))
        if not days:
            return [resolve_scan_date(end_day)]
        picked = list(days)
        if not quiet:
            log.info(
                "[流程] 扫描区间（默认近1个月）%s ~ %s 共%d日",
                picked[0],
                picked[-1],
                len(picked),
            )
        else:
            log.debug(
                "默认扫描区间（近1个月）%s ~ %s",
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
    if end > completed:
        end = completed
    if start > end:
        start = end

    # 用户明确选择的日历区间：直接查 trade_cal，勿用 resolve_scan_date 单点对齐
    days = sorted(adapter.get_trade_days(start, end))
    if not days:
        # 先尝试用本地 market cache 的交易日清单恢复区间，避免误降级成 1 日。
        cache_days: list[date] = []
        if settings.market_cache_enabled:
            try:
                from app.services.market_cache import get_market_cache

                cache_days = [
                    d for d in get_market_cache().list_trade_days() if start <= d <= end
                ]
            except Exception:
                cache_days = []
        if cache_days:
            if not quiet:
                log.warning(
                    "[流程] trade_cal 区间无结果，改用本地缓存交易日 %s ~ %s 共 %d 日",
                    cache_days[0],
                    cache_days[-1],
                    len(cache_days),
                )
            return cache_days
        # 仍无可用区间时，再回退到单日对齐，避免用户被硬错误阻断。
        fallback_day = resolve_scan_date(end)
        if not quiet:
            log.warning(
                "[流程] trade_cal 区间无结果且本地无缓存，回退单日扫描 %s（请求区间 %s ~ %s）",
                fallback_day,
                start,
                end,
            )
        return [fallback_day]
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
    """供 /system/status 填默认日期用（默认当前时间前一个月 ~ 今天）。"""
    end_day = _latest_completed_trade_day()
    start_day = end_day - timedelta(days=30)
    return start_day, end_day


def ui_default_scan_range(default_count: int = 10) -> tuple[date, date]:
    """仪表盘默认扫描起止日（默认当前时间前一个月 ~ 今天）。"""
    if default_count == 10:
        return _ui_default_scan_range_cached()
    end_day = _latest_completed_trade_day()
    start_day = end_day - timedelta(days=30)
    return start_day, end_day
