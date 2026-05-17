from functools import lru_cache

from app.adapters.base import MarketDataAdapter
from app.adapters.demo_adapter import DemoAdapter
from app.config import settings


@lru_cache
def get_adapter() -> MarketDataAdapter:
    if settings.demo_mode:
        return DemoAdapter()
    try:
        from app.adapters.jqdata_adapter import JQDataAdapter

        adapter = JQDataAdapter()
        adapter.get_trade_days(
            __import__("datetime").date(2024, 1, 2),
            __import__("datetime").date(2024, 1, 5),
        )
        return adapter
    except Exception:
        return DemoAdapter()
