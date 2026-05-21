"""证券名称解析（Tushare stock_basic）。"""

from functools import lru_cache
from typing import Optional

@lru_cache(maxsize=1)
def _load_name_map() -> dict[str, str]:
    try:
        from app.adapters.tushare_adapter import load_stock_name_map

        return load_stock_name_map()
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
