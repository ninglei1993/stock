"""清空缓存、内存快照与扫描入库数据（含历史演示残留）。"""

from __future__ import annotations

import logging

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import (
    Alert,
    MarketEnvDaily,
    SectorDaily,
    SectorFlowDaily,
    SectorScoreDaily,
    StockDaily,
    ThemeLeaderDaily,
)

logger = logging.getLogger(__name__)


def clear_runtime_caches() -> None:
    import app.adapters.factory as factory_mod

    from app.adapters.tushare_adapter import clear_tushare_caches
    from app.services.concept_cache import clear_concept_cache
    from app.services.stock_names import clear_name_cache
    from app.services.trade_calendar import clear_trade_days_cache
    from app.services.volatile_scan import clear_volatile_snapshots

    factory_mod.reset_adapter()
    clear_concept_cache()
    clear_trade_days_cache()
    clear_name_cache()
    clear_tushare_caches()
    clear_volatile_snapshots()
    logger.info("[系统] 已清空运行时缓存与内存快照")


def clear_demo_data_source_override() -> str | None:
    """若曾选演示数据源，改为 tushare/auto。"""
    from app.config import settings
    from app.services.data_source_store import clear_override, read_override, write_override

    cur = read_override()
    if cur != "demo":
        return cur
    if settings.tushare_configured():
        write_override("tushare")
        return "tushare"
    if settings.jq_configured():
        write_override("jqdata")
        return "jqdata"
    clear_override()
    return None


async def clear_scan_database(session: AsyncSession) -> dict[str, int]:
    """删除扫描产生的业务表数据（保留回测表）。"""
    counts: dict[str, int] = {}
    for model, key in (
        (Alert, "alerts"),
        (SectorScoreDaily, "sector_scores"),
        (ThemeLeaderDaily, "leaders"),
        (StockDaily, "stocks"),
        (SectorFlowDaily, "flows"),
        (SectorDaily, "sectors"),
        (MarketEnvDaily, "market_env"),
    ):
        result = await session.execute(delete(model))
        counts[key] = result.rowcount or 0
    await session.commit()
    logger.info("[系统] 已清空数据库扫描数据: %s", counts)
    return counts
