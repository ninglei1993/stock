import logging
import time
from datetime import date, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

from app.adapters.base import (
    ConceptInfo,
    IndexBar,
    MarketBreadth,
    MarketDataAdapter,
    SectorQuote,
    StockQuote,
)
from app.adapters.rate_limiter import jqdata_limiter
from app.config import settings

_jq_auth_done = False


def _ensure_auth() -> None:
    global _jq_auth_done
    if _jq_auth_done:
        return
    import jqdatasdk as jq

    if not settings.jqdata_username or not settings.jqdata_password:
        raise RuntimeError("JQData credentials not configured")
    jq.auth(settings.jqdata_username, settings.jqdata_password)
    _jq_auth_done = True


def _to_date_str(d: date) -> str:
    return d.strftime("%Y-%m-%d")


class JQDataAdapter(MarketDataAdapter):
    _concepts_cache: Optional[list[ConceptInfo]] = None

    def get_trade_days(self, start_date: date, end_date: date) -> list[date]:
        _ensure_auth()
        jqdata_limiter.acquire_sync()
        import jqdatasdk as jq

        days = jq.get_trade_days(start_date=_to_date_str(start_date), end_date=_to_date_str(end_date))
        return sorted(pd.Timestamp(d).date() for d in days)

    def list_concepts(self) -> list[ConceptInfo]:
        if JQDataAdapter._concepts_cache is not None:
            return JQDataAdapter._concepts_cache
        _ensure_auth()
        jqdata_limiter.acquire_sync()
        import jqdatasdk as jq

        df = jq.get_concepts()
        JQDataAdapter._concepts_cache = [
            ConceptInfo(code=code, name=str(row["name"])) for code, row in df.iterrows()
        ]
        return JQDataAdapter._concepts_cache

    def get_concept_stocks(self, concept_code: str, trade_date: date) -> list[str]:
        logger.info("[数据] JQ get_concept_stocks concept=%s date=%s", concept_code, trade_date)
        t0 = time.monotonic()
        _ensure_auth()
        jqdata_limiter.acquire_sync()
        import jqdatasdk as jq

        codes = list(jq.get_concept_stocks(concept_code, date=trade_date))
        logger.info(
            "[数据] JQ get_concept_stocks 完成 耗时=%.2fs count=%d",
            time.monotonic() - t0,
            len(codes),
        )
        return codes

    def get_sector_quotes(self, trade_date: date, concept_codes: list[str]) -> list[SectorQuote]:
        from app.services.sector_aggregator import SectorAggregator

        agg = SectorAggregator(self)
        if JQDataAdapter._concepts_cache is None:
            self.list_concepts()
        names = {c.code: c.name for c in (JQDataAdapter._concepts_cache or [])}
        return [
            agg.aggregate_sector(code, names.get(code, code), trade_date)
            for code in concept_codes
        ]

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
        t0 = time.monotonic()
        logger.info(
            "[数据] JQ get_stock_quotes 开始 sector=%s stocks=%d lookback=%d",
            sector_code or "-",
            len(stock_codes),
            price_lookback_days,
        )
        _ensure_auth()
        jqdata_limiter.acquire_sync()
        import jqdatasdk as jq

        start = trade_date - timedelta(days=max(price_lookback_days, 3))
        df = jq.get_price(
            stock_codes,
            start_date=_to_date_str(start),
            end_date=_to_date_str(trade_date),
            frequency="daily",
            fields=["open", "close", "high", "low", "high_limit", "volume", "money", "pre_close"],
            panel=False,
            fill_paused=False,
        )
        if df is None or df.empty:
            return []

        if capital_flows is not None:
            flows = capital_flows
        elif skip_flows:
            flows = {}
        else:
            flows = self.get_capital_flows(stock_codes, trade_date, lookback=1)
        results: list[StockQuote] = []
        for code in stock_codes:
            sub = df[df["code"] == code] if "code" in df.columns else df
            if sub.empty:
                continue
            sub = sub.sort_values("time")
            row = sub.iloc[-1]
            close = float(row["close"])
            high = float(row["high"])
            hl = float(row.get("high_limit", close * 1.1))
            pre = float(row.get("pre_close", close))
            pct = (close / pre - 1) * 100 if pre else 0.0
            is_lu = close >= hl * 0.998 - 1e-6
            is_blow = high >= hl * 0.998 and close < hl * 0.998
            streak = self._calc_streak(sub, hl)
            inflow = flows.get(code, [0.0])
            results.append(
                StockQuote(
                    stock_code=code,
                    sector_code=sector_code,
                    pct_change=round(pct, 2),
                    open=float(row["open"]),
                    close=close,
                    high=high,
                    low=float(row["low"]),
                    high_limit=hl,
                    volume=float(row.get("volume", 0)),
                    money=float(row.get("money", 0)),
                    is_limit_up=is_lu,
                    is_big_yang=pct >= 7,
                    is_blow_up=is_blow,
                    limit_up_streak=streak,
                    net_inflow_main=inflow[-1] if inflow else 0.0,
                )
            )
        logger.info(
            "[数据] JQ get_stock_quotes 完成 耗时=%.2fs 有行情=%d/%d",
            time.monotonic() - t0,
            len(results),
            len(stock_codes),
        )
        return results

    def _calc_streak(self, sub: pd.DataFrame, hl_today: float) -> int:
        streak = 0
        for _, r in sub.iloc[::-1].iterrows():
            c = float(r["close"])
            hl = float(r.get("high_limit", hl_today))
            if c >= hl * 0.998 - 1e-6:
                streak += 1
            else:
                break
        return streak

    def get_capital_flows(
        self, stock_codes: list[str], trade_date: date, lookback: int = 5
    ) -> dict[str, list[float]]:
        if not stock_codes:
            return {}
        t0 = time.monotonic()
        logger.info(
            "[数据] JQ get_capital_flows 开始 stocks=%d lookback=%d",
            len(stock_codes),
            lookback,
        )
        _ensure_auth()
        flows: dict[str, list[float]] = {}
        start = trade_date - timedelta(days=lookback * 3)
        batch_size = 50
        import jqdatasdk as jq

        for i in range(0, len(stock_codes), batch_size):
            batch = stock_codes[i : i + batch_size]
            jqdata_limiter.acquire_sync()
            try:
                df = jq.get_money_flow(
                    batch,
                    start_date=_to_date_str(start),
                    end_date=_to_date_str(trade_date),
                    fields=["date", "sec_code", "net_amount_main"],
                )
            except Exception:
                for c in batch:
                    flows[c] = [0.0] * lookback
                continue
            if df is None or df.empty:
                for c in batch:
                    flows[c] = [0.0] * lookback
                continue
            for code in batch:
                sub = df[df["sec_code"] == code] if "sec_code" in df.columns else df
                vals = (
                    sub.sort_values("date")["net_amount_main"].tail(lookback).tolist()
                    if not sub.empty
                    else []
                )
                while len(vals) < lookback:
                    vals.insert(0, 0.0)
                flows[code] = vals[-lookback:]
        logger.info(
            "[数据] JQ get_capital_flows 完成 耗时=%.2fs stocks=%d",
            time.monotonic() - t0,
            len(stock_codes),
        )
        return flows

    def get_index_bars(self, code: str, start_date: date, end_date: date) -> list[IndexBar]:
        logger.info("[数据] JQ get_index_bars %s %s~%s", code, start_date, end_date)
        _ensure_auth()
        jqdata_limiter.acquire_sync()
        import jqdatasdk as jq

        df = jq.get_price(
            code,
            start_date=_to_date_str(start_date),
            end_date=_to_date_str(end_date),
            frequency="daily",
            fields=["open", "close", "high", "low", "pre_close"],
        )
        if df is None or df.empty:
            return []
        bars: list[IndexBar] = []
        for idx, row in df.iterrows():
            td = pd.Timestamp(idx).date()
            pre = float(row.get("pre_close", row["close"]))
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
        logger.info("[数据] JQ get_market_breadth date=%s", trade_date)
        _ensure_auth()
        jqdata_limiter.acquire_sync()
        import jqdatasdk as jq

        all_stocks = jq.get_all_securities(types=["stock"], date=trade_date)
        codes = list(all_stocks.index[:100])
        quotes = self.get_stock_quotes(
            codes, trade_date, price_lookback_days=3, skip_flows=True
        )
        up = sum(1 for q in quotes if q.pct_change > 0)
        down = sum(1 for q in quotes if q.pct_change < 0)
        limit_up = sum(1 for q in quotes if q.is_limit_up)
        return MarketBreadth(
            trade_date=trade_date,
            limit_up_count=limit_up,
            up_count=up,
            down_count=down,
            total_count=len(quotes),
        )
