import logging
from typing import Optional

from app.adapters.base import MarketDataAdapter
from app.adapters.demo_adapter import DemoAdapter
from app.config import settings

logger = logging.getLogger(__name__)

_adapter_instance: Optional[MarketDataAdapter] = None
_last_jq_error: Optional[str] = None


def reset_adapter() -> None:
    """清除适配器单例（修改 .env 或聚宽恢复后需调用）。"""
    global _adapter_instance, _last_jq_error
    _adapter_instance = None
    _last_jq_error = None


def get_adapter() -> MarketDataAdapter:
    global _adapter_instance, _last_jq_error

    if _adapter_instance is not None:
        return _adapter_instance

    if settings.use_demo_data():
        _adapter_instance = DemoAdapter()
        logger.info("Market data: DemoAdapter (%d concepts)", len(_adapter_instance.list_concepts()))
        return _adapter_instance

    try:
        from app.adapters.jqdata_adapter import JQDataAdapter

        adapter = JQDataAdapter()
        adapter.get_trade_days(
            __import__("datetime").date(2024, 1, 2),
            __import__("datetime").date(2024, 1, 5),
        )
        n = len(adapter.list_concepts())
        _adapter_instance = adapter
        _last_jq_error = None
        logger.info("Market data: JQDataAdapter (%d concepts)", n)
        return _adapter_instance
    except Exception as exc:
        _last_jq_error = str(exc)
        logger.error("JQData connection failed: %s", exc, exc_info=True)
        if settings.jq_configured():
            # 已配置账号时禁止静默回退演示数据
            raise RuntimeError(
                f"聚宽 JQData 连接失败，请检查账号/网络/配额: {exc}"
            ) from exc
        logger.warning("JQData unavailable, falling back to DemoAdapter")
        _adapter_instance = DemoAdapter()
        return _adapter_instance


def adapter_info() -> dict:
    from app.services.concept_cache import cache_meta, get_cached_concepts

    try:
        adapter = get_adapter()
    except RuntimeError as exc:
        return {
            "adapter": "JQDataAdapter",
            "data_source_label": "聚宽连接失败",
            "data_source_short": "连接失败",
            "is_live_data": False,
            "demo_mode": False,
            "jq_configured": settings.jq_configured(),
            "universe_total": 0,
            "jq_error": str(exc),
            "cached": False,
            "count": 0,
        }

    name = adapter.__class__.__name__
    is_jq = name == "JQDataAdapter"
    is_demo = name == "DemoAdapter"

    if settings.jq_configured() and is_demo:
        logger.warning(
            "jq_configured=True but DemoAdapter active; concept cache may be stale"
        )

    try:
        concepts, cache_source = get_cached_concepts()
        total = len(concepts)
    except Exception:
        total = cache_meta().get("count") or 0
        cache_source = name

    if is_jq:
        label = "聚宽 JQData（实盘概念与行情）"
        short = "聚宽数据"
    elif is_demo:
        label = "演示数据（合成行情，非聚宽）"
        short = "演示数据"
    else:
        label = name
        short = name

    return {
        "adapter": name,
        "data_source_label": label,
        "data_source_short": short,
        "is_live_data": is_jq,
        "demo_mode": is_demo,
        "jq_configured": settings.jq_configured(),
        "universe_total": total,
        "concept_cache_source": cache_source,
        "jq_error": _last_jq_error,
        **cache_meta(),
    }
