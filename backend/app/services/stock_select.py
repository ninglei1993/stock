"""入库前成分股筛选（按流动性 / 涨停优先，取 Top N）。"""

import logging
from datetime import date

from app.adapters.base import MarketDataAdapter

logger = logging.getLogger(__name__)


def limit_stocks_for_ingest(
    adapter: MarketDataAdapter,
    stock_codes: list[str],
    trade_date: date,
    max_stocks: int,
) -> list[str]:
    if max_stocks <= 0 or len(stock_codes) <= max_stocks:
        return stock_codes

    name = adapter.__class__.__name__
    if name == "TushareAdapter":
        ranked = _rank_tushare(adapter, stock_codes, trade_date)
    elif name == "JQDataAdapter":
        ranked = _rank_jq(adapter, stock_codes, trade_date)
    else:
        ranked = _rank_via_quotes(adapter, stock_codes, trade_date)

    selected = ranked[:max_stocks]
    logger.info(
        "[数据] limit_stocks_for_ingest %s: %d -> %d (max=%d)",
        name,
        len(stock_codes),
        len(selected),
        max_stocks,
    )
    return selected


def _sort_key(pct: float, money: float, streak: int) -> tuple:
    """涨停/连板优先，其次成交额。"""
    is_hot = pct >= 9.8 or streak > 0
    return (1 if is_hot else 0, streak, money, pct)


def _rank_tushare(adapter, stock_codes: list[str], trade_date: date) -> list[str]:
    from app.adapters.tushare_codes import normalize_stock_code, to_ts_code

    daily = adapter._daily_market(trade_date)  # noqa: SLF001
    if daily.empty or "ts_code" not in daily.columns:
        return stock_codes[:]

    internal_set = {normalize_stock_code(c) for c in stock_codes}
    ts_set = {to_ts_code(c) for c in internal_set}
    sub = daily[daily["ts_code"].isin(ts_set)].copy()
    if sub.empty:
        return stock_codes[:]

    rows: list[tuple[str, float, float, int]] = []
    for _, row in sub.iterrows():
        internal = normalize_stock_code(str(row["ts_code"]))
        pre = float(row.get("pre_close", row["close"]) or row["close"] or 1)
        close = float(row["close"] or 0)
        pct = float(row.get("pct_chg", (close / pre - 1) * 100 if pre else 0) or 0)
        money = float(row.get("amount", 0) or 0)
        ts = str(row["ts_code"])
        up_lim = adapter._up_limit(ts, trade_date)  # noqa: SLF001
        streak = 1 if (up_lim and close >= up_lim * 0.998 - 1e-6) or pct >= 9.8 else 0
        rows.append((internal, pct, money, streak))

    rows.sort(key=lambda x: _sort_key(x[1], x[2], x[3]), reverse=True)
    ranked = [r[0] for r in rows]
    seen = set(ranked)
    for code in stock_codes:
        if code not in seen:
            ranked.append(code)
    return ranked


def _rank_jq(adapter, stock_codes: list[str], trade_date: date) -> list[str]:
    quotes = adapter.get_stock_quotes(
        stock_codes,
        trade_date,
        price_lookback_days=1,
        skip_flows=True,
    )
    if not quotes:
        return stock_codes[:]
    quotes.sort(
        key=lambda q: _sort_key(q.pct_change, q.money, q.limit_up_streak),
        reverse=True,
    )
    ranked = [q.stock_code for q in quotes]
    seen = set(ranked)
    for code in stock_codes:
        if code not in seen:
            ranked.append(code)
    return ranked


def _rank_via_quotes(adapter, stock_codes: list[str], trade_date: date) -> list[str]:
    try:
        quotes = adapter.get_stock_quotes(
            stock_codes,
            trade_date,
            price_lookback_days=1,
            skip_flows=True,
        )
    except TypeError:
        quotes = adapter.get_stock_quotes(stock_codes, trade_date)
    if not quotes:
        return stock_codes[:]
    quotes.sort(
        key=lambda q: _sort_key(q.pct_change, q.money, q.limit_up_streak),
        reverse=True,
    )
    return [q.stock_code for q in quotes]
