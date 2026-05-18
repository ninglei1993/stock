import logging
from typing import Optional

from app.adapters.base import MarketDataAdapter
from app.adapters.demo_adapter import DemoAdapter
from app.config import settings

logger = logging.getLogger(__name__)

_adapter_instance: Optional[MarketDataAdapter] = None
_last_jq_error: Optional[str] = None
_last_tushare_error: Optional[str] = None


def reset_adapter() -> None:
    """清除适配器单例（修改 .env 或切换数据源后需调用）。"""
    global _adapter_instance, _last_jq_error, _last_tushare_error
    _adapter_instance = None
    _last_jq_error = None
    _last_tushare_error = None


def _init_jq_adapter() -> MarketDataAdapter:
    """聚宽适配器初始化（逻辑保持与原实现一致）。"""
    global _last_jq_error
    from app.adapters.jqdata_adapter import JQDataAdapter

    from datetime import date, timedelta

    adapter = JQDataAdapter()
    today = date.today()
    adapter.get_trade_days(today - timedelta(days=7), today)
    n = len(adapter.list_concepts())
    _last_jq_error = None
    logger.info("Market data: JQDataAdapter (%d concepts)", n)
    return adapter


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
    global _adapter_instance, _last_jq_error, _last_tushare_error

    if _adapter_instance is not None:
        return _adapter_instance

    provider = settings.resolved_live_provider()
    if provider is None:
        raise RuntimeError(
            "未配置实盘数据源：请在 .env 设置 TUSHARE_TOKEN 或聚宽账号，"
            "并在仪表盘选择 Tushare / 聚宽"
        )

    if provider == "tushare":
        try:
            _adapter_instance = _init_tushare_adapter()
            return _adapter_instance
        except Exception as exc:
            _last_tushare_error = str(exc)
            logger.error("Tushare connection failed: %s", exc, exc_info=True)
            raise RuntimeError(f"Tushare 连接失败，请检查 TUSHARE_TOKEN/积分/网络: {exc}") from exc

    # provider == "jqdata" 或 auto 且已配置聚宽
    try:
        _adapter_instance = _init_jq_adapter()
        return _adapter_instance
    except Exception as exc:
        _last_jq_error = str(exc)
        logger.error("JQData connection failed: %s", exc, exc_info=True)
        if settings.jq_configured() and settings.effective_data_source() == "jqdata":
            raise RuntimeError(
                f"聚宽 JQData 连接失败，请检查账号/网络/配额: {exc}"
            ) from exc
        if settings.tushare_configured():
            try:
                _adapter_instance = _init_tushare_adapter()
                return _adapter_instance
            except Exception as ts_exc:
                _last_tushare_error = str(ts_exc)
        raise RuntimeError(
            f"聚宽 JQData 不可用: {exc}；且 Tushare 未配置或连接失败"
        ) from exc


def adapter_info() -> dict:
    from app.services.concept_cache import cache_meta, get_cached_concepts
    from app.services.ingest_settings_store import effective_max_stocks_per_concept

    ds = settings.effective_data_source()
    try:
        adapter = get_adapter()
    except RuntimeError as exc:
        label = "聚宽连接失败" if settings.effective_data_source() == "jqdata" else "Tushare 连接失败"
        return {
            "adapter": "JQDataAdapter" if ds == "jqdata" else "TushareAdapter",
            "data_source": ds,
            "data_source_label": label,
            "data_source_short": "连接失败",
            "is_live_data": False,
            "demo_mode": False,
            "jq_configured": settings.jq_configured(),
            "tushare_configured": settings.tushare_configured(),
            "universe_total": 0,
            "jq_error": str(exc),
            "cached": False,
            "count": 0,
        }

    name = adapter.__class__.__name__
    is_jq = name == "JQDataAdapter"
    is_ts = name == "TushareAdapter"
    is_demo = name == "DemoAdapter"

    if settings.jq_configured() and is_demo and ds == "jqdata":
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
    elif is_ts:
        label = "Tushare Pro（同花顺概念与行情）"
        short = "Tushare"
    elif is_demo:
        label = "演示数据（合成行情，非实盘）"
        short = "演示数据"
    else:
        label = name
        short = name

    return {
        "adapter": name,
        "data_source": ds,
        "data_source_label": label,
        "data_source_short": short,
        "is_live_data": is_jq or is_ts,
        "demo_mode": is_demo,
        "jq_configured": settings.jq_configured(),
        "tushare_configured": settings.tushare_configured(),
        "universe_total": total,
        "concept_cache_source": cache_source,
        "jq_error": _last_jq_error,
        "tushare_error": _last_tushare_error,
        "ingest_concept_filter": settings.ingest_concept_filter,
        "ingest_max_concepts": settings.ingest_max_concepts,
        "ingest_max_stocks_per_concept": effective_max_stocks_per_concept(),
        **cache_meta(),
    }
