"""Tushare ts_code 与系统内部证券代码（聚宽风格）互转。"""


def to_internal_code(ts_code: str) -> str:
    """000001.SZ -> 000001.XSHE, 600000.SH -> 600000.XSHG"""
    code, _, exch = ts_code.partition(".")
    exch = exch.upper()
    if exch in ("SZ", "XSHE"):
        return f"{code}.XSHE"
    if exch in ("SH", "XSHG"):
        return f"{code}.XSHG"
    if exch == "BJ":
        return f"{code}.BJ"
    return ts_code


def to_ts_code(internal: str) -> str:
    """000001.XSHE -> 000001.SZ"""
    code, _, suffix = internal.partition(".")
    suffix = suffix.upper()
    if suffix in ("XSHE", "SZ"):
        return f"{code}.SZ"
    if suffix in ("XSHG", "SH"):
        return f"{code}.SH"
    if suffix == "BJ":
        return f"{code}.BJ"
    if "." in internal:
        return internal
    return f"{code}.SZ"
