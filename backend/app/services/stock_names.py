"""聚宽证券名称解析（回测/入库展示用）。"""

from functools import lru_cache
from typing import Optional

from app.config import settings


@lru_cache(maxsize=1)
def _load_name_map() -> dict[str, str]:
    if settings.use_demo_data():
        return {}
    try:
        provider = settings.resolved_live_provider()
        if provider == "tushare":
            from app.adapters.tushare_adapter import load_stock_name_map

            return load_stock_name_map()

        from app.adapters.jqdata_adapter import _ensure_auth
        from app.adapters.rate_limiter import jqdata_limiter

        _ensure_auth()
        jqdata_limiter.acquire_sync()
        import jqdatasdk as jq

        df = jq.get_all_securities(types=["stock"])
        return {str(code): str(row["display_name"]) for code, row in df.iterrows()}
    except Exception:
        return {}


def resolve_stock_name(stock_code: str) -> str:
    return _load_name_map().get(stock_code, stock_code)


def resolve_stock_names(stock_codes: list[str]) -> dict[str, str]:
    m = _load_name_map()
    return {c: m.get(c, c) for c in stock_codes}


def clear_name_cache() -> None:
    _load_name_map.cache_clear()
    try:
        from app.adapters.tushare_adapter import load_stock_name_map

        load_stock_name_map.cache_clear()
    except ImportError:
        pass
