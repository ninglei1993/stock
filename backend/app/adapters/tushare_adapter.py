"""Tushare Pro 行情适配器（同花顺概念板块 + 日线/资金流缓存）。"""

from __future__ import annotations

import logging
import time
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
from app.adapters.tushare_codes import normalize_stock_code, to_internal_code, to_ts_code
from app.adapters.tushare_rate_limiter import tushare_limiter
from app.config import settings

logger = logging.getLogger(__name__)

_pro = None


def reset_tushare_client() -> None:
    global _pro
    _pro = None


def _apply_api_endpoint(pro) -> None:
    url = (settings.tushare_api_url or "").strip().rstrip("/")
    if url:
        pro._DataApi__http_url = url


def _ensure_pro():
    global _pro
    if _pro is not None:
        return _pro
    if not settings.tushare_configured():
        raise RuntimeError("Tushare token 未配置，请在 .env 设置 TUSHARE_TOKEN")
    import tushare as ts

    ts.set_token(settings.tushare_token)
    pro = ts.pro_api(settings.tushare_token)
    _apply_api_endpoint(pro)
    _pro = pro
    endpoint = getattr(pro, "_DataApi__http_url", "default")
    logger.info("Tushare client ready, endpoint=%s", endpoint)
    return _pro


def _fmt(d: date) -> str:
    return d.strftime("%Y%m%d")


class TushareAdapter(MarketDataAdapter):
    """同花顺概念（ths_index / ths_member）+ 按日全市场缓存，降低接口次数。"""

    _concepts_cache: Optional[list[ConceptInfo]] = None
    _daily_cache: dict[str, pd.DataFrame] = {}
    _limit_cache: dict[str, pd.DataFrame] = {}
    _moneyflow_cache: dict[str, pd.DataFrame] = {}
    _trade_days_cache: dict[tuple[str, str], list[date]] = {}
    _member_cache: dict[str, list[str]] = {}

    def __init__(self) -> None:
        _ensure_pro()

    def _call(self, fn_name: str, *, plain: str = "", **kwargs) -> pd.DataFrame:
        tushare_limiter.acquire_sync()
        pro = _ensure_pro()
        fn = getattr(pro, fn_name)
        if plain:
            logger.info("[流程] %s", plain)
        logger.info("[数据] Tushare %s 请求 %s", fn_name, kwargs)
        t0 = time.monotonic()
        df = fn(**kwargs)
        elapsed = time.monotonic() - t0
        if df is None:
            logger.warning("[数据] Tushare %s 返回 None 耗时=%.2fs", fn_name, elapsed)
            return pd.DataFrame()
        logger.info(
            "[数据] Tushare %s 完成 耗时=%.2fs rows=%d",
            fn_name,
            elapsed,
            len(df),
        )
        if not df.empty and logger.isEnabledFor(logging.DEBUG):
            logger.debug("Tushare %s sample:\n%s", fn_name, df.head(2).to_string())
        return df

    def get_trade_days(self, start_date: date, end_date: date) -> list[date]:
        cache_key = (_fmt(start_date), _fmt(end_date))
        if cache_key in TushareAdapter._trade_days_cache:
            days = TushareAdapter._trade_days_cache[cache_key]
            logger.debug(
                "[数据] trade_cal(%s~%s) 命中缓存 days=%d",
                start_date,
                end_date,
                len(days),
            )
            return days
        df = self._call(
            "trade_cal",
            plain=f"查询 {start_date} 至 {end_date} 的 A 股开市日历",
            exchange="SSE",
            start_date=_fmt(start_date),
            end_date=_fmt(end_date),
            is_open="1",
        )
        if df.empty:
            return []
        days = sorted(pd.Timestamp(x).date() for x in df["cal_date"].tolist())
        TushareAdapter._trade_days_cache[cache_key] = days
        return days

    def list_concepts(self) -> list[ConceptInfo]:
        if TushareAdapter._concepts_cache is not None:
            logger.debug("[数据] list_concepts 命中缓存 count=%d", len(TushareAdapter._concepts_cache))
            return TushareAdapter._concepts_cache
        logger.info("[数据] list_concepts 开始 ths_index")
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
        if concept_code in TushareAdapter._member_cache:
            cached = TushareAdapter._member_cache[concept_code]
            logger.info(
                "[数据] get_concept_stocks concept=%s 命中成分股缓存 count=%d",
                concept_code,
                len(cached),
            )
            return list(cached)
        logger.info(
            "[流程] 拉取概念板块 %s 的成分股列表（ths_member，每板块仅请求一次）",
            concept_code,
        )
        df = self._call(
            "ths_member",
            plain=f"获取概念板块 {concept_code} 的全部成分股代码",
            ts_code=concept_code,
        )
        if df.empty:
            logger.warning("[数据] get_concept_stocks 无成分 concept=%s", concept_code)
            return []
        col = "con_code" if "con_code" in df.columns else "code"
        codes = [normalize_stock_code(str(c)) for c in df[col].dropna().unique()]
        TushareAdapter._member_cache[concept_code] = codes
        logger.info("[数据] get_concept_stocks 完成 concept=%s count=%d", concept_code, len(codes))
        return codes

    def _daily_market(self, trade_date: date) -> pd.DataFrame:
        key = _fmt(trade_date)
        if key in TushareAdapter._daily_cache:
            logger.debug(
                "[数据] daily(%s) 命中缓存，跳过接口（全市场约 %d 行）",
                key,
                len(TushareAdapter._daily_cache[key]),
            )
            return TushareAdapter._daily_cache[key]
        df = self._call(
            "daily",
            plain=f"拉取 {trade_date} 全市场约 5000 只股票日线行情（开高低收、成交额）",
            trade_date=key,
        )
        TushareAdapter._daily_cache[key] = df
        return df

    def _limit_table(self, trade_date: date) -> pd.DataFrame:
        key = _fmt(trade_date)
        if key in TushareAdapter._limit_cache:
            logger.debug(
                "[数据] stk_limit(%s) 命中缓存，跳过接口（%d 行）",
                key,
                len(TushareAdapter._limit_cache[key]),
            )
            return TushareAdapter._limit_cache[key]
        try:
            df = self._call(
                "stk_limit",
                plain=f"拉取 {trade_date} 全市场涨跌停价格表",
                trade_date=key,
            )
        except Exception as exc:
            logger.warning("[数据] stk_limit(%s) 失败: %s", key, exc)
            df = pd.DataFrame()
        TushareAdapter._limit_cache[key] = df
        return df

    def _moneyflow_market(self, trade_date: date) -> pd.DataFrame:
        key = _fmt(trade_date)
        if key in TushareAdapter._moneyflow_cache:
            logger.debug(
                "[数据] moneyflow_dc(%s) 命中缓存，跳过接口（全市场约 %d 行）",
                key,
                len(TushareAdapter._moneyflow_cache[key]),
            )
            return TushareAdapter._moneyflow_cache[key]
        try:
            df = self._call(
                "moneyflow_dc",
                plain=f"拉取 {trade_date} 全市场约 5000 只股票主力资金流向",
                trade_date=key,
            )
        except Exception as exc:
            logger.warning("[数据] moneyflow_dc(%s) 失败: %s", key, exc)
            df = pd.DataFrame()
        TushareAdapter._moneyflow_cache[key] = df
        return df

    def prefetch_shared_market_data(
        self,
        trade_date: date,
        flow_lookback: int,
        price_lookback: int,
    ) -> dict[str, int]:
        """
        扫描开始前一次性预热全市场公有表（按交易日去重），
        后续各概念板块从内存缓存筛选，不再重复请求接口。
        若存在用户扫描边界，仅预取边界内交易日（不回溯到 4 月等区间外日期）。
        """
        from app.services.scan_context import get_allowed_trade_days, lookback_trade_days

        flow_lb = max(1, flow_lookback)
        price_lb = max(1, price_lookback)
        allowed = get_allowed_trade_days()
        if allowed:
            flow_days = lookback_trade_days(trade_date, flow_lb)
            price_days = lookback_trade_days(trade_date, price_lb)
            need_days = sorted({*flow_days, *price_days, trade_date})
        else:
            flow_start = trade_date - timedelta(days=flow_lb * 3)
            price_start = trade_date - timedelta(days=max(price_lb, 3))
            flow_days = self.get_trade_days(flow_start, trade_date)[-flow_lb:]
            price_days = self.get_trade_days(price_start, trade_date)
            need_days = sorted({*flow_days, *price_days, trade_date})

        api_calls = 0
        for td in need_days:
            key = _fmt(td)
            before = (
                key not in TushareAdapter._daily_cache,
                key not in TushareAdapter._limit_cache,
                key not in TushareAdapter._moneyflow_cache,
            )
            self._daily_market(td)
            self._limit_table(td)
            self._moneyflow_market(td)
            if any(before):
                api_calls += sum(before)

        logger.info(
            "[流程] 全市场公有数据预取完成 anchor=%s 交易日 %d 个（%s ~ %s）本次新请求约 %d 次",
            trade_date,
            len(need_days),
            need_days[0] if need_days else trade_date,
            need_days[-1] if need_days else trade_date,
            api_calls,
        )
        return {
            "trade_days": len(need_days),
            "api_calls": api_calls,
            "flow_days": len(flow_days),
            "price_days": len(price_days),
        }

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

    @staticmethod
    def _limit_pct_threshold(stock_code: str) -> float:
        """
        根据交易所板块给出涨停判定阈值（用于 up_limit 缺失时兜底）。
        - 主板：10%
        - 创业板/科创板：20%
        - 北交所：30%
        """
        internal = to_internal_code(stock_code)
        raw = internal.split(".")[0]
        if raw.startswith(("300", "301", "688", "689")):
            return 19.8
        if raw.startswith(("8", "4")):
            return 29.8
        return 9.8

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
            "[数据] get_stock_quotes 开始 sector=%s stocks=%d lookback_days=%d date=%s",
            sector_code or "-",
            len(stock_codes),
            price_lookback_days,
            trade_date,
        )
        ts_codes = [to_ts_code(c) for c in stock_codes]
        ts_to_internal = {to_ts_code(c): to_internal_code(c) for c in stock_codes}
        ts_set = set(ts_codes)
        from app.services.scan_context import lookback_trade_days

        trade_days = lookback_trade_days(trade_date, price_lookback_days)
        if not trade_days:
            trade_days = [trade_date]

        history: dict[str, list[dict]] = {tc: [] for tc in ts_codes}
        for td in trade_days:
            day_t0 = time.monotonic()
            daily = self._daily_market(td)
            if daily.empty:
                continue
            sub = daily[daily["ts_code"].isin(ts_set)]
            logger.info(
                "[数据] get_stock_quotes 交易日 %s daily过滤 %d/%d 只 本日耗时=%.2fs",
                td,
                len(sub),
                len(ts_set),
                time.monotonic() - day_t0,
            )
            for _, row in sub.iterrows():
                tc = str(row["ts_code"])
                pre = float(row.get("pre_close", row["close"]) or row["close"])
                close = float(row["close"])
                pct = (close / pre - 1) * 100 if pre else 0.0
                up_lim = self._up_limit(tc, td)
                history[tc].append(
                    {
                        "trade_date": td,
                        "stock_code": ts_to_internal.get(tc, tc),
                        "open": float(row["open"]),
                        "close": close,
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "pre_close": pre,
                        "pct": pct,
                        "volume": float(row.get("vol", 0) or 0),
                        "money": float(row.get("amount", 0) or 0),
                        "up_limit": up_lim,
                        "limit_pct": self._limit_pct_threshold(
                            ts_to_internal.get(tc, tc)
                        ),
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
            limit_pct = float(row.get("limit_pct", self._limit_pct_threshold(internal)))
            if up_lim is None:
                is_lu = row["pct"] >= limit_pct
                is_blow = False
            else:
                is_lu = close >= up_lim * 0.998 - 1e-6
                is_blow = high >= up_lim * 0.998 and close < up_lim * 0.998
            streak = self._calc_streak(bars, limit_pct)
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
        logger.info(
            "[数据] get_stock_quotes 完成 sector=%s 耗时=%.2fs 有行情=%d/%d trade_days=%d",
            sector_code or "-",
            time.monotonic() - t0,
            len(results),
            len(stock_codes),
            len(trade_days),
        )
        return results

    def _calc_streak(self, bars: list[dict], default_limit_pct: float) -> int:
        streak = 0
        for row in reversed(bars):
            up_lim = row.get("up_limit")
            limit_pct = float(row.get("limit_pct", default_limit_pct))
            if up_lim is not None:
                if row["close"] >= up_lim * 0.998 - 1e-6:
                    streak += 1
                else:
                    break
            elif row["pct"] >= limit_pct:
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
        from app.services.scan_context import lookback_trade_days

        days = lookback_trade_days(trade_date, lookback)
        if not days:
            days = [trade_date]
        logger.info(
            "[流程] 从已缓存的全市场资金流表中筛选 %d 只成分股、近 %d 个交易日（%s ~ %s）主力净流入",
            len(stock_codes),
            len(days),
            days[0],
            days[-1],
        )
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
        logger.info(
            "[数据] get_capital_flows 完成 耗时=%.2fs stocks=%d days=%d",
            time.monotonic() - t0,
            len(stock_codes),
            len(days),
        )
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
        logger.info("[数据] get_index_bars code=%s %s~%s", code, start_date, end_date)
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
        logger.info("[数据] get_market_breadth date=%s", trade_date)
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
    TushareAdapter._trade_days_cache.clear()
    TushareAdapter._member_cache.clear()
    load_stock_name_map.cache_clear()
    reset_tushare_client()
