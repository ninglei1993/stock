"""成分股 Top N 筛选。"""

from datetime import date
from unittest.mock import MagicMock

import pandas as pd

from app.services.ingest_settings_store import (
    effective_max_stocks_per_concept,
    write_max_stocks_override,
)
from app.services.stock_select import limit_stocks_for_ingest


def test_effective_max_stocks_override(tmp_path, monkeypatch):
    override = tmp_path / "ingest_settings.override.json"
    monkeypatch.setattr(
        "app.services.ingest_settings_store._OVERRIDE_FILE",
        override,
    )
    write_max_stocks_override(20)
    assert effective_max_stocks_per_concept() == 20


def test_limit_stocks_zero_means_all():
    adapter = MagicMock()
    type(adapter).__name__ = "DemoAdapter"
    codes = ["a", "b", "c"]
    assert limit_stocks_for_ingest(adapter, codes, date(2026, 4, 17), 0) == codes


def test_limit_tushare_by_amount():
    adapter = MagicMock()
    type(adapter).__name__ = "TushareAdapter"
    adapter._daily_market.return_value = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
            "close": [10.0, 20.0, 30.0],
            "pre_close": [9.0, 19.0, 29.0],
            "pct_chg": [5.0, 9.9, 1.0],
            "amount": [100.0, 500.0, 200.0],
        }
    )

    from app.adapters.tushare_codes import to_internal_code

    codes = [to_internal_code(c) for c in ["000001.SZ", "000002.SZ", "000003.SZ"]]
    selected = limit_stocks_for_ingest(adapter, codes, date(2026, 4, 17), 2)
    assert len(selected) == 2
    # 涨停优先，其次成交额：000002 涨停+成交额最大应在前
    assert selected[0] == to_internal_code("000002.SZ")
