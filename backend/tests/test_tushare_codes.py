"""证券代码规范化。"""

from app.adapters.tushare_codes import normalize_stock_code, to_internal_code, to_ts_code


def test_normalize_bare_shanghai():
    assert normalize_stock_code("600519") == "600519.XSHG"


def test_normalize_bare_shenzhen():
    assert normalize_stock_code("000001") == "000001.XSHE"


def test_normalize_tushare_suffix():
    assert normalize_stock_code("000001.SZ") == "000001.XSHE"
    assert normalize_stock_code("600519.SH") == "600519.XSHG"


def test_roundtrip():
    internal = "300502.XSHE"
    assert to_internal_code(to_ts_code(internal)) == internal
