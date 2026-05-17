"""Tushare Pro 行情适配器（同花顺概念板块 + 日线/资金流缓存）。"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from functools import lru_cache
from typing import Optional

import pandas as pd

from app.adapters.base import (
    ConceptInfo,
    IndexBar,
    MarketBreadth,
    MarketDataAdapter,
    SectorQuote,
    StockQuote,
)
from app.adapters.tushare_codes import to_internal_code, to_ts_code
from app.adapters.tushare_rate_limiter import tushare_limiter
from app.config import settings

logger = logging.getLogger(__name__)

_pro = None


def _ensure_pro():
    global _pro
    if _pro is not None:
        return _pro
    if not settings.tushare_configured():
        raise RuntimeError("Tushare token 未配置，请在 .env 设置 TUSHARE_TOKEN")
    import tushare as ts

    _pro = ts.pro_api(settings.tushare_token)
    return _pro


def _fmt(d: date) -> str:
    return d.strftime("%Y%m%d")


class TushareAdapter(MarketDataAdapter):
    """同花顺概念（ths_index / ths_member）+ 按日全市场缓存，降低接口次数。"""

    _concepts_cache: Optional[list[ConceptInfo]] = None
    _daily_cache: dict[str, pd.DataFrame] = {}
    _limit_cache: dict[str, pd.DataFrame] = {}
    _moneyflow_cache: dict[str, pd.DataFrame] = {}

    def __init__(self) -> None:
        _ensure_pro()

    def _call(self, fn_name: str, **kwargs) -> pd.DataFrame:
        tushare_limiter.acquire_sync()
        pro = _ensure_pro()
        fn = getattr(pro, fn_name)
        df = fn(**kwargs)
        if df is None:
            return pd.DataFrame()
        return df

    def get_trade_days(self, start_date: date, end_date: date) -> list[date]:
        df = self._call(
            "trade_cal",
            exchange="SSE",
            start_date=_fmt(start_date),
            end_date=_fmt(end_date),
            is_open="1",
        )
        if df.empty:
            return []
        return [pd.Timestamp(x).date() for x in df["cal_date"].tolist()]

    def list_concepts(self) -> list[ConceptInfo]:
        if TushareAdapter._concepts_cache is not None:
            return TushareAdapter._concepts_cache
        df = self._call("ths_index", exchange="A", type="N")
        if df.empty:
            df = self._call("ths_index")
        concepts: list[ConceptInfo] = []
        for _, row in df.iterrows():
            code = str(row.get("ts_code", ""))
            name = str(row.get("name", code))
            if code:
                concepts.append(ConceptInfo(code=code, name=name))
        TushareAdapter._concepts_cache = concepts
        logger.info("TushareAdapter loaded %d ths concepts", len(concepts))
        return concepts

    def get_concept_stocks(self, concept_code: str, trade_date: date) -> list[str]:
        df = self._call("ths_member", ts_code=concept_code)
        if df.empty:
            return []
        col = "con_code" if "con_code" in df.columns else "code"
        codes = [to_internal_code(str(c)) for c in df[col].dropna().unique()]
        return codes

    def _daily_market(self, trade_date: date) -> pd.DataFrame:
        key = _fmt(trade_date)
        if key not in TushareAdapter._daily_cache:
            df = self._call("daily", trade_date=key)
            TushareAdapter._daily_cache[key] = df
        return TushareAdapter._daily_cache[key]

    def _limit_table(self, trade_date: date) -> pd.DataFrame:
        key = _fmt(trade_date)
        if key not in TushareAdapter._limit_cache:
            try:
                df = self._call("stk_limit", trade_date=key)
            except Exception as exc:
                logger.warning("stk_limit %s failed: %s", key, exc)
                df = pd.DataFrame()
            TushareAdapter._limit_cache[key] = df
        return TushareAdapter._limit_cache[key]

    def _moneyflow_market(self, trade_date: date) -> pd.DataFrame:
        key = _fmt(trade_date)
        if key not in TushareAdapter._moneyflow_cache:
            try:
                df = self._call("moneyflow_dc", trade_date=key)
            except Exception as exc:
                logger.warning("moneyflow_dc %s failed: %s", key, exc)
                df = pd.DataFrame()
            TushareAdapter._moneyflow_cache[key] = df
        return TushareAdapter._moneyflow_cache[key]

    def _up_limit(self, ts_code: str, trade_date: date) -> Optional[float]:
        lim = self._limit_table(trade_date)
        if lim.empty or "ts_code" not in lim.columns:
            return None
        sub = lim[lim["ts_code"] == ts_code]
        if sub.empty:
            return None
        row = sub.iloc[-1]
        for col in ("up_limit", "up_limit_price"):
            if col in row and pd.notna(row[col]):
                return float(row[col])
        return None

    def _net_main_inflow(self, ts_code: str, trade_date: date) -> float:
        mf = self._moneyflow_market(trade_date)
        if mf.empty or "ts_code" not in mf.columns:
            return 0.0
        sub = mf[mf["ts_code"] == ts_code]
        if sub.empty:
            return 0.0
        row = sub.iloc[-1]
        for col in ("net_amount", "net_mf_amount", "net_amount_main"):
            if col in row and pd.notna(row[col]):
                return float(row[col])
        buy = float(row.get("buy_lg_amount", 0) or 0)
        sell = float(row.get("sell_lg_amount", 0) or 0)
        return buy - sell

    def get_stock_quotes(
        self,
        stock_codes: list[str],
        trade_date: date,
        sector_code: str = "",
        *,
        price_lookback_days: int = 12,
        skip_flows: bool = False,
        capital_flows: Optional[dict[str, list[float]]] = None,
    ) -> list[StockQuote]:
        if not stock_codes:
            return []
        ts_codes = [to_ts_code(c) for c in stock_codes]
        ts_set = set(ts_codes)
        start = trade_date - timedelta(days=max(price_lookback_days, 3))
        trade_days = self.get_trade_days(start, trade_date)
        if not trade_days:
            trade_days = [trade_date]

        history: dict[str, list[dict]] = {tc: [] for tc in ts_codes}
        for td in trade_days:
            daily = self._daily_market(td)
            if daily.empty:
                continue
            sub = daily[daily["ts_code"].isin(ts_set)]
            for _, row in sub.iterrows():
                tc = str(row["ts_code"])
                pre = float(row.get("pre_close", row["close"]) or row["close"])
                close = float(row["close"])
                pct = (close / pre - 1) * 100 if pre else 0.0
                up_lim = self._up_limit(tc, td)
                history[tc].append(
                    {
                        "trade_date": td,
                        "open": float(row["open"]),
                        "close": close,
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "pre_close": pre,
                        "pct": pct,
                        "volume": float(row.get("vol", 0) or 0),
                        "money": float(row.get("amount", 0) or 0),
                        "up_limit": up_lim,
                    }
                )

        if capital_flows is not None:
            flows = capital_flows
        elif skip_flows:
            flows = {}
        else:
            flows = self.get_capital_flows(stock_codes, trade_date, lookback=1)

        results: list[StockQuote] = []
        for internal, tc in zip(stock_codes, ts_codes):
            bars = sorted(history.get(tc, []), key=lambda x: x["trade_date"])
            if not bars:
                continue
            row = bars[-1]
            up_lim = row["up_limit"]
            close = row["close"]
            high = row["high"]
            if up_lim is None:
                up_lim = close * 1.1
            is_lu = close >= up_lim * 0.998 - 1e-6 or row["pct"] >= 9.8
            is_blow = high >= up_lim * 0.998 and close < up_lim * 0.998
            streak = self._calc_streak(bars, up_lim)
            inflow = flows.get(internal, [0.0])
            results.append(
                StockQuote(
                    stock_code=internal,
                    sector_code=sector_code,
                    pct_change=round(row["pct"], 2),
                    open=row["open"],
                    close=close,
                    high=high,
                    low=row["low"],
                    high_limit=up_lim,
                    volume=row["volume"],
                    money=row["money"],
                    is_limit_up=is_lu,
                    is_big_yang=row["pct"] >= 7,
                    is_blow_up=is_blow,
                    limit_up_streak=streak,
                    net_inflow_main=inflow[-1] if inflow else 0.0,
                )
            )
        return results

    def _calc_streak(self, bars: list[dict], default_up: float) -> int:
        streak = 0
        for row in reversed(bars):
            up_lim = row.get("up_limit") or default_up
            if row["close"] >= up_lim * 0.998 - 1e-6 or row["pct"] >= 9.8:
                streak += 1
            else:
                break
        return streak

    def get_capital_flows(
        self, stock_codes: list[str], trade_date: date, lookback: int = 5
    ) -> dict[str, list[float]]:
        if not stock_codes:
            return {}
        start = trade_date - timedelta(days=lookback * 3)
        days = self.get_trade_days(start, trade_date)[-lookback:]
        if not days:
            days = [trade_date]
        flows: dict[str, list[float]] = {c: [] for c in stock_codes}
        for td in days:
            self._moneyflow_market(td)
            for code in stock_codes:
                ts = to_ts_code(code)
                val = self._net_main_inflow(ts, td)
                flows[code].append(val)
        for code in stock_codes:
            while len(flows[code]) < lookback:
                flows[code].insert(0, 0.0)
            flows[code] = flows[code][-lookback:]
        return flows

    def get_sector_quotes(self, trade_date: date, concept_codes: list[str]) -> list[SectorQuote]:
        from app.services.sector_aggregator import SectorAggregator

        agg = SectorAggregator(self)
        if TushareAdapter._concepts_cache is None:
            self.list_concepts()
        names = {c.code: c.name for c in (TushareAdapter._concepts_cache or [])}
        return [
            agg.aggregate_sector(code, names.get(code, code), trade_date)
            for code in concept_codes
        ]

    def get_index_bars(self, code: str, start_date: date, end_date: date) -> list[IndexBar]:
        ts_code = to_ts_code(code) if ".XSH" in code or ".XSHE" in code else code
        if ts_code.endswith(".XSHG"):
            ts_code = ts_code.replace(".XSHG", ".SH").replace(".XSHE", ".SZ")
        if code == "000300.XSHG":
            ts_code = "000300.SH"
        df = self._call(
            "index_daily",
            ts_code=ts_code,
            start_date=_fmt(start_date),
            end_date=_fmt(end_date),
        )
        if df.empty:
            return []
        bars: list[IndexBar] = []
        for _, row in df.iterrows():
            td = pd.Timestamp(str(row["trade_date"])).date()
            pre = float(row.get("pre_close", row["close"]) or row["close"])
            close = float(row["close"])
            pct = (close / pre - 1) * 100 if pre else 0.0
            bars.append(
                IndexBar(
                    code=code,
                    trade_date=td,
                    open=float(row["open"]),
                    close=close,
                    high=float(row["high"]),
                    low=float(row["low"]),
                    pct_change=round(pct, 2),
                )
            )
        return bars

    def get_market_breadth(self, trade_date: date) -> MarketBreadth:
        daily = self._daily_market(trade_date)
        if daily.empty:
            return MarketBreadth(trade_date=trade_date)
        pre = daily["pre_close"].astype(float)
        close = daily["close"].astype(float)
        pct = (close / pre - 1) * 100
        up = int((pct > 0).sum())
        down = int((pct < 0).sum())
        try:
            lim = self._call("limit_list_d", trade_date=_fmt(trade_date), limit_type="U")
            limit_up = len(lim) if lim is not None and not lim.empty else int((pct >= 9.8).sum())
        except Exception:
            limit_up = int((pct >= 9.8).sum())
        return MarketBreadth(
            trade_date=trade_date,
            limit_up_count=limit_up,
            up_count=up,
            down_count=down,
            total_count=len(daily),
        )


@lru_cache(maxsize=1)
def load_stock_name_map() -> dict[str, str]:
    adapter = TushareAdapter()
    df = adapter._call("stock_basic", exchange="", list_status="L", fields="ts_code,name")
    if df.empty:
        return {}
    return {to_internal_code(str(r["ts_code"])): str(r["name"]) for _, r in df.iterrows()}


def clear_tushare_caches() -> None:
    TushareAdapter._concepts_cache = None
    TushareAdapter._daily_cache.clear()
    TushareAdapter._limit_cache.clear()
    TushareAdapter._moneyflow_cache.clear()
    load_stock_name_map.cache_clear()
