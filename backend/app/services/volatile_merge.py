"""合并 PostgreSQL 历史与 volatile 缓冲区中的当日扫描数据（供 ScanService 使用）。"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.tables import MarketEnvDaily, SectorDaily, SectorFlowDaily, ThemeLeaderDaily


def _volatile_rows_for_date(buf, trade_date: date, attr: str) -> list:
    """按记录上的 trade_date 取 volatile 行，不依赖 buf.trade_date 指针。"""
    bucket = getattr(buf, attr, None)
    if not bucket:
        return []
    if isinstance(bucket, dict):
        return [r for r in bucket.values() if getattr(r, "trade_date", None) == trade_date]
    return [r for r in bucket if getattr(r, "trade_date", None) == trade_date]


async def merge_sector_daily(
    session: AsyncSession,
    lookback_start: date,
    trade_date: date,
) -> list:
    stmt: Select[SectorDaily] = select(SectorDaily).where(
        SectorDaily.trade_date >= lookback_start,
        SectorDaily.trade_date <= trade_date,
    )
    db_rows = (await session.execute(stmt)).scalars().all()
    if not settings.scan_volatile_storage:
        return list(db_rows)
    from app.services.volatile_scan import get_today_buffer

    buf = get_today_buffer()
    if not buf:
        return list(db_rows)
    vol_rows = _volatile_rows_for_date(buf, trade_date, "sectors_by_code")
    if not vol_rows:
        return list(db_rows)
    codes_to_replace = frozenset(r.sector_code for r in vol_rows)
    merged = [
        r
        for r in db_rows
        if not (r.trade_date == trade_date and r.sector_code in codes_to_replace)
    ]
    merged.extend(vol_rows)
    return merged


async def merge_sector_flow(
    session: AsyncSession,
    lookback_start: date,
    trade_date: date,
) -> list:
    stmt = select(SectorFlowDaily).where(
        SectorFlowDaily.trade_date >= lookback_start,
        SectorFlowDaily.trade_date <= trade_date,
    )
    db_rows = (await session.execute(stmt)).scalars().all()
    if not settings.scan_volatile_storage:
        return list(db_rows)
    from app.services.volatile_scan import get_today_buffer

    buf = get_today_buffer()
    if not buf:
        return list(db_rows)
    vol_rows = _volatile_rows_for_date(buf, trade_date, "flows_by_code")
    if not vol_rows:
        return list(db_rows)
    codes_to_replace = frozenset(r.sector_code for r in vol_rows)
    merged = [
        r
        for r in db_rows
        if not (r.trade_date == trade_date and r.sector_code in codes_to_replace)
    ]
    merged.extend(vol_rows)
    return merged


async def merge_leaders(session: AsyncSession, trade_date: date) -> list:
    stmt = select(ThemeLeaderDaily).where(ThemeLeaderDaily.trade_date == trade_date)
    db_rows = (await session.execute(stmt)).scalars().all()
    if not settings.scan_volatile_storage:
        return list(db_rows)
    from app.services.volatile_scan import get_today_buffer

    buf = get_today_buffer()
    if not buf:
        return list(db_rows)
    vol_rows = _volatile_rows_for_date(buf, trade_date, "leaders_by_code")
    if not vol_rows:
        return list(db_rows)
    codes_replace = frozenset(r.sector_code for r in vol_rows)
    merged = [r for r in db_rows if r.sector_code not in codes_replace]
    merged.extend(vol_rows)
    return merged


async def get_market_env_merged(session: AsyncSession, trade_date: date):
    """优先使用 volatile 缓冲区中的市场环境。"""
    if settings.scan_volatile_storage:
        from app.services.volatile_scan import get_today_buffer

        buf = get_today_buffer()
        if buf and buf.market_env is not None:
            if getattr(buf.market_env, "trade_date", None) == trade_date:
                return buf.market_env
    row = await session.get(MarketEnvDaily, trade_date)
    return row
