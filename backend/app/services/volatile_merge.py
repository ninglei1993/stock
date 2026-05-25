"""从 volatile 缓冲区读取扫描数据（供 ScanService 使用）。"""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import MarketEnvDaily


def _volatile_rows_in_range(buf, attr: str, lookback_start: date, trade_date: date) -> list:
    bucket = getattr(buf, attr, None)
    if not bucket:
        return []
    if isinstance(bucket, list):
        return [
            r
            for r in bucket
            if lookback_start <= getattr(r, "trade_date", trade_date) <= trade_date
        ]
    if isinstance(bucket, dict):
        return [
            r
            for r in bucket.values()
            if lookback_start <= getattr(r, "trade_date", trade_date) <= trade_date
        ]
    return []


async def merge_sector_daily(
    session: AsyncSession,
    lookback_start: date,
    trade_date: date,
) -> list:
    from app.services.volatile_scan import get_today_buffer

    buf = get_today_buffer()
    if buf and buf.sector_rows:
        return _volatile_rows_in_range(buf, "sector_rows", lookback_start, trade_date)
    return []


async def merge_sector_flow(
    session: AsyncSession,
    lookback_start: date,
    trade_date: date,
) -> list:
    from app.services.volatile_scan import get_today_buffer

    buf = get_today_buffer()
    if buf and buf.flow_rows:
        return _volatile_rows_in_range(buf, "flow_rows", lookback_start, trade_date)
    return []


async def merge_leaders(session: AsyncSession, trade_date: date) -> list:
    from app.services.volatile_scan import get_today_buffer

    buf = get_today_buffer()
    if buf and buf.leader_rows:
        return [r for r in buf.leader_rows if getattr(r, "trade_date", None) == trade_date]
    return []


async def get_market_env_merged(session: AsyncSession, trade_date: date):
    """从 volatile 缓冲区读取市场环境，回退到 DB。"""
    from app.services.volatile_scan import get_today_buffer

    buf = get_today_buffer()
    if buf and buf.market_env is not None:
        if getattr(buf.market_env, "trade_date", None) == trade_date:
            return buf.market_env
    return await session.get(MarketEnvDaily, trade_date)
