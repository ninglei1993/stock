"""仪表盘（Dashboard）专用服务层。

与扫盘（scan）逻辑完全解耦：
- 默认 trade_date 基于 trade_calendar.latest_completed_trade_day()，而非扫描入库数据
- 仅加载 market_overview + indices，不依赖板块扫描结果
- 使用 asyncio.gather 并行加载以提升首屏速度
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any, Optional

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.factory import get_adapter
from app.services.trade_calendar import latest_completed_trade_day

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Trade date resolution
# ---------------------------------------------------------------------------

def resolve_dashboard_trade_date(requested: Optional[date] = None) -> Optional[date]:
    """
    仪表盘使用的交易日。

    - 未传日期：取最近已收盘交易日（不依赖扫描入库数据）
    - 传了日期：截断到最近已收盘交易日
    """
    try:
        completed = latest_completed_trade_day()
    except Exception:
        completed = None

    if requested is None:
        return completed

    if completed is not None and requested > completed:
        return completed
    return requested


# ---------------------------------------------------------------------------
# Market overview (涨跌分布 / 成交额 / 涨跌家数)
# ---------------------------------------------------------------------------

def _is_a_share_code(ts_code: str) -> bool:
    c = str(ts_code or "").strip().upper()
    if len(c) < 3 or "." not in c:
        return False
    num, suffix = c.split(".", 1)
    if suffix == "SH":
        return num.startswith("6")
    if suffix == "SZ":
        return num.startswith(("0", "3"))
    if suffix == "BJ":
        return True
    return False


def _apply_a_share_filter(src: pd.DataFrame) -> pd.DataFrame:
    if src is None or src.empty:
        return src
    if "ts_code" not in src.columns:
        return src
    mask = src["ts_code"].astype(str).map(_is_a_share_code)
    return src[mask].copy()


def build_market_overview(anchor: date, limit_up_count_hint: int = 0) -> Optional[dict[str, Any]]:
    """
    构建市场总览 dict（对应前端的 market_overview）。

    优先读 market_cache，回退到 adapter 实时拉取。
    """
    from app.services.market_cache import MarketTable, get_market_cache

    store = get_market_cache()
    adapter = None

    # --- Load daily bars ---
    try:
        df = store.load(MarketTable.DAILY, anchor)
    except Exception:
        df = None
    if df is None or df.empty:
        try:
            adapter = get_adapter()
            if hasattr(adapter, "_daily_market"):
                df = adapter._daily_market(anchor)  # type: ignore[attr-defined]
        except Exception:
            df = None
    if df is None or df.empty:
        return None
    if not {"close", "pre_close", "amount"}.issubset(set(df.columns)):
        return None

    df = _apply_a_share_filter(df)
    if df.empty:
        return None

    pre = pd.to_numeric(df["pre_close"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")
    pct = ((close / pre) - 1.0) * 100.0
    pct = pct.where(pre > 0).fillna(0.0)
    amount = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)

    up_count = int((pct > 0).sum())
    down_count = int((pct < 0).sum())
    flat_count = int((pct == 0).sum())

    # --- Limit-up / limit-down detection ---
    up_limit_flag = pd.Series(False, index=df.index)
    down_limit_flag = pd.Series(False, index=df.index)
    try:
        lim_df = store.load(MarketTable.LIMIT, anchor)
    except Exception:
        lim_df = None
    if (lim_df is None or lim_df.empty) and adapter is None:
        try:
            adapter = get_adapter()
        except Exception:
            adapter = None
    if (lim_df is None or lim_df.empty) and adapter is not None:
        try:
            if hasattr(adapter, "_limit_table"):
                lim_df = adapter._limit_table(anchor)  # type: ignore[attr-defined]
        except Exception:
            lim_df = None

    if (
        lim_df is not None
        and not lim_df.empty
        and {"ts_code", "up_limit", "down_limit"}.issubset(set(lim_df.columns))
    ):
        lim_sub = _apply_a_share_filter(lim_df)[["ts_code", "up_limit", "down_limit"]].copy()
        if "ts_code" in df.columns and not lim_sub.empty:
            merged = df[["ts_code"]].merge(lim_sub, on="ts_code", how="left")
            up_lim = pd.to_numeric(merged["up_limit"], errors="coerce").round(2)
            down_lim = pd.to_numeric(merged["down_limit"], errors="coerce").round(2)
            close_round = close.round(2)
            up_limit_flag = (close_round == up_lim) & up_lim.notna()
            down_limit_flag = (close_round == down_lim) & down_lim.notna()

    up_limit_count = int(up_limit_flag.sum())
    down_limit_count = int(down_limit_flag.sum())
    if up_limit_count == 0 and down_limit_count == 0:
        try:
            adapter = adapter or get_adapter()
            real_up, real_down = adapter.get_limit_counts(anchor)  # type: ignore[attr-defined]
            up_limit_count = int(real_up or 0)
            down_limit_count = int(real_down or 0)
        except Exception:
            pass

    # --- Turnover delta vs previous trading day ---
    turnover_delta = 0.0
    try:
        days = [d for d in store.list_trade_days() if d < anchor]
        prev_day = days[-1] if days else None
        prev_df = None
        if prev_day is None:
            for i in range(1, 15):
                cand = anchor - timedelta(days=i)
                try:
                    cand_df = store.load(MarketTable.DAILY, cand)
                except Exception:
                    cand_df = None
                if cand_df is not None and not cand_df.empty:
                    prev_day = cand
                    prev_df = cand_df
                    break
        if prev_day is None:
            try:
                adapter = adapter or get_adapter()
                history_days = adapter.get_trade_days(anchor - timedelta(days=20), anchor)
                prior_days = [d for d in history_days if d < anchor]
                prev_day = prior_days[-1] if prior_days else None
            except Exception:
                prev_day = None

        if prev_day is not None:
            if prev_df is None:
                prev_df = store.load(MarketTable.DAILY, prev_day)
            if prev_df is None or prev_df.empty:
                try:
                    adapter = adapter or get_adapter()
                    if hasattr(adapter, "_daily_market"):
                        prev_df = adapter._daily_market(prev_day)  # type: ignore[attr-defined]
                except Exception:
                    prev_df = None
            if prev_df is not None and not prev_df.empty and "amount" in prev_df.columns:
                prev_df = _apply_a_share_filter(prev_df)
                prev_amount = pd.to_numeric(prev_df["amount"], errors="coerce").fillna(0.0)
                turnover_delta = round(float((amount.sum() - prev_amount.sum()) / 1e5), 2)
    except Exception:
        pass

    return {
        "total_turnover_yi": round(float(amount.sum()) / 1e5, 2),
        "turnover_delta_yi": turnover_delta,
        "up_count": up_count,
        "down_count": down_count,
        "flat_count": flat_count,
        "limit_up_count": up_limit_count,
        "distribution": {
            "down_limit": down_limit_count,
            "neg_7_plus": int(((pct <= -7) & (~down_limit_flag)).sum()),
            "neg_7_5": int(((pct > -7) & (pct <= -5) & (~down_limit_flag)).sum()),
            "neg_5_3": int(((pct > -5) & (pct <= -3) & (~down_limit_flag)).sum()),
            "neg_3_0": int(((pct > -3) & (pct < 0) & (~down_limit_flag)).sum()),
            "flat": flat_count,
            "pos_0_3": int(((pct > 0) & (pct < 3) & (~up_limit_flag)).sum()),
            "pos_3_5": int(((pct >= 3) & (pct < 5) & (~up_limit_flag)).sum()),
            "pos_5_7": int(((pct >= 5) & (pct < 7) & (~up_limit_flag)).sum()),
            "pos_7_plus": int(((pct >= 7) & (~up_limit_flag)).sum()),
            "up_limit": up_limit_count,
        },
    }


# ---------------------------------------------------------------------------
# Index summaries (上证 / 深证 / 沪深300)
# ---------------------------------------------------------------------------

def fetch_index_summaries(td: date) -> list[dict[str, Any]]:
    """获取三大指数当日收盘摘要。"""
    codes = [
        ("000001.SH", "上证指数"),
        ("399001.SZ", "深证成指"),
        ("000300.SH", "沪深300"),
    ]
    out: list[dict[str, Any]] = []
    start = td - timedelta(days=40)
    try:
        adapter = get_adapter()
    except Exception:
        return out

    for code, name in codes:
        try:
            bars = adapter.get_index_bars(code, start, td)
        except Exception:
            continue
        bars = sorted([b for b in bars if b.trade_date <= td], key=lambda x: x.trade_date)
        if not bars:
            continue
        today = bars[-1]
        prev_close = float(getattr(today, "pre_close", 0.0) or 0.0)
        if prev_close <= 0 and len(bars) >= 2:
            prev_close = float(bars[-2].close or 0.0)
        if prev_close <= 0:
            prev_close = (
                today.close / (1.0 + (today.pct_change / 100.0))
                if abs(today.pct_change) > 1e-9
                else today.close
            )
        out.append({
            "code": code,
            "name": name,
            "close": round(today.close, 2),
            "pre_close": round(prev_close, 2),
            "pct_change": round(today.pct_change, 2),
            "point_change": round(today.close - prev_close, 2),
        })
    return out


# ---------------------------------------------------------------------------
# Main entry: build dashboard response (parallel)
# ---------------------------------------------------------------------------

async def build_dashboard_response(trade_date: Optional[date] = None) -> dict[str, Any]:
    """
    构建仪表盘完整响应。

    market_overview 与 indices 并行加载，top_sectors 固定为空（已移除）。
    """
    td = resolve_dashboard_trade_date(trade_date)
    if not td:
        return {
            "trade_date": None,
            "market_env": None,
            "top_sectors": [],
            "market_overview": None,
            "indices": [],
        }

    # Run blocking I/O in thread pool, in parallel
    loop = asyncio.get_running_loop()

    overview_task = loop.run_in_executor(None, build_market_overview, td, 0)
    indices_task = loop.run_in_executor(None, fetch_index_summaries, td)

    overview, indices = await asyncio.gather(overview_task, indices_task)

    return {
        "trade_date": td,
        "market_env": None,  # env 依赖扫描数据，已移除
        "top_sectors": [],   # 主线板块已移除
        "market_overview": overview,
        "indices": indices or [],
    }


# ---------------------------------------------------------------------------
# Limit stocks (涨停 / 跌停明细)
# ---------------------------------------------------------------------------

def build_limit_stocks(
    side: str, trade_date: Optional[date] = None
) -> dict[str, Any]:
    """构建涨跌停明细响应。"""
    from app.services.market_cache import MarketTable, get_market_cache

    td = resolve_dashboard_trade_date(trade_date)
    empty = {"trade_date": td, "side": side, "total": 0, "items": []}
    if not td:
        return empty

    store = get_market_cache()
    adapter = None

    try:
        daily = store.load(MarketTable.DAILY, td)
    except Exception:
        daily = None
    if daily is None or daily.empty:
        try:
            adapter = get_adapter()
            if hasattr(adapter, "_daily_market"):
                daily = adapter._daily_market(td)  # type: ignore[attr-defined]
        except Exception:
            daily = None

    try:
        limit_df = store.load(MarketTable.LIMIT, td)
    except Exception:
        limit_df = None
    if (limit_df is None or limit_df.empty) and adapter is None:
        try:
            adapter = get_adapter()
        except Exception:
            adapter = None
    if (limit_df is None or limit_df.empty) and adapter is not None:
        try:
            if hasattr(adapter, "_limit_table"):
                limit_df = adapter._limit_table(td)  # type: ignore[attr-defined]
        except Exception:
            limit_df = None

    required_daily_cols = {"ts_code", "close", "pre_close"}
    required_limit_cols = {"ts_code", "up_limit", "down_limit"}
    if (
        daily is None
        or daily.empty
        or limit_df is None
        or limit_df.empty
        or not required_daily_cols.issubset(set(daily.columns))
        or not required_limit_cols.issubset(set(limit_df.columns))
    ):
        return empty

    daily = daily[daily["ts_code"].astype(str).map(_is_a_share_code)].copy()
    limit_df = limit_df[limit_df["ts_code"].astype(str).map(_is_a_share_code)].copy()
    daily_cols = ["ts_code", "close", "pre_close"]
    if "name" in daily.columns:
        daily_cols.append("name")
    merged = daily[daily_cols].merge(
        limit_df[["ts_code", "up_limit", "down_limit"]],
        on="ts_code",
        how="inner",
    )
    if merged.empty:
        return empty

    close = pd.to_numeric(merged["close"], errors="coerce").round(2)
    up_limit = pd.to_numeric(merged["up_limit"], errors="coerce").round(2)
    down_limit = pd.to_numeric(merged["down_limit"], errors="coerce").round(2)
    pre_close = pd.to_numeric(merged["pre_close"], errors="coerce")
    pct_change = (((close / pre_close) - 1.0) * 100.0).where(pre_close > 0).fillna(0.0)

    if side == "up":
        mask = (close == up_limit) & up_limit.notna()
        limit_price = up_limit
    else:
        mask = (close == down_limit) & down_limit.notna()
        limit_price = down_limit

    rows = merged.loc[mask].copy()
    if rows.empty:
        return empty

    stock_name_map: dict[str, str] = {}
    if "name" in rows.columns:
        stock_name_map = dict(zip(rows["ts_code"].astype(str), rows["name"].astype(str)))

    from app.adapters.tushare_codes import to_internal_code

    items = []
    for _, row in rows.iterrows():
        ts_code = str(row["ts_code"])
        code = to_internal_code(ts_code)
        items.append({
            "stock_code": code,
            "stock_name": stock_name_map.get(ts_code, code),
            "close": float(close.loc[row.name]),
            "limit_price": float(limit_price.loc[row.name]),
            "pct_change": round(float(pct_change.loc[row.name]), 2),
        })
    items.sort(key=lambda x: abs(x["pct_change"]), reverse=True)

    return {
        "trade_date": td,
        "side": side,
        "total": len(items),
        "items": items,
    }
