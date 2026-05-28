"""清空缓存、内存快照与扫描数据。"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def clear_file_scan_storage() -> None:
    """删除 data/market 与 data/scan 下全部落盘数据。"""
    from app.services.latest_scan_store import LatestScanStore
    from app.services.market_cache import get_market_cache
    from app.services.scan_context import clear_scan_context

    get_market_cache().clear_all()
    LatestScanStore.clear()
    clear_scan_context()
    logger.info("[系统] 已清空本地 JSON（全市场行情缓存 + 最新扫盘结果）")


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
    clear_file_scan_storage()
    logger.info("[系统] 已清空运行时缓存与内存快照")
