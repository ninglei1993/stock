"""Tushare ts_code 与系统内部证券代码（聚宽风格）互转。"""


def normalize_stock_code(raw: str) -> str:
    """统一为 000001.XSHE / 600000.XSHG 等内部代码（处理 ths_member 仅 6 位数字的情况）。"""
    s = (raw or "").strip()
    if not s:
        return s
    if "." in s:
        upper = s.upper()
        if upper.endswith((".XSHG", ".XSHE", ".BJ")):
            return upper
        return to_internal_code(s)
    digits = "".join(c for c in s if c.isdigit())
    if len(digits) < 6:
        return s
    code = digits[:6]
    if code.startswith(("6", "9")):
        return f"{code}.XSHG"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return f"{code}.XSHE"


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
    if code.isdigit() and len(code) == 6:
        return normalize_stock_code(code)
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
