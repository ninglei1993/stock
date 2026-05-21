"""market_cache 与 latest_scan_store 单元测试。"""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app.services.latest_scan_store import LatestScanStore
from app.services.market_cache import MarketCacheStore, MarketTable, rows_to_dataframe


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKET_CACHE_ENABLED", "true")
    from app.config import settings

    settings.data_dir = tmp_path
    settings.market_cache_enabled = True
    return tmp_path


def test_market_cache_save_load_roundtrip(tmp_data_dir):
    store = MarketCacheStore()
    td = date(2026, 5, 15)
    df = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "open": 10.0,
                "close": 10.5,
                "high": 10.6,
                "low": 9.9,
                "vol": 1000,
                "amount": 1e7,
                "pct_chg": 5.0,
            }
        ]
    )
    store.save(MarketTable.DAILY, td, df)
    assert store.has_table(MarketTable.DAILY, td)
    loaded = store.load(MarketTable.DAILY, td)
    assert loaded is not None
    assert len(loaded) == 1
    assert loaded.iloc[0]["ts_code"] == "000001.SZ"


def test_market_cache_has_day_requires_all_tables(tmp_data_dir):
    store = MarketCacheStore()
    td = date(2026, 5, 16)
    store.save(MarketTable.DAILY, td, pd.DataFrame([{"ts_code": "1"}]))
    assert not store.has_day(td)
    store.save(MarketTable.LIMIT, td, pd.DataFrame())
    store.save(MarketTable.MONEYFLOW, td, pd.DataFrame())
    assert store.has_day(td)


def test_latest_scan_store_overwrite(tmp_data_dir):
    td = date(2026, 5, 18)
    LatestScanStore.save(
        trade_date=td,
        scores=[
            {
                "trade_date": td,
                "sector_code": "886069.TI",
                "sector_name": "测试",
                "total_score": 80,
                "persistence_score": 90,
                "capital_score": 70,
                "breadth_score": 60,
                "leader_score": 50,
                "relative_score": 40,
                "stage": "ferment",
                "rank": 1,
                "position_hint": "observe",
            }
        ],
        market_env={
            "trade_date": td,
            "env_score": 50,
            "limit_up_count": 10,
            "up_down_ratio": 1.2,
            "index_pct": 0.5,
            "conclusion": "ok",
            "can_long": True,
        },
        leader_map={},
        scan_trade_days=[td],
    )
    loaded = LatestScanStore.load()
    assert loaded is not None
    assert loaded.trade_date == td
    assert len(loaded.scores) == 1
    assert loaded.scores[0].sector_code == "886069.TI"

    LatestScanStore.save(
        trade_date=td,
        scores=[],
        market_env=None,
        leader_map={},
        scan_trade_days=[td],
    )
    loaded2 = LatestScanStore.load()
    assert loaded2 is not None
    assert len(loaded2.scores) == 0


def test_rows_to_dataframe_empty():
    assert rows_to_dataframe([]).empty
