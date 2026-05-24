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
_TS_CALL_MAX_RETRIES = 2
_TS_CALL_RETRY_BASE_SECONDS = 1.5


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
        if plain:
            logger.debug("[流程] %s", plain)
        last_exc: Exception | None = None
        for attempt in range(1, _TS_CALL_MAX_RETRIES + 2):
            tushare_limiter.acquire_sync()
            pro = _ensure_pro()
            fn = getattr(pro, fn_name)
            logger.debug("[数据] Tushare %s 请求 %s attempt=%d", fn_name, kwargs, attempt)
            t0 = time.monotonic()
            try:
                df = fn(**kwargs)
                elapsed = time.monotonic() - t0
                if df is None:
                    logger.warning("[数据] Tushare %s 返回 None 耗时=%.2fs", fn_name, elapsed)
                    return pd.DataFrame()
                logger.info(
                    "[数据] Tushare %s API 完成 耗时=%.2fs rows=%d",
                    fn_name,
                    elapsed,
                    len(df),
                )
                if not df.empty and logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Tushare %s sample:\n%s", fn_name, df.head(2).to_string())
                return df
            except Exception as exc:
                last_exc = exc
                elapsed = time.monotonic() - t0
                msg = str(exc).lower()
                retryable = any(
                    key in msg
                    for key in (
                        "timed out",
                        "timeout",
                        "connection aborted",
                        "connection reset",
                        "max retries exceeded",
                        "temporary failure",
                    )
                )
                if retryable and attempt <= _TS_CALL_MAX_RETRIES:
                    sleep_s = _TS_CALL_RETRY_BASE_SECONDS * attempt
                    logger.warning(
                        "[数据] Tushare %s 网络异常（第 %d/%d 次）耗时=%.2fs: %s；%.1fs 后重试",
                        fn_name,
                        attempt,
                        _TS_CALL_MAX_RETRIES + 1,
                        elapsed,
                        exc,
                        sleep_s,
                    )
                    time.sleep(sleep_s)
                    continue
                if retryable:
                    logger.error(
                        "[数据] Tushare %s 连续网络异常，返回空结果并继续流程: %s",
                        fn_name,
                        exc,
                    )
                    return pd.DataFrame()
                raise
        if last_exc is not None:
            raise last_exc
        return pd.DataFrame()

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
        # 统一口径：按同花顺“概念板块(type=N)”作为默认板块池，避免行业/扩展类型混入导致数量异常膨胀。
        df = self._call("ths_index", exchange="A", type="N")
        if df is None or df.empty:
            # 网关兼容回退：缺少 type 参数时退化到 ths_index 全量。
            try:
                df = self._call("ths_index", exchange="A")
            except Exception:
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

    def get_concept_index_quote(self, concept_code: str, trade_date: date) -> dict[str, float] | None:
        """
        获取同花顺概念/行业板块指数在指定交易日的 OHLC 与涨跌幅（ths_daily）。

        若接口不可用/无权限/无数据，返回 None（上层应回退到“成分股聚合”口径）。
        """
        try:
            df = self._call(
                "ths_daily",
                plain=f"获取板块指数 {concept_code} 在 {trade_date} 的日线点位（ths_daily）",
                ts_code=concept_code,
                trade_date=_fmt(trade_date),
                fields="ts_code,trade_date,open,close,high,low,pre_close,pct_change,vol,amount",
            )
            if df is None or df.empty:
                # 部分网关不支持 vol/amount 字段，回退到基础字段确保 close/pct 可用。
                df = self._call(
                    "ths_daily",
                    plain=f"获取板块指数 {concept_code} 在 {trade_date} 的日线点位（ths_daily，基础字段回退）",
                    ts_code=concept_code,
                    trade_date=_fmt(trade_date),
                    fields="ts_code,trade_date,open,close,high,low,pre_close,pct_change",
                )
        except Exception as exc:
            logger.debug(
                "[数据] ths_daily 不可用 concept=%s date=%s: %s",
                concept_code,
                trade_date,
                exc,
            )
            return None
        if df is None or df.empty:
            return None
        row = df.iloc[-1]
        try:
            out = {
                "open": float(row.get("open", 0) or 0.0),
                "close": float(row.get("close", 0) or 0.0),
                "high": float(row.get("high", 0) or 0.0),
                "low": float(row.get("low", 0) or 0.0),
            }
            pct = row.get("pct_change", None)
            if pct is None or pd.isna(pct):
                pre = float(row.get("pre_close", out["close"]) or out["close"])
                out["pct_change"] = float((out["close"] / pre - 1) * 100.0) if pre else 0.0
            else:
                out["pct_change"] = float(pct)
            if out["close"] <= 0:
                return None
            return out
        except Exception as exc:
            logger.debug(
                "[数据] ths_daily 解析失败 concept=%s date=%s: %s",
                concept_code,
                trade_date,
                exc,
            )
            return None

    def get_concept_index_history(
        self, concept_code: str, start_date: date, end_date: date
    ) -> dict[date, dict[str, float]]:
        """
        获取同花顺板块指数在区间内的日线（ths_daily），返回 trade_date -> OHLC/pct_change。

        若接口不可用/无权限，返回空 dict（上层应回退到本地聚合口径）。
        """
        try:
            df = self._call(
                "ths_daily",
                plain=f"获取板块指数 {concept_code} 区间 {start_date}~{end_date} 日线点位（ths_daily）",
                ts_code=concept_code,
                start_date=_fmt(start_date),
                end_date=_fmt(end_date),
                fields="ts_code,trade_date,open,close,high,low,pre_close,pct_change,vol,amount",
            )
            if df is None or df.empty:
                # 网关字段不兼容时回退，避免历史序列全空。
                df = self._call(
                    "ths_daily",
                    plain=f"获取板块指数 {concept_code} 区间 {start_date}~{end_date} 日线点位（ths_daily，基础字段回退）",
                    ts_code=concept_code,
                    start_date=_fmt(start_date),
                    end_date=_fmt(end_date),
                    fields="ts_code,trade_date,open,close,high,low,pre_close,pct_change",
                )
        except Exception as exc:
            logger.debug(
                "[数据] ths_daily 区间不可用 concept=%s %s~%s: %s",
                concept_code,
                start_date,
                end_date,
                exc,
            )
            return {}
        if df is None or df.empty:
            return {}
        out: dict[date, dict[str, float]] = {}
        for _, row in df.iterrows():
            try:
                td = pd.Timestamp(str(row.get("trade_date"))).date()
            except Exception:
                continue
            try:
                item = {
                    "open": float(row.get("open", 0) or 0.0),
                    "close": float(row.get("close", 0) or 0.0),
                    "high": float(row.get("high", 0) or 0.0),
                    "low": float(row.get("low", 0) or 0.0),
                    "volume": float(row.get("vol", 0) or 0.0),
                    "money": float(row.get("amount", 0) or 0.0),
                }
                pct = row.get("pct_change", None)
                if pct is None or pd.isna(pct):
                    pre = float(row.get("pre_close", item["close"]) or item["close"])
                    item["pct_change"] = float((item["close"] / pre - 1) * 100.0) if pre else 0.0
                else:
                    item["pct_change"] = float(pct)
                if item["close"] > 0:
                    out[td] = item
            except Exception:
                continue
        return out

    def get_concept_stocks(self, concept_code: str, trade_date: date) -> list[str]:
        if concept_code in TushareAdapter._member_cache:
            cached = TushareAdapter._member_cache[concept_code]
            logger.info(
                "[数据] get_concept_stocks concept=%s 命中成分股缓存 count=%d",
                concept_code,
                len(cached),
            )
            return list(cached)

        def _infer_member_col(df: pd.DataFrame) -> str | None:
            """
            ths_member 字段在不同网关/版本下可能是 code / con_code / stock_code。
            必须避免误用概念 ts_code（通常形如 886033.TI），否则成分股全空导致板块指标为 0。
            """
            if df is None or df.empty:
                return None
            candidates = [c for c in ("con_code", "code", "stock_code") if c in df.columns]
            # ts_code 很可能是概念自身代码；只有在缺少其它列时才考虑
            if "ts_code" in df.columns:
                candidates.append("ts_code")
            best_col: str | None = None
            best_score = -1.0
            for col in candidates:
                raw_vals = [str(v).strip() for v in df[col].dropna().unique().tolist()]
                if not raw_vals:
                    continue
                sample = raw_vals[:20]
                # 概念列常见为常量概念码；直接跳过
                if len(set(sample)) == 1 and sample[0].upper() == str(concept_code).upper():
                    continue
                # 概念码后缀 .TI 出现占比过高，认为不是成分股列
                if sum(1 for v in sample if v.upper().endswith(".TI")) >= max(1, len(sample) // 2):
                    continue
                ok = 0
                for v in sample:
                    internal = normalize_stock_code(v)
                    ts = to_ts_code(internal)
                    if (
                        len(ts) == 9
                        and ts[:6].isdigit()
                        and ts[6] == "."
                        and ts[7:] in ("SZ", "SH", "BJ")
                    ):
                        ok += 1
                score = ok / max(len(sample), 1)
                if score > best_score:
                    best_score = score
                    best_col = col
            return best_col
        logger.info(
            "[流程] 拉取概念板块 %s 的成分股列表（ths_member，每板块仅请求一次）",
            concept_code,
        )
        code_candidates: list[str] = [str(concept_code)]
        raw = str(concept_code).strip()
        if raw.upper().endswith(".TI"):
            bare = raw.split(".")[0]
            if bare:
                code_candidates.append(bare)
        elif raw and "." not in raw:
            code_candidates.append(f"{raw}.TI")
        # 去重并保持顺序
        seen_codes: set[str] = set()
        code_candidates = [
            c for c in code_candidates if c and not (c in seen_codes or seen_codes.add(c))
        ]
        df = pd.DataFrame()
        try:
            for cc in code_candidates:
                df = self._call(
                    "ths_member",
                    plain=f"获取概念板块 {cc} 在 {trade_date} 的成分股代码（ths_member）",
                    ts_code=cc,
                    trade_date=_fmt(trade_date),
                )
                if df is None or df.empty:
                    df = self._call(
                        "ths_member",
                        plain=f"获取概念板块 {cc} 的全部成分股代码",
                        ts_code=cc,
                    )
                if df is not None and not df.empty:
                    if cc != concept_code:
                        logger.info(
                            "[数据] get_concept_stocks concept=%s 使用候选编码 %s 命中",
                            concept_code,
                            cc,
                        )
                    break
        except Exception as exc:
            logger.warning("[数据] get_concept_stocks 调用失败 concept=%s: %s", concept_code, exc)
            return []
        if df.empty:
            logger.warning("[数据] get_concept_stocks 无成分 concept=%s", concept_code)
            return []
        col = _infer_member_col(df) or ("code" if "code" in df.columns else None)
        if not col:
            logger.warning(
                "[数据] get_concept_stocks 未找到有效成分股字段 concept=%s columns=%s",
                concept_code,
                list(df.columns),
            )
            return []
        codes = [normalize_stock_code(str(c)) for c in df[col].dropna().unique()]
        # 兜底过滤：忽略明显的概念编码/异常值
        codes = [c for c in codes if c and not str(c).upper().endswith(".TI")]
        TushareAdapter._member_cache[concept_code] = codes
        logger.info(
            "[数据] get_concept_stocks concept=%s col=%s count=%d",
            concept_code,
            col,
            len(codes),
        )
        return codes

    def _load_market_table_from_disk(self, table: str, trade_date: date) -> pd.DataFrame | None:
        if not settings.market_cache_enabled:
            return None
        from app.services.market_cache import MarketTable, get_market_cache

        kind = MarketTable(table)
        return get_market_cache().load(kind, trade_date)

    def _save_market_table_to_disk(self, table: str, trade_date: date, df: pd.DataFrame) -> None:
        if not settings.market_cache_enabled:
            return
        from app.services.market_cache import MarketTable, get_market_cache

        store = get_market_cache()
        store.save(MarketTable(table), trade_date, df)
        if store.has_day(trade_date):
            store._register_day(trade_date)

    def _daily_market(self, trade_date: date) -> pd.DataFrame:
        key = _fmt(trade_date)
        if key in TushareAdapter._daily_cache:
            return TushareAdapter._daily_cache[key]
        disk = self._load_market_table_from_disk("daily", trade_date)
        if disk is not None:
            if not disk.empty:
                TushareAdapter._daily_cache[key] = disk
                return disk
            logger.warning("[数据] daily 磁盘缓存为空，触发实时重拉 trade_date=%s", trade_date)
        try:
            df = self._call(
                "daily",
                plain=f"拉取 {trade_date} 全市场约 5000 只股票日线行情（开高低收、成交额）",
                trade_date=key,
            )
        except Exception as exc:
            logger.warning("[数据] daily(%s) 失败: %s", key, exc)
            df = pd.DataFrame()
        TushareAdapter._daily_cache[key] = df
        self._save_market_table_to_disk("daily", trade_date, df)
        return df

    def _limit_table(self, trade_date: date) -> pd.DataFrame:
        key = _fmt(trade_date)
        if key in TushareAdapter._limit_cache:
            return TushareAdapter._limit_cache[key]
        disk = self._load_market_table_from_disk("limit", trade_date)
        if disk is not None:
            if not disk.empty:
                TushareAdapter._limit_cache[key] = disk
                return disk
            logger.warning("[数据] limit 磁盘缓存为空，触发实时重拉 trade_date=%s", trade_date)
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
        self._save_market_table_to_disk("limit", trade_date, df)
        return df

    def _moneyflow_market(self, trade_date: date) -> pd.DataFrame:
        key = _fmt(trade_date)
        if key in TushareAdapter._moneyflow_cache:
            return TushareAdapter._moneyflow_cache[key]
        disk = self._load_market_table_from_disk("moneyflow", trade_date)
        if disk is not None:
            if not disk.empty:
                TushareAdapter._moneyflow_cache[key] = disk
                return disk
            logger.warning(
                "[数据] moneyflow 磁盘缓存为空，触发实时重拉 trade_date=%s",
                trade_date,
            )
        try:
            df = self._call(
                "moneyflow_dc",
                plain=f"拉取 {trade_date} 全市场约 5000 只股票主力资金流向",
                trade_date=key,
            )
        except Exception as exc:
            logger.warning("[数据] moneyflow_dc(%s) 失败: %s", key, exc)
            df = pd.DataFrame()
        if df.empty:
            try:
                # 兼容部分账号/网关下 moneyflow_dc 无数据的情况，退化到 moneyflow。
                df = self._call(
                    "moneyflow",
                    plain=f"moneyflow_dc为空，回退拉取 {trade_date} moneyflow 主力资金流向",
                    trade_date=key,
                )
            except Exception as exc:
                logger.warning("[数据] moneyflow(%s) 失败: %s", key, exc)
                df = pd.DataFrame()
        TushareAdapter._moneyflow_cache[key] = df
        self._save_market_table_to_disk("moneyflow", trade_date, df)
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

        if settings.market_cache_enabled:
            from app.services.market_cache import get_market_cache

            stats = get_market_cache().ensure_days(self, need_days)
            api_calls = stats.get("api_calls", 0)
            skipped = stats.get("skipped", 0)
            fetched = stats.get("fetched", 0)
        else:
            api_calls = 0
            skipped = 0
            fetched = 0
            for td in need_days:
                key = _fmt(td)
                before = (
                    key not in TushareAdapter._daily_cache,
                    key not in TushareAdapter._limit_cache,
                    key not in TushareAdapter._moneyflow_cache,
                )
                daily_df = self._daily_market(td)
                limit_df = self._limit_table(td)
                money_df = self._moneyflow_market(td)
                logger.info(
                    "[数据] %s 三张表已加载 daily=%d limit=%d moneyflow=%d%s",
                    key,
                    len(daily_df),
                    len(limit_df),
                    len(money_df),
                    "（含API拉取）" if any(before) else "（内存/磁盘）",
                )
                if any(before):
                    api_calls += sum(before)
            fetched = len(need_days)

        logger.info(
            "[流程] 全市场公有数据预取完成 anchor=%s 交易日 %d 个（%s ~ %s）"
            " 跳过缓存 %d 日 新拉 %d 日 API约 %d 次",
            trade_date,
            len(need_days),
            need_days[0] if need_days else trade_date,
            need_days[-1] if need_days else trade_date,
            skipped,
            fetched,
            api_calls,
        )
        return {
            "trade_days": len(need_days),
            "api_calls": api_calls,
            "skipped": skipped,
            "fetched": fetched,
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
        logger.debug(
            "[数据] get_stock_quotes sector=%s stocks=%d lookback=%d date=%s",
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
            logger.debug(
                "[数据] get_stock_quotes %s 过滤 %d/%d 耗时=%.2fs",
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
            row = next((b for b in reversed(bars) if b["trade_date"] == trade_date), None)
            if row is None:
                continue
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
        logger.debug(
            "[数据] get_stock_quotes 完成 sector=%s 耗时=%.2fs 有行情=%d/%d",
            sector_code or "-",
            time.monotonic() - t0,
            len(results),
            len(stock_codes),
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
                    pre_close=pre,
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
        limit_up, _ = self.get_limit_counts(trade_date)
        return MarketBreadth(
            trade_date=trade_date,
            limit_up_count=limit_up,
            up_count=up,
            down_count=down,
            total_count=len(daily),
        )

    def get_limit_counts(self, trade_date: date) -> tuple[int, int]:
        """
        仅使用 Tushare《涨跌停列表（新）》统计真实涨停/跌停家数。
        返回 (up_limit_count, down_limit_count)。
        """
        def _extract_unique_codes(df: pd.DataFrame) -> set[str]:
            if df is None or df.empty:
                return set()
            if "ts_code" not in df.columns:
                return set()
            codes = (
                df["ts_code"]
                .astype(str)
                .str.strip()
                .str.upper()
            )
            return set(codes.tolist())

        td = _fmt(trade_date)

        def _count_from_price_limits() -> tuple[int, int] | None:
            """
            备用口径：daily 收盘价命中 stk_limit 涨跌停价。
            用于 limit_list_d 在代理网关下返回异常偏低时兜底。
            """
            try:
                daily = self._daily_market(trade_date)
                lim = self._limit_table(trade_date)
            except Exception as exc:
                logger.warning("[数据] 价格涨跌停兜底读取失败 trade_date=%s err=%s", td, exc)
                return None
            if daily is None or daily.empty or lim is None or lim.empty:
                return None
            if "ts_code" not in daily.columns or "ts_code" not in lim.columns:
                return None
            if "close" not in daily.columns or "up_limit" not in lim.columns or "down_limit" not in lim.columns:
                return None
            try:
                merged = daily[["ts_code", "close"]].merge(
                    lim[["ts_code", "up_limit", "down_limit"]],
                    on="ts_code",
                    how="inner",
                )
                if merged.empty:
                    return None
                close = pd.to_numeric(merged["close"], errors="coerce").round(2)
                up_lim = pd.to_numeric(merged["up_limit"], errors="coerce").round(2)
                down_lim = pd.to_numeric(merged["down_limit"], errors="coerce").round(2)
                up = int((close == up_lim).sum())
                down = int((close == down_lim).sum())
                return up, down
            except Exception as exc:
                logger.warning("[数据] 价格涨跌停兜底计算失败 trade_date=%s err=%s", td, exc)
                return None

        def _collect(limit_type: str) -> set[str]:
            try:
                df_all = self._call(
                    "limit_list_d",
                    trade_date=td,
                    limit_type=limit_type,
                    fields="ts_code,trade_date",
                )
                codes_all = _extract_unique_codes(df_all)
                raw_rows_all = 0 if df_all is None else int(len(df_all))
                logger.warning(
                    "[数据] limit_list_d type=%s trade_date=%s rows=%d uniq=%d",
                    limit_type,
                    td,
                    raw_rows_all,
                    len(codes_all),
                )
                return codes_all
            except Exception as exc:
                logger.warning(
                    "[数据] limit_list_d(%s) 失败 trade_date=%s err=%s",
                    limit_type,
                    td,
                    exc,
                )
            return set()

        up_codes = _collect("U")
        down_codes = _collect("D")
        list_up = len(up_codes)
        list_down = len(down_codes)
        logger.warning(
            "[数据] limit_list_d trade_date=%s final up=%d down=%d",
            td,
            list_up,
            list_down,
        )
        fallback = _count_from_price_limits()
        if fallback is None:
            return list_up, list_down
        price_up, price_down = fallback
        logger.warning(
            "[数据] limit_count_check trade_date=%s limit_list=(%d,%d) price_hit=(%d,%d)",
            td,
            list_up,
            list_down,
            price_up,
            price_down,
        )
        # 代理/镜像数据源下，limit_list_d 可能明显偏低；此时切换到价格命中口径。
        if (
            (price_up > 0 and list_up < int(price_up * 0.9))
            or (price_down > 0 and list_down < int(price_down * 0.9))
        ):
            logger.warning(
                "[数据] limit_list_d 偏低，改用 price_hit 口径 trade_date=%s up=%d down=%d",
                td,
                price_up,
                price_down,
            )
            return price_up, price_down
        return list_up, list_down


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
