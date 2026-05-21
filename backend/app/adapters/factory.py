import logging
from typing import Optional

from app.adapters.base import MarketDataAdapter
from app.config import settings

logger = logging.getLogger(__name__)

_adapter_instance: Optional[MarketDataAdapter] = None
_last_tushare_error: Optional[str] = None


def reset_adapter() -> None:
    """清除适配器单例（修改 .env 或切换数据源后需调用）。"""
    global _adapter_instance, _last_tushare_error
    _adapter_instance = None
    _last_tushare_error = None


def _init_tushare_adapter() -> MarketDataAdapter:
    global _last_tushare_error
    from app.adapters.tushare_adapter import TushareAdapter

    from datetime import date, timedelta

    adapter = TushareAdapter()
    today = date.today()
    adapter.get_trade_days(today - timedelta(days=7), today)
    n = len(adapter.list_concepts())
    _last_tushare_error = None
    logger.info("Market data: TushareAdapter (%d concepts)", n)
    return adapter


def get_adapter() -> MarketDataAdapter:
    global _adapter_instance, _last_tushare_error

    if _adapter_instance is not None:
        return _adapter_instance
    if not settings.tushare_configured():
        raise RuntimeError("未配置 Tushare：请在 .env 设置 TUSHARE_TOKEN")
    try:
        _adapter_instance = _init_tushare_adapter()
        return _adapter_instance
    except Exception as exc:
        _last_tushare_error = str(exc)
        logger.error("Tushare connection failed: %s", exc, exc_info=True)
        raise RuntimeError(f"Tushare 连接失败，请检查 TUSHARE_TOKEN/积分/网络: {exc}") from exc


def adapter_info() -> dict:
    from app.services.concept_cache import cache_meta, get_cached_concepts
    from app.services.ingest_settings_store import effective_max_stocks_per_concept

    try:
        adapter = get_adapter()
    except RuntimeError as exc:
        return {
            "adapter": "TushareAdapter",
            "data_source": "tushare",
            "data_source_label": "Tushare 连接失败",
            "data_source_short": "连接失败",
            "is_live_data": False,
            "demo_mode": False,
            "tushare_configured": settings.tushare_configured(),
            "universe_total": 0,
            "tushare_error": str(exc),
            "cached": False,
            "count": 0,
        }

    name = adapter.__class__.__name__
    is_ts = name == "TushareAdapter"

    try:
        concepts, cache_source = get_cached_concepts()
        total = len(concepts)
    except Exception:
        total = cache_meta().get("count") or 0
        cache_source = name

    if is_ts:
        label = "Tushare Pro（同花顺概念与行情）"
        short = "Tushare"
    else:
        label = name
        short = name

    return {
        "adapter": name,
        "data_source": "tushare",
        "data_source_label": label,
        "data_source_short": short,
        "is_live_data": is_ts,
        "demo_mode": False,
        "tushare_configured": settings.tushare_configured(),
        "universe_total": total,
        "concept_cache_source": cache_source,
        "tushare_error": _last_tushare_error,
        "ingest_concept_filter": settings.ingest_concept_filter,
        "ingest_max_concepts": settings.ingest_max_concepts,
        "ingest_max_stocks_per_concept": effective_max_stocks_per_concept(),
        **cache_meta(),
    }
