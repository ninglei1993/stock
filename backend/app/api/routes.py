import asyncio
from datetime import date, timedelta
import time
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
import pandas as pd
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.models.tables import (
    Alert,
    BacktestEquityDaily,
    BacktestMetric,
    BacktestRun,
    BacktestTrade,
    MarketEnvDaily,
    SectorDaily,
    SectorFlowDaily,
    SectorScoreDaily,
    StockDaily,
    ThemeLeaderDaily,
)
from app.adapters.factory import adapter_info, get_adapter
from app.adapters.tushare_codes import to_internal_code
from app.config import settings
from app.api.backtest_helpers import trade_to_out
from app.labels import BACKTEST_TRADE_NOTE, STRATEGY_LABELS
from app.schemas.common import (
    AStrategyListOut,
    AStrategyManualInputIn,
    AStrategyManualInputOut,
    AlertOut,
    BacktestCreate,
    BacktestReport,
    BacktestRunOut,
    BacktestSectorCandidateOut,
    BacktestSectorCandidatesOut,
    BacktestTradeOut,
    DashboardOut,
    EquityPointOut,
    FlowDayOut,
    LimitStockListOut,
    MarketEnvOut,
    ReviewDayOut,
    SectorDetailOut,
    ConceptOut,
    SectorListOut,
    SectorScoreOut,
    StockInSector,
    SystemStatusOut,
    TaskStatusOut,
    SetIngestSettingsIn,
    ScanSectorsOut,
    SetScanSectorsIn,
    TusharePingOut,
)
from app.services.trade_calendar import (
    clamp_backtest_range,
    latest_completed_trade_day,
    resolve_scan_date,
    resolve_scan_trade_days,
    ui_default_scan_date,
    ui_default_scan_range,
)
from app.services.task_status import (
    cancel_scan,
    clear_cancel_flag,
    fail_scan,
    finish_scan,
    get_scan_task,
    is_cancel_requested,
    request_cancel_scan,
    start_scan,
    update_scan_progress,
)
from app.services.stock_names import clear_name_cache, resolve_stock_name
from app.services.backtest_engine import BacktestEngine
from app.services.ingestion import IngestionService
from app.services.scan_service import ScanService
from app.services.a_strategy_manual_store import (
    delete_manual_input,
    get_manual_input,
    get_manual_inputs_for_day,
    upsert_manual_input,
)

router = APIRouter(prefix="/api")


def _classify_tushare_error(msg: str) -> str:
    m = (msg or "").lower()
    if "token" in m and ("不对" in msg or "错误" in msg or "invalid" in m):
        return "token_invalid"
    if any(k in msg for k in ("访问频次", "频次", "超过限制", "每分钟", "流控", "限流")) or "rate" in m:
        return "rate_limited"
    if any(k in m for k in ("timed out", "timeout", "connection", "dns", "refused", "reset")):
        return "network"
    return "unknown"


@router.get("/system/tushare/ping", response_model=TusharePingOut)
async def tushare_ping():
    """
    诊断 Tushare 连接（用于区分 token 无效 / 限流 / 网络/代理异常）。
    通过一次轻量的 trade_cal 调用判断可用性；不会泄漏 token。
    """
    if not settings.tushare_configured():
        return TusharePingOut(
            ok=False,
            tushare_configured=False,
            adapter=adapter_info().get("adapter", ""),
            error_type="not_configured",
            error_message="TUSHARE_TOKEN 未配置或为占位值",
        )
    try:
        adapter = get_adapter()
    except Exception as exc:
        msg = str(exc)
        return TusharePingOut(
            ok=False,
            tushare_configured=True,
            adapter=adapter_info().get("adapter", "TushareAdapter"),
            endpoint="",
            error_type=_classify_tushare_error(msg),
            error_message=msg,
        )
    endpoint = ""
    try:
        from app.adapters.tushare_adapter import _ensure_pro  # type: ignore

        pro = _ensure_pro()
        endpoint = str(getattr(pro, "_DataApi__http_url", "") or "")
    except Exception:
        endpoint = ""

    t0 = time.monotonic()
    try:
        # 取近 7 天，trade_cal 是最轻量且最常用的“验 token”接口之一
        end = date.today()
        start = end - timedelta(days=7)
        df = getattr(adapter, "_call")(
            "trade_cal",
            exchange="SSE",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            is_open="1",
            fields="cal_date,is_open",
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        rows = 0 if df is None else int(getattr(df, "shape", [0])[0] or 0)
        return TusharePingOut(
            ok=True,
            tushare_configured=True,
            adapter=adapter.__class__.__name__,
            endpoint=endpoint,
            latency_ms=latency_ms,
            sample_rows=rows,
        )
    except Exception as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        msg = str(exc)
        return TusharePingOut(
            ok=False,
            tushare_configured=True,
            adapter=adapter.__class__.__name__,
            endpoint=endpoint,
            latency_ms=latency_ms,
            error_type=_classify_tushare_error(msg),
            error_message=msg,
        )

_PCT_HISTORY_LIMIT = 10


def _pct_display_days(
    anchor: date, scan_days: Optional[list[date]] = None, limit: int = _PCT_HISTORY_LIMIT
) -> list[date]:
    if scan_days:
        prior = sorted(d for d in scan_days if d <= anchor)
        return prior[-limit:] if prior else [anchor]
    return [anchor]


def _build_stocks_in_sector(
    sector_code: str,
    trade_date: date,
    rows: list,
    display_days: list[date],
    *,
    limit: int = 30,
) -> list:
    from app.schemas.common import StockInSector, StockPctDayOut

    def _get(obj, key, default=None):
        """Support both attribute access and dict-style get."""
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def _get_date(obj, key):
        """Get a date field, parsing ISO strings if needed."""
        val = _get(obj, key)
        if isinstance(val, date):
            return val
        if isinstance(val, str):
            try:
                return date.fromisoformat(val[:10])
            except (ValueError, TypeError):
                return None
        return None

    by_key: dict[tuple[str, date], Any] = {}
    for r in rows:
        if _get(r, "sector_code") != sector_code:
            continue
        sc = _get(r, "stock_code", "")
        td_val = _get_date(r, "trade_date")
        if td_val is None:
            continue
        by_key[(sc, td_val)] = r

    anchor_rows = [r for (code, d), r in by_key.items() if d == trade_date]
    anchor_rows.sort(key=lambda r: float(_get(r, "pct_change", 0) or 0), reverse=True)

    out: list[StockInSector] = []
    # limit=0 约定为"展示全部"
    target_rows = anchor_rows if limit <= 0 else anchor_rows[:limit]
    for s in target_rows:
        sc = _get(s, "stock_code", "")
        hist = [
            StockPctDayOut(trade_date=d, pct_change=float(_get(by_key.get((sc, d)), "pct_change", 0) or 0))
            for d in display_days
            if (sc, d) in by_key
        ]
        out.append(
            StockInSector(
                stock_code=sc,
                stock_name=_get(s, "stock_name") or resolve_stock_name(sc),
                pct_change=float(_get(s, "pct_change", 0) or 0),
                pct_trade_date=trade_date,
                is_limit_up=bool(_get(s, "is_limit_up", False)),
                limit_up_streak=int(_get(s, "limit_up_streak", 0) or 0),
                money=float(_get(s, "money", 0) or 0),
                pct_history=hist,
            )
        )
    return out


def _backfill_pct_history(
    stocks: list[StockInSector], display_days: list[date], *, anchor: date
) -> list[StockInSector]:
    """
    针对 TopN 行中缺失的日期，按“指定交易日 + 指定股票”回填涨跌幅。
    只补缺口，不改动已有入库值。
    """
    if not stocks or not display_days:
        return stocks
    adapter = get_adapter()
    try:
        from app.schemas.common import StockPctDayOut
    except Exception:
        return stocks

    for td in display_days:
        need_codes: list[str] = []
        for s in stocks:
            existed = {p.trade_date for p in s.pct_history}
            if td not in existed:
                need_codes.append(s.stock_code)
        if not need_codes:
            continue
        try:
            day_quotes = adapter.get_stock_quotes(
                need_codes,
                td,
                sector_code="",
                price_lookback_days=1,
                skip_flows=True,
            )
        except Exception:
            continue
        qmap = {q.stock_code: q for q in day_quotes}
        for s in stocks:
            if s.stock_code not in qmap:
                continue
            if td not in {p.trade_date for p in s.pct_history}:
                s.pct_history.append(
                    StockPctDayOut(trade_date=td, pct_change=qmap[s.stock_code].pct_change)
                )
            if td == anchor:
                # 锚点日采用当日实时行情重新校验，避免误判涨停/连板/成交额
                q = qmap[s.stock_code]
                s.pct_change = q.pct_change
                s.is_limit_up = q.is_limit_up
                s.limit_up_streak = q.limit_up_streak
                s.money = q.money

    for s in stocks:
        s.pct_history = sorted(s.pct_history, key=lambda x: x.trade_date)
    return stocks


def _build_stocks_on_demand(
    sector_code: str,
    trade_date: date,
    display_days: list[date],
    *,
    limit: int = 30,
) -> list[StockInSector]:
    """从全市场行情缓存 + 成分股列表现场聚合（不持久化 stock_daily）。"""
    from app.schemas.common import StockInSector, StockPctDayOut
    from app.services.ingest_settings_store import effective_max_stocks_per_concept
    from app.services.stock_select import limit_stocks_for_ingest

    adapter = get_adapter()
    try:
        members = adapter.get_concept_stocks(sector_code, trade_date)
    except Exception:
        return []
    max_stocks = effective_max_stocks_per_concept()
    if max_stocks > 0 and members:
        members = limit_stocks_for_ingest(adapter, members, trade_date, max_stocks)
    if not members:
        return []
    try:
        quotes = adapter.get_stock_quotes(
            members,
            trade_date,
            sector_code,
            price_lookback_days=max(len(display_days), 1),
            skip_flows=True,
        )
    except Exception:
        return []
    quotes = sorted(quotes, key=lambda q: q.pct_change, reverse=True)
    if limit > 0:
        quotes = quotes[:limit]
    out: list[StockInSector] = []
    for q in quotes:
        out.append(
            StockInSector(
                stock_code=q.stock_code,
                stock_name=resolve_stock_name(q.stock_code),
                pct_change=q.pct_change,
                pct_trade_date=trade_date,
                is_limit_up=q.is_limit_up,
                limit_up_streak=q.limit_up_streak,
                money=q.money,
                pct_history=[
                    StockPctDayOut(trade_date=trade_date, pct_change=q.pct_change)
                ],
            )
        )
    return _backfill_pct_history(out, display_days, anchor=trade_date)


def _resolve_dashboard_snapshot():
    from app.services.latest_scan_store import LatestScanStore
    from app.services.storage_mode import uses_file_scan_storage
    from app.services.volatile_scan import (
        VolatileDashboardSnapshot,
        get_dashboard_snapshot,
        set_dashboard_snapshot,
    )

    snap = get_dashboard_snapshot()
    if snap is not None:
        # 快照 trade_date 为 epoch（如 1970-01-01）时视为无效，清除后重建
        if snap.trade_date < date(1970, 1, 3):
            import logging
            logging.getLogger(__name__).warning(
                "[数据] 内存快照 trade_date=%s 为 epoch，已清除", snap.trade_date
            )
            set_dashboard_snapshot(None)
            snap = None
        else:
            return snap
    if not uses_file_scan_storage():
        return None
    loaded = LatestScanStore.load()
    if not loaded:
        return None
    # load() 已做 epoch 修正，但再保险一次
    if loaded.trade_date < date(1970, 1, 3):
        return None
    snap = VolatileDashboardSnapshot(
        trade_date=loaded.trade_date,
        env=loaded.market_env,
        scores=loaded.scores,
        leader_map=loaded.leader_map,
        scan_trade_days=loaded.trade_days,
        sector_dailies=loaded.sector_dailies,
        sector_flows=loaded.sector_flows,
    )
    set_dashboard_snapshot(snap)
    return snap


async def _latest_trade_date(session: AsyncSession) -> Optional[date]:
    row_db = (
        await session.execute(
            select(SectorScoreDaily.trade_date).order_by(desc(SectorScoreDaily.trade_date)).limit(1)
        )
    ).scalar_one_or_none()
    try:
        completed = latest_completed_trade_day()
    except Exception:
        completed = None
    if row_db is not None and completed is not None:
        if row_db > completed:
            return completed
        return row_db
    if row_db is not None:
        return row_db
    # DB 为空时回退到内存快照的交易日
    snap = _resolve_dashboard_snapshot()
    if snap and snap.trade_date and snap.trade_date >= date(2020, 1, 1):
        return snap.trade_date
    return completed


def _normalize_requested_trade_date(trade_date: Optional[date]) -> Optional[date]:
    if trade_date is None:
        return None
    completed = latest_completed_trade_day()
    return trade_date if trade_date <= completed else completed


def _sector_score_out(
    s, leader, *, pct_change: Optional[float] = None, include_rules: bool = True
) -> SectorScoreOut:
    reasons_raw = getattr(s, "rule_fail_reasons", None)
    if isinstance(reasons_raw, str):
        rule_fail_reasons = [x for x in reasons_raw.split("；") if x]
    elif isinstance(reasons_raw, list):
        rule_fail_reasons = reasons_raw
    else:
        rule_fail_reasons = []
    compact_rules: list[dict] = []
    if include_rules:
        raw_rules = list(getattr(s, "rules_json", []) or [])
        # 列表页仅展示规则“通过与否”摘要，避免把大块调试字段透传导致响应过大。
        for r in raw_rules:
            if isinstance(r, dict):
                compact_rules.append(
                    {
                        "key": r.get("key"),
                        "label": r.get("label"),
                        "passed": bool(r.get("passed", False)),
                        "threshold": r.get("threshold"),
                    }
                )
            else:
                compact_rules.append({"label": str(r), "passed": False})
    return SectorScoreOut(
        sector_code=s.sector_code,
        sector_name=s.sector_name,
        total_score=s.total_score,
        stage=s.stage,
        rank=s.rank,
        persistence_score=s.persistence_score,
        capital_score=s.capital_score,
        breadth_score=s.breadth_score,
        leader_score=s.leader_score,
        relative_score=s.relative_score,
        position_hint=s.position_hint,
        leader_stock=leader.stock_code if leader else None,
        # 列表接口不做名称兜底远程拉取，避免首次请求触发全市场名称加载而阻塞仪表盘。
        leader_stock_name=((leader.stock_name or "") if leader else None),
        leader_streak=leader.limit_up_streak if leader else None,
        pct_change=pct_change,
        is_main_line=bool(getattr(s, "is_main_line", False)),
        main_line_tier=str(getattr(s, "main_line_tier", "rotation") or "rotation"),
        confirm_state=str(getattr(s, "confirm_state", "pending") or "pending"),
        exit_state=str(getattr(s, "exit_state", "normal") or "normal"),
        source_tag=str(getattr(s, "source_tag", "auto") or "auto"),
        rules=compact_rules,
        rule_fail_reasons=rule_fail_reasons,
    )


def _build_data_missing_items(
    daily_row: Any | None,
    flow_row: Any | None,
    stocks: list[Any],
) -> list[str]:
    missing: list[str] = []
    if daily_row is None:
        total_count = 0
    elif isinstance(daily_row, dict):
        total_count = int(daily_row.get("total_count", 0) or 0)
    else:
        total_count = int(getattr(daily_row, "total_count", 0) or 0)
    if total_count <= 0 or not stocks:
        missing.append("成分股涨跌幅未获取（当日板块成分行情为空）")
        missing.append("涨停家数未获取（依赖成分股行情）")
        missing.append("炸板率未获取（依赖成分股行情）")
        missing.append("上涨占比未获取（依赖成分股行情）")
        missing.append("主力流入资金未获取（成分股行情缺失导致资金聚合不可用）")
    elif flow_row is None:
        missing.append("主力流入资金未获取（板块资金流为空）")
    return missing


@router.get("/health")
async def health():
    info = adapter_info()
    return {"status": "ok", "product": "ThemeRadar", **info}


@router.post("/system/reload-config")
async def reload_config():
    """修改 .env 后调用，重新加载配置与概念缓存（无需整容器重启）。"""
    import importlib

    import app.adapters.factory as factory_mod
    import app.config as config_mod
    from app.services.concept_cache import clear_concept_cache, get_cached_concepts
    from app.services.trade_calendar import clear_trade_days_cache

    importlib.reload(config_mod)
    importlib.reload(factory_mod)
    _reset_data_source_runtime()
    adapter = factory_mod.get_adapter()
    concepts, _ = get_cached_concepts(force_refresh=True)
    info = adapter_info()
    return {
        "message": "配置已重新加载",
        "adapter": adapter.__class__.__name__,
        "concepts": len(concepts),
        **info,
    }


def _reset_data_source_runtime() -> None:
    import app.adapters.factory as factory_mod

    from app.adapters.tushare_adapter import clear_tushare_caches
    from app.services.concept_cache import clear_concept_cache
    from app.services.stock_names import clear_name_cache
    from app.services.trade_calendar import clear_trade_days_cache

    factory_mod.reset_adapter()
    clear_concept_cache()
    clear_trade_days_cache()
    clear_name_cache()
    clear_tushare_caches()


@router.get("/system/status", response_model=SystemStatusOut)
async def system_status():
    from app.services.concept_select import resolve_scan_scope_label
    from app.services.ingest_settings_store import (
        effective_max_stocks_per_concept,
        read_scan_sectors_selection,
    )

    info = adapter_info()
    scan = get_scan_task()
    use_explicit, selected = read_scan_sectors_selection()
    return SystemStatusOut(
        adapter=info["adapter"],
        is_live_data=info.get("is_live_data", False),
        data_source_label=info.get("data_source_label", ""),
        data_source_short=info.get("data_source_short", ""),
        tushare_configured=info.get("tushare_configured", settings.tushare_configured()),
        universe_total=info["universe_total"],
        ingest_max_concepts=settings.ingest_max_concepts,
        ingest_concept_filter=settings.ingest_concept_filter,
        scan_scope_label=resolve_scan_scope_label(),
        ingest_max_stocks_per_concept=effective_max_stocks_per_concept(),
        use_explicit_sector_selection=use_explicit,
        selected_sector_count=len(selected),
        scan_volatile_storage=settings.scan_volatile_storage or settings.market_cache_enabled,
        scan_task=TaskStatusOut(**scan.to_dict()),
        default_scan_date=ui_default_scan_date(),
        default_scan_start=ui_default_scan_range()[0],
        default_scan_end=ui_default_scan_range()[1],
    )


@router.get("/system/scan-sectors", response_model=ScanSectorsOut)
async def get_scan_sectors():
    from app.services.concept_cache import get_cached_concepts
    from app.services.ingest_settings_store import read_scan_sectors_selection

    use_explicit, selected = read_scan_sectors_selection()
    concepts, _ = get_cached_concepts()
    universe = [
        ConceptOut(sector_code=c.code, sector_name=c.name) for c in concepts
    ]
    return ScanSectorsOut(
        use_explicit_selection=use_explicit,
        selected_codes=selected,
        universe=universe,
    )


@router.post("/system/scan-sectors")
async def set_scan_sectors(body: SetScanSectorsIn):
    from app.services.ingest_settings_store import write_scan_sectors_selection

    write_scan_sectors_selection(
        use_explicit_selection=body.use_explicit_selection,
        selected_codes=body.selected_codes,
    )
    return {
        "message": "扫描板块选择已保存",
        "use_explicit_selection": body.use_explicit_selection,
        "selected_count": len(body.selected_codes),
    }


@router.get("/system/scan-history")
async def get_scan_history():
    from app.services.ingest_settings_store import read_scan_history

    return {"history": read_scan_history()}


@router.post("/system/scan-history")
async def save_scan_history(body: dict):
    from app.services.ingest_settings_store import append_scan_history

    label = str(body.get("label", "")).strip() or "未命名"
    codes = body.get("codes", [])
    if not isinstance(codes, list) or not codes:
        raise HTTPException(400, "codes 不能为空")
    append_scan_history(label, codes)
    return {"message": "已保存历史勾选", "label": label, "count": len(codes)}


@router.post("/system/clear-data")
async def clear_all_data(db: AsyncSession = Depends(get_db)):
    """清空缓存、内存快照与库内扫描/演示数据。"""
    from app.services.data_reset import (
        clear_runtime_caches,
        clear_scan_database,
    )
    clear_runtime_caches()
    counts = await clear_scan_database(db)
    _reset_data_source_runtime()
    return {
        "message": "已清空缓存、扫描数据、本地 JSON 行情缓存与最新扫盘结果",
        "deleted": counts,
    }


@router.post("/system/ingest-settings")
async def set_ingest_settings(body: SetIngestSettingsIn):
    """设置每个板块最多分析的成分股数（0=全部）。写入 ingest_settings.override.json。"""
    from app.services.ingest_settings_store import write_max_stocks_override

    max_stocks = int(body.max_stocks_per_concept or 0)
    write_max_stocks_override(max_stocks)
    return {
        "message": "入库参数已保存",
        "ingest_max_stocks_per_concept": max_stocks,
    }


@router.get("/tasks/scan", response_model=TaskStatusOut)
async def scan_task_status():
    """查询后台扫盘任务进度（供前端轮询）。真正启动扫盘请用 POST /scan/latest。"""
    return TaskStatusOut(**get_scan_task().to_dict())


@router.post("/tasks/scan/cancel")
async def cancel_scan_task():
    """请求停止当前后台扫盘任务。"""
    ok = request_cancel_scan()
    if not ok:
        return {"cancelled": False, "message": "当前没有正在运行的扫描任务"}
    return {"cancelled": True, "message": "已请求停止扫描，将在当前步骤完成后终止"}


@router.get("/concepts", response_model=list[ConceptOut])
async def list_all_concepts():
    from app.services.concept_cache import get_cached_concepts

    concepts, _ = get_cached_concepts()
    return [ConceptOut(sector_code=c.code, sector_name=c.name) for c in concepts]


def _scan_concept_total() -> int:
    try:
        from app.services.concept_select import select_concepts_for_ingest
        from app.services.concept_cache import get_cached_concepts as _gcc

        all_concepts, _ = _gcc()
        selected = select_concepts_for_ingest(all_concepts)
        return max(len(selected), 1)
    except Exception:
        try:
            from app.services.concept_cache import get_cached_concepts as _gcc2

            concepts, _ = _gcc2()
            return max(len(concepts), 1)
        except Exception:
            return 1


_INGEST_LOOKBACK_DAYS = 8


def _run_scan_sync(trade_days: list[date]) -> None:
    """
    在线程池执行扫盘。
    优化：仅对最近 N 天执行 ingest（volume_ratio/market_share/inflow 所需），
    只对最后一天执行评分，MA20/pct_20d 由 ths_daily 实时补充。
    """
    import asyncio
    import logging

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.config import settings

    if not trade_days:
        return
    last_td = trade_days[-1]
    ingest_days = trade_days[-_INGEST_LOOKBACK_DAYS:]
    td_str = str(last_td)
    concepts_per_day = _scan_concept_total()
    OVERHEAD_PER_DAY = 3
    steps_per_day = concepts_per_day + OVERHEAD_PER_DAY
    total = steps_per_day * len(ingest_days) + 1  # +1 for final scoring
    n_days = len(ingest_days)
    scan_completed = False

    from app.services.scan_context import clear_scan_context

    async def _run() -> None:
        nonlocal scan_completed
        import logging
        import time

        from app.services.scan_pipeline import ScanPipelineTracker, set_tracker

        log = logging.getLogger(__name__)
        scan_t0 = time.monotonic()
        adapter_name = get_adapter().__class__.__name__
        tracker = ScanPipelineTracker(
            trade_date=td_str,
            adapter=adapter_name,
            concept_count=total,
        )
        set_tracker(tracker)
        log.info(
            "[扫描] 开始 全区间=%s 实际ingest=%s (%d日) 评分=%s",
            [str(d) for d in trade_days],
            [str(d) for d in ingest_days],
            n_days,
            last_td,
        )

        worker_engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
        )
        WorkerSession = async_sessionmaker(
            worker_engine, class_=AsyncSession, expire_on_commit=False
        )
        try:
            async with WorkerSession() as session:
                ingestion = IngestionService(session)

                scores: list = []

                for day_idx, trade_date in enumerate(ingest_days):
                    if is_cancel_requested():
                        cancel_scan()
                        log.info("[扫描] 用户请求取消，已中止")
                        return

                    day_offset = day_idx * steps_per_day
                    day_label = f"[{day_idx + 1}/{n_days}] {trade_date}"

                    update_scan_progress(
                        day_offset,
                        total,
                        f"{day_label} 拉取板块数据…",
                        current_trade_date=str(trade_date),
                    )

                    def _make_on_progress(
                        d_offset: int, td: date, d_idx: int
                    ):
                        def on_progress(
                            done: int, concept_total: int, label: str = ""
                        ) -> None:
                            step = d_offset + 1 + done
                            if done == 0:
                                msg = f"[{d_idx + 1}/{n_days}] {td} 大盘环境与预取数据…"
                            elif label:
                                msg = f"[{d_idx + 1}/{n_days}] {td} 板块 {done}/{concept_total}：{label}"
                            else:
                                msg = f"[{d_idx + 1}/{n_days}] {td} 板块 {done}/{concept_total}…"
                            update_scan_progress(
                                step,
                                total,
                                msg,
                                current_trade_date=str(td),
                            )

                        return on_progress

                    on_progress = _make_on_progress(day_offset, trade_date, day_idx)

                    ingest_t0 = time.monotonic()
                    is_last = (trade_date == last_td)
                    await ingestion.ingest_day(
                        trade_date,
                        on_progress=on_progress,
                        skip_market_env=not is_last,
                    )
                    if is_cancel_requested():
                        cancel_scan()
                        log.info("[扫描] 用户请求取消（ingest进行中），已中止")
                        return
                    log.info(
                        "[扫描] ingest %s 完成 耗时=%.1fs",
                        trade_date,
                        time.monotonic() - ingest_t0,
                    )

                    update_scan_progress(
                        day_offset + steps_per_day,
                        total,
                        f"{day_label} 完成",
                        current_trade_date=str(trade_date),
                    )

                if is_cancel_requested():
                    cancel_scan()
                    log.info("[扫描] 用户请求取消（评分前），已中止")
                    return

                # 仅对最后一个交易日执行评分
                score_offset = n_days * steps_per_day
                update_scan_progress(
                    score_offset,
                    total,
                    f"评分 {last_td}…",
                    current_trade_date=str(last_td),
                )
                scanner = ScanService(session)
                scores = await scanner.run_scan(last_td)
                from app.services.volatile_scan import get_today_buffer

                buf_day = get_today_buffer()
                if buf_day is not None:
                    buf_day.scores_by_date[last_td] = list(scores)

                score_phase_t0 = tracker.start_phase(
                    "theme_score",
                    "板块评分与预警",
                    f"共 {len(trade_days)} 个交易日评分完成",
                )
                tracker.end_phase(
                    "theme_score",
                    "板块评分与预警",
                    "最终以最近交易日更新仪表盘",
                    score_phase_t0,
                    extra=f"{len(scores)}个板块 @ {last_td}",
                )
                from app.services.latest_scan_store import LatestScanStore
                from app.services.scan_context import (
                    get_calendar_bounds,
                    pop_market_cache_stats,
                )
                from app.services.storage_mode import uses_file_scan_storage
                from app.services.volatile_scan import (
                    VolatileDashboardSnapshot,
                    get_today_buffer,
                    set_dashboard_snapshot,
                )

                buf_r = get_today_buffer()
                if buf_r and not scores and last_td in buf_r.scores_by_date:
                    scores = list(buf_r.scores_by_date[last_td])
                    log.warning(
                        "[数据] 最终日评分为空，回退使用 scores_by_date[%s] count=%d",
                        last_td,
                        len(scores),
                    )
                if buf_r and not scores and buf_r.sectors_by_code:
                    log.warning(
                        "[数据] 评分为空但缓冲区内有 %d 个板块，重跑最终日评分",
                        len(buf_r.sectors_by_code),
                    )
                    scanner = ScanService(session)
                    scores = await scanner.run_scan(last_td)
                    buf_r.scores_by_date[last_td] = list(scores)
                # 防止“当日行情全空”覆盖仪表盘：仅记录告警，不再中断任务。
                if buf_r:
                    final_rows = [
                        r
                        for r in (buf_r.sector_rows or [])
                        if getattr(r, "trade_date", None) == last_td
                    ]
                    has_effective = any(
                        int(getattr(r, "total_count", 0) or 0) > 0
                        and float(getattr(r, "close", 0) or 0) > 0
                        for r in final_rows
                    )
                    if final_rows and not has_effective:
                        log.error(
                            "[数据] %s 板块行情全空（total_count=0），继续发布快照供排查",
                            last_td,
                        )

                env_for_dash = buf_r.market_env if buf_r else None
                lm: dict = {}
                if buf_r:
                    lm = {
                        code: leader
                        for code, leader in buf_r.leaders_by_code.items()
                        if getattr(leader, "trade_date", None) == last_td
                    }
                cal_start, cal_end = get_calendar_bounds()
                sd: dict = {}
                sf: dict = {}
                if buf_r:
                    sd = dict(buf_r.sectors_by_code)
                    sf = dict(buf_r.flows_by_code)
                snap = VolatileDashboardSnapshot(
                    trade_date=last_td,
                    env=env_for_dash,
                    scores=list(scores),
                    leader_map=lm,
                    scan_trade_days=list(trade_days),
                    sector_dailies=sd,
                    sector_flows=sf,
                )
                set_dashboard_snapshot(snap)
                if uses_file_scan_storage():
                    mstats = pop_market_cache_stats()
                    LatestScanStore.save(
                        trade_date=last_td,
                        scores=list(scores),
                        market_env=env_for_dash,
                        leader_map=lm,
                        scan_trade_days=list(trade_days),
                        scan_start_date=cal_start,
                        scan_end_date=cal_end,
                        market_cache_stats=mstats or None,
                        sector_dailies=sd,
                        sector_flows=sf,
                    )
                    log.info(
                        "[数据] 已写入 scan/latest.json trade_date=%s scores=%d "
                        "行情缓存跳过 %s 日 新拉 %s 日",
                        last_td,
                        len(scores),
                        mstats.get("skipped", 0),
                        mstats.get("fetched", 0),
                    )
                await session.rollback()
                log.info(
                    "[数据] 内存快照已发布 trade_date=%s scores=%d",
                    last_td,
                    len(scores),
                )
                if not scores:
                    fail_scan(
                        f"扫描完成但未产生板块评分（交易日 {last_td}），请检查板块勾选与日期区间"
                    )
                    return
                finish_scan(len(scores), td_str)
                scan_completed = True
                log.info(
                    "[数据] _run_scan_sync 全部完成 总耗时=%.2fs last_trade_date=%s",
                    time.monotonic() - scan_t0,
                    last_td,
                )
        except Exception as exc:
            fail_scan(str(exc))
            raise
        finally:
            tracker.log_summary()
            set_tracker(None)
            await worker_engine.dispose()

    log = logging.getLogger(__name__)
    try:
        asyncio.run(_run())
    except Exception as exc:
        log.exception("[数据] _run_scan_sync 异常终止: %s", exc)
        if not scan_completed and get_scan_task().status == "running":
            fail_scan(str(exc))
    finally:
        clear_scan_context()


@router.post("/scan/latest")
async def scan_latest(
    background_tasks: BackgroundTasks,
    trade_date: Optional[date] = Query(None, description="兼容：等同 end_date"),
    start_date: Optional[date] = Query(None, description="扫描开始交易日"),
    end_date: Optional[date] = Query(None, description="扫描结束交易日"),
):
    if trade_date is not None and end_date is None:
        end_date = trade_date
    try:
        trade_days = resolve_scan_trade_days(start_date, end_date)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    last_td = trade_days[-1]
    import logging

    logging.getLogger(__name__).info(
        "[流程] POST /scan/latest 请求区间 start=%s end=%s -> 交易日 %s",
        start_date,
        end_date,
        [str(d) for d in trade_days],
    )
    from app.services.ingest_settings_store import read_scan_sectors_selection

    use_explicit, selected = read_scan_sectors_selection()
    if use_explicit and not selected:
        raise HTTPException(
            400,
            detail="请先在仪表盘「扫描板块」中至少勾选一个概念板块",
        )
    current = get_scan_task()
    if current.status == "running":
        return {
            "trade_date": str(last_td),
            "status": "running",
            "message": "已有扫描任务在执行中，请稍候",
        }
    concepts_count = _scan_concept_total()
    actual_ingest = min(len(trade_days), _INGEST_LOOKBACK_DAYS)
    total = (concepts_count + 3) * actual_ingest + 1
    range_label = (
        str(trade_days[0])
        if len(trade_days) == 1
        else f"{trade_days[0]} ~ {trade_days[-1]}（{len(trade_days)} 日）"
    )
    td_list = [str(d) for d in trade_days]
    req_start = str(start_date) if start_date is not None else td_list[0]
    req_end = str(end_date) if end_date is not None else td_list[-1]
    from app.services.scan_context import set_scan_bounds

    set_scan_bounds(
        trade_days,
        calendar_start=start_date,
        calendar_end=end_date,
    )
    clear_cancel_flag()
    start_scan(
        str(last_td),
        f"收盘扫描已启动 {req_start} ~ {req_end}…",
        total=total,
        scan_start_date=req_start,
        scan_end_date=req_end,
        trade_days=td_list,
    )
    background_tasks.add_task(_run_scan_sync, trade_days)
    msg = f"正在扫描 {range_label}"
    return {
        "trade_date": str(last_td),
        "start_date": str(trade_days[0]),
        "end_date": str(last_td),
        "trade_days": [str(d) for d in trade_days],
        "status": "started",
        "message": msg,
    }


@router.post("/scan/{trade_date}")
async def trigger_scan(trade_date: date, db: AsyncSession = Depends(get_db)):
    trade_date = resolve_scan_date(trade_date)
    ingestion = IngestionService(db)
    await ingestion.ingest_day(trade_date)
    scanner = ScanService(db)
    scores = await scanner.run_scan(trade_date)

    from app.services.storage_mode import uses_file_scan_storage

    from app.services.latest_scan_store import LatestScanStore
    from app.services.volatile_scan import (
        VolatileDashboardSnapshot,
        get_today_buffer,
        set_dashboard_snapshot,
    )

    buf = get_today_buffer()
    lm = dict(buf.leaders_by_code) if buf else {}
    snap = VolatileDashboardSnapshot(
        trade_date=trade_date,
        env=(buf.market_env if buf else None),
        scores=list(scores),
        leader_map=lm,
        scan_trade_days=[trade_date],
    )
    set_dashboard_snapshot(snap)
    if uses_file_scan_storage():
        LatestScanStore.save(
            trade_date=trade_date,
            scores=list(scores),
            market_env=snap.env,
            leader_map=lm,
            scan_trade_days=[trade_date],
        )
    await db.rollback()

    return {"trade_date": str(trade_date), "sectors_scored": len(scores)}


def _fetch_index_summaries(adapter, td: date) -> list[dict[str, Any]]:
    from datetime import timedelta

    codes = [
        ("000001.SH", "上证指数"),
        ("399001.SZ", "深证成指"),
        ("000300.SH", "沪深300"),
    ]
    out: list[dict[str, Any]] = []
    # 使用更长回看窗口，确保长假后也能拿到“上一交易日”收盘对比基准。
    start = td - timedelta(days=40)
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
        out.append(
            {
                "code": code,
                "name": name,
                "close": round(today.close, 2),
                "pre_close": round(prev_close, 2),
                "pct_change": round(today.pct_change, 2),
                "point_change": round(today.close - prev_close, 2),
            }
        )
    return out


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(trade_date: Optional[date] = None):
    """仪表盘：仅展示市场总览 + 指数涨幅（不依赖扫盘数据）。"""
    from app.services.dashboard_service import build_dashboard_response

    result = await build_dashboard_response(trade_date)
    return DashboardOut(**result)


@router.get("/dashboard/limit-stocks", response_model=LimitStockListOut)
async def dashboard_limit_stocks(
    side: str = Query(default="up", pattern="^(up|down)$"),
    trade_date: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
):
    from app.services.market_cache import MarketTable, get_market_cache
    from app.services.dashboard_service import resolve_dashboard_trade_date

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

    td = resolve_dashboard_trade_date(trade_date)
    if not td:
        return LimitStockListOut(trade_date=None, side=side, total=0, items=[])

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
        return LimitStockListOut(trade_date=td, side=side, total=0, items=[])

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
        return LimitStockListOut(trade_date=td, side=side, total=0, items=[])

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
        return LimitStockListOut(trade_date=td, side=side, total=0, items=[])
    rows = rows.assign(
        close=close.loc[mask].values,
        limit_price=limit_price.loc[mask].values,
        pct_change=pct_change.loc[mask].values,
    )
    rows = rows.sort_values(
        by=["pct_change", "ts_code"],
        ascending=[False, True] if side == "up" else [True, True],
    )

    # 名称优先使用 Tushare stock_basic 全量映射；若缓存曾异常为空，尝试刷新一次。
    fresh_name_map: dict[str, str] = {}
    try:
        from app.adapters.tushare_adapter import load_stock_name_map

        fresh_name_map = load_stock_name_map()
        if not fresh_name_map:
            clear_name_cache()
            fresh_name_map = load_stock_name_map()
    except Exception:
        fresh_name_map = {}
    if not fresh_name_map:
        try:
            adapter = adapter or get_adapter()
            if hasattr(adapter, "_call"):
                name_df = adapter._call(
                    "stock_basic",
                    exchange="",
                    list_status="L",
                    fields="ts_code,name",
                )
                if name_df is not None and not name_df.empty and {"ts_code", "name"}.issubset(set(name_df.columns)):
                    fresh_name_map = {
                        to_internal_code(str(r["ts_code"])): str(r["name"])
                        for _, r in name_df.iterrows()
                        if str(r.get("ts_code", "")).strip()
                    }
        except Exception:
            fresh_name_map = {}

    def _fetch_tushare_names_fallback(ts_codes: list[str], data_adapter: Any) -> dict[str, str]:
        """仅使用 Tushare stock_basic 兜底补充股票名称。"""
        if not ts_codes or not hasattr(data_adapter, "_call"):
            return {}
        out: dict[str, str] = {}
        for raw in sorted({str(c or "").strip().upper() for c in ts_codes if str(c or "").strip()}):
            df = None
            for status in ("L", "D", "P"):
                try:
                    df = data_adapter._call(
                        "stock_basic",
                        ts_code=raw,
                        list_status=status,
                        fields="ts_code,name",
                    )
                except Exception as exc:
                    logger.debug("[数据] stock_basic 名称兜底失败 ts_code=%s status=%s: %s", raw, status, exc)
                    continue
                if df is not None and not df.empty:
                    break
            if (df is None or df.empty):
                try:
                    df = data_adapter._call("stock_basic", ts_code=raw, fields="ts_code,name")
                except Exception as exc:
                    logger.debug("[数据] stock_basic 名称兜底失败 ts_code=%s: %s", raw, exc)
                    continue
            if df is None or df.empty or not {"ts_code", "name"}.issubset(set(df.columns)):
                continue
            row = df.iloc[0]
            ts_code = str(row.get("ts_code", "")).strip().upper()
            name = str(row.get("name", "")).strip()
            if ts_code and name:
                out[ts_code] = name
        return out

    row_items: list[dict[str, Any]] = []
    unresolved_codes: list[str] = []
    for _, r in rows.iterrows():
        ts_code = str(r["ts_code"])
        internal = to_internal_code(ts_code)
        day_name = str(r.get("name", "") or "").strip()
        stock_name = (
            (day_name if day_name and day_name not in {ts_code, internal} else "")
            or fresh_name_map.get(internal)
            or resolve_stock_name(internal)
            or resolve_stock_name(ts_code)
            or ts_code
        )
        if stock_name in {internal, ts_code, ""}:
            unresolved_codes.append(ts_code)
        row_items.append(
            {
                "stock_code": ts_code,
                "stock_name": stock_name,
                "close": round(float(r["close"]), 2),
                "limit_price": round(float(r["limit_price"]), 2),
                "pct_change": round(float(r["pct_change"]), 2),
            }
        )
    if unresolved_codes:
        adapter = adapter or get_adapter()
        fallback_names = _fetch_tushare_names_fallback(unresolved_codes, adapter)
        if fallback_names:
            for item in row_items:
                code = item["stock_code"]
                if item["stock_name"] in {code, to_internal_code(code), ""}:
                    item["stock_name"] = fallback_names.get(code, item["stock_name"])
    items = row_items
    return LimitStockListOut(trade_date=td, side=side, total=len(items), items=items)


@router.get("/alerts", response_model=list[AlertOut])
async def list_alerts(
    trade_date: Optional[date] = None,
    alert_code: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    td = _normalize_requested_trade_date(trade_date) or await _latest_trade_date(db)
    if not td:
        return []
    q = select(Alert).where(Alert.trade_date == td).order_by(desc(Alert.id))
    if alert_code:
        q = q.where(Alert.alert_code == alert_code)
    rows = (await db.execute(q)).scalars().all()
    return [AlertOut.model_validate(r) for r in rows]


@router.get("/sectors", response_model=SectorListOut)
async def list_sectors(
    trade_date: Optional[date] = None,
    scored_only: bool = Query(True, description="仅返回已扫描评分的板块（更快）"),
    db: AsyncSession = Depends(get_db),
):
    from app.services.concept_cache import get_cached_concepts

    td = _normalize_requested_trade_date(trade_date) or await _latest_trade_date(db)
    info = adapter_info()
    all_concepts: list = []
    if not scored_only:
        all_concepts, _ = get_cached_concepts()
    universe_total = info.get("universe_total") or len(all_concepts)

    score_map: dict[str, SectorScoreDaily] = {}
    pct_map: dict[str, float] = {}
    leader_map: dict[str, ThemeLeaderDaily] = {}

    if td:
        scores = (
            await db.execute(
                select(SectorScoreDaily).where(SectorScoreDaily.trade_date == td)
            )
        ).scalars().all()
        score_map = {s.sector_code: s for s in scores}
        daily_rows = (
            await db.execute(select(SectorDaily).where(SectorDaily.trade_date == td))
        ).scalars().all()
        pct_map = {r.sector_code: r.pct_change for r in daily_rows}
        leaders = (
            await db.execute(
                select(ThemeLeaderDaily).where(ThemeLeaderDaily.trade_date == td)
            )
        ).scalars().all()
        leader_map = {l.sector_code: l for l in leaders}

    # DB 无数据时回退到内存快照（scan_volatile_storage=true 场景）
    if not score_map and td:
        snap = _resolve_dashboard_snapshot()
        if snap and snap.scores:
            snap_days = list(snap.scan_trade_days) if snap.scan_trade_days else []
            if td == snap.trade_date or td in snap_days:
                score_map = {s.sector_code: s for s in snap.scores}
                leader_map = {
                    code: val for code, val in (snap.leader_map or {}).items()
                }
                if snap.sector_dailies:
                    for code, sd in snap.sector_dailies.items():
                        if hasattr(sd, "pct_change"):
                            pct_map[code] = sd.pct_change
                        elif isinstance(sd, dict) and "pct_change" in sd:
                            pct_map[code] = sd["pct_change"]

    def _score_out(s) -> SectorScoreOut:
        l = leader_map.get(s.sector_code)
        leader_stock = None
        leader_streak = None
        if l is not None:
            if hasattr(l, "stock_code"):
                leader_stock = l.stock_code
                leader_streak = getattr(l, "limit_up_streak", None)
            elif isinstance(l, dict):
                leader_stock = l.get("stock_code")
                leader_streak = l.get("limit_up_streak")
        reasons_raw = getattr(s, "rule_fail_reasons", None)
        if isinstance(reasons_raw, str):
            rule_fail_reasons = [x for x in reasons_raw.split("；") if x]
        elif isinstance(reasons_raw, list):
            rule_fail_reasons = reasons_raw
        else:
            rule_fail_reasons = []
        return SectorScoreOut(
            sector_code=s.sector_code,
            sector_name=s.sector_name,
            total_score=s.total_score,
            stage=s.stage,
            rank=s.rank,
            persistence_score=s.persistence_score,
            capital_score=s.capital_score,
            breadth_score=s.breadth_score,
            leader_score=s.leader_score,
            relative_score=s.relative_score,
            position_hint=s.position_hint,
            leader_stock=leader_stock,
            leader_streak=leader_streak,
            pct_change=pct_map.get(s.sector_code),
            is_filtered=s.is_filtered,
            filter_reason=s.filter_reason,
            is_scored=True,
            is_main_line=bool(getattr(s, "is_main_line", False)),
            main_line_tier=str(getattr(s, "main_line_tier", "rotation") or "rotation"),
            confirm_state=str(getattr(s, "confirm_state", "pending") or "pending"),
            exit_state=str(getattr(s, "exit_state", "normal") or "normal"),
            source_tag=str(getattr(s, "source_tag", "auto") or "auto"),
            rules=list(getattr(s, "rules_json", []) or []),
            rule_fail_reasons=rule_fail_reasons,
        )

    scored_list: list[SectorScoreOut] = []
    unscored_list: list[SectorScoreOut] = []

    if scored_only:
        scored_list = [_score_out(s) for s in sorted(score_map.values(), key=lambda x: x.rank)]
    else:
        scored_codes = set()
        for c in all_concepts:
            s = score_map.get(c.code)
            if s:
                scored_codes.add(c.code)
                scored_list.append(_score_out(s))
            else:
                unscored_list.append(
                    SectorScoreOut(
                        sector_code=c.code,
                        sector_name=c.name,
                        total_score=0,
                        stage="dormant",
                        rank=0,
                        persistence_score=0,
                        capital_score=0,
                        breadth_score=0,
                        leader_score=0,
                        relative_score=0,
                        position_hint="observe",
                        is_scored=False,
                    )
                )

    scored_list.sort(key=lambda x: x.rank)
    unscored_list.sort(key=lambda x: x.sector_name)
    sectors = scored_list if scored_only else scored_list + unscored_list

    return SectorListOut(
        trade_date=td,
        universe_total=universe_total,
        sectors_scored=len(scored_list),
        is_live_data=info.get("is_live_data", False),
        data_source=info["adapter"],
        data_source_label=info.get("data_source_label", ""),
        data_source_short=info.get("data_source_short", ""),
        sectors=sectors,
    )


@router.get("/sectors/{sector_code}", response_model=SectorDetailOut)
async def sector_detail(
    sector_code: str,
    trade_date: Optional[date] = None,
    stocks_limit: int = Query(
        30, ge=0, description="成分股展示条数（0=全部，可能较慢）"
    ),
    db: AsyncSession = Depends(get_db),
):
    td = _normalize_requested_trade_date(trade_date) or await _latest_trade_date(db)
    if not td:
        raise HTTPException(404, "No data")

    snap = _resolve_dashboard_snapshot()
    if snap:
        from app.services.volatile_scan import get_today_buffer

        buf = get_today_buffer()
        snap_days = list(snap.scan_trade_days) if snap.scan_trade_days else []
        if td == snap.trade_date or td in snap_days:
            score_row = next(
                (s for s in snap.scores if s.sector_code == sector_code), None
            )
            if score_row:
                daily = buf.sectors_by_code.get(sector_code) if buf else None
                flow = buf.flows_by_code.get(sector_code) if buf else None
                daily_from_snap = None
                flow_from_snap = None
                if daily is None:
                    snap_dailies = getattr(snap, "sector_dailies", None) or {}
                    daily_from_snap = snap_dailies.get(sector_code)
                if flow is None:
                    snap_flows = getattr(snap, "sector_flows", None) or {}
                    flow_from_snap = snap_flows.get(sector_code)
                leader = snap.leader_map.get(sector_code) or (
                    buf.leaders_by_code.get(sector_code) if buf else None
                )
                scan_days = list(snap.scan_trade_days) if snap.scan_trade_days else [td]
                display_days = _pct_display_days(td, scan_days)
                has_buf_stocks = buf is not None and any(
                    getattr(r, "sector_code", None) == sector_code
                    and getattr(r, "trade_date", None) == td
                    for r in buf.stocks
                )
                if has_buf_stocks:
                    stock_models = _build_stocks_in_sector(
                        sector_code, td, buf.stocks, display_days, limit=stocks_limit
                    )
                    stock_models = _backfill_pct_history(
                        stock_models, display_days, anchor=td
                    )
                else:
                    stock_models = _build_stocks_on_demand(
                        sector_code, td, display_days, limit=stocks_limit
                    )
                reasons_raw = getattr(score_row, "rule_fail_reasons", None)
                if isinstance(reasons_raw, str):
                    rule_fail_reasons = [x for x in reasons_raw.split("；") if x]
                elif isinstance(reasons_raw, list):
                    rule_fail_reasons = reasons_raw
                else:
                    rule_fail_reasons = []
                net_wan = (
                    flow.net_inflow_main
                    if flow
                    else float(flow_from_snap.get("net_inflow_main", 0) or 0)
                    if flow_from_snap
                    else 0.0
                )
                up_c = (
                    daily.up_count
                    if daily
                    else int(daily_from_snap.get("up_count", 0) or 0)
                    if daily_from_snap
                    else 0
                )
                tot_c = (
                    daily.total_count
                    if daily
                    else int(daily_from_snap.get("total_count", 0) or 0)
                    if daily_from_snap
                    else 1
                )
                missing_items = _build_data_missing_items(daily, flow, stock_models)
                return SectorDetailOut(
                    sector_code=sector_code,
                    sector_name=score_row.sector_name,
                    trade_date=td,
                    pct_display_days=display_days,
                    stage=score_row.stage,
                    total_score=score_row.total_score,
                    is_main_line=bool(getattr(score_row, "is_main_line", False)),
                    main_line_tier=str(getattr(score_row, "main_line_tier", "rotation") or "rotation"),
                    confirm_state=str(getattr(score_row, "confirm_state", "pending") or "pending"),
                    exit_state=str(getattr(score_row, "exit_state", "normal") or "normal"),
                    source_tag=str(getattr(score_row, "source_tag", "auto") or "auto"),
                    rules=list(getattr(score_row, "rules_json", []) or []),
                    rule_fail_reasons=rule_fail_reasons,
                    limit_up_count=(
                        daily.limit_up_count
                        if daily
                        else int(daily_from_snap.get("limit_up_count", 0) or 0)
                        if daily_from_snap
                        else 0
                    ),
                    big_yang_count=(
                        daily.big_yang_count
                        if daily
                        else int(daily_from_snap.get("big_yang_count", 0) or 0)
                        if daily_from_snap
                        else 0
                    ),
                    net_inflow_main=net_wan,
                    net_inflow_yi=round(net_wan / 10000, 2),
                    inflow_days=(
                        flow.inflow_days
                        if flow
                        else int(flow_from_snap.get("inflow_days", 0) or 0)
                        if flow_from_snap
                        else 0
                    ),
                    up_count=up_c,
                    total_count=tot_c,
                    up_ratio=round(up_c / tot_c, 4) if tot_c else 0,
                    blow_up_rate=(
                        daily.blow_up_rate
                        if daily
                        else float(daily_from_snap.get("blow_up_rate", 0) or 0)
                        if daily_from_snap
                        else 0
                    ),
                    position_hint=score_row.position_hint,
                    leader={
                        "stock_code": leader.stock_code,
                        "stock_name": leader.stock_name
                        or resolve_stock_name(leader.stock_code),
                        "streak": leader.limit_up_streak,
                        "pct_change": leader.pct_change,
                    }
                    if leader
                    else None,
                    stocks=stock_models,
                    history=[
                        {
                            "trade_date": str(td),
                            "total_score": score_row.total_score,
                            "stage": score_row.stage,
                        }
                    ],
                    flow_history=[],
                    data_missing_items=missing_items,
                )

    score = (
        await db.execute(
            select(SectorScoreDaily).where(
                SectorScoreDaily.trade_date == td,
                SectorScoreDaily.sector_code == sector_code,
            )
        )
    ).scalar_one_or_none()
    if not score:
        raise HTTPException(404, "Sector not found")

    daily = (
        await db.execute(
            select(SectorDaily).where(
                SectorDaily.sector_code == sector_code,
                SectorDaily.trade_date == td,
            )
        )
    ).scalar_one_or_none()
    flow = (
        await db.execute(
            select(SectorFlowDaily).where(
                SectorFlowDaily.sector_code == sector_code,
                SectorFlowDaily.trade_date == td,
            )
        )
    ).scalar_one_or_none()
    leader = (
        await db.execute(
            select(ThemeLeaderDaily).where(
                ThemeLeaderDaily.sector_code == sector_code,
                ThemeLeaderDaily.trade_date == td,
            )
        )
    ).scalar_one_or_none()
    history_rows_for_days = (
        await db.execute(
            select(SectorScoreDaily.trade_date)
            .where(SectorScoreDaily.sector_code == sector_code)
            .order_by(desc(SectorScoreDaily.trade_date))
            .limit(_PCT_HISTORY_LIMIT)
        )
    ).scalars().all()
    scan_days_db = sorted(set(history_rows_for_days))
    display_days = _pct_display_days(td, scan_days_db or [td])

    stock_rows_multi = (
        await db.execute(
            select(StockDaily).where(
                StockDaily.sector_code == sector_code,
                StockDaily.trade_date.in_(display_days),
            )
        )
    ).scalars().all()
    stock_models = _build_stocks_in_sector(
        sector_code, td, list(stock_rows_multi), display_days, limit=stocks_limit
    )
    stock_models = _backfill_pct_history(stock_models, display_days, anchor=td)

    history_rows = (
        await db.execute(
            select(SectorScoreDaily)
            .where(SectorScoreDaily.sector_code == sector_code)
            .order_by(SectorScoreDaily.trade_date)
            .limit(10)
        )
    ).scalars().all()

    flow_history_rows = (
        await db.execute(
            select(SectorFlowDaily)
            .where(SectorFlowDaily.sector_code == sector_code)
            .order_by(desc(SectorFlowDaily.trade_date))
            .limit(20)
        )
    ).scalars().all()
    flow_history = [
        FlowDayOut(
            trade_date=f.trade_date,
            net_inflow_wan=round(f.net_inflow_main, 2),
            net_inflow_yi=round(f.net_inflow_main / 10000, 4),
        )
        for f in reversed(flow_history_rows)
    ]

    reasons_raw = getattr(score, "rule_fail_reasons", None)
    if isinstance(reasons_raw, str):
        rule_fail_reasons = [x for x in reasons_raw.split("；") if x]
    elif isinstance(reasons_raw, list):
        rule_fail_reasons = reasons_raw
    else:
        rule_fail_reasons = []
    net_wan = flow.net_inflow_main if flow else 0.0
    up_c = daily.up_count if daily else 0
    tot_c = daily.total_count if daily else 1
    missing_items = _build_data_missing_items(daily, flow, stock_models)

    return SectorDetailOut(
        sector_code=sector_code,
        sector_name=score.sector_name,
        trade_date=td,
        pct_display_days=display_days,
        stage=score.stage,
        total_score=score.total_score,
        is_main_line=bool(getattr(score, "is_main_line", False)),
        main_line_tier=str(getattr(score, "main_line_tier", "rotation") or "rotation"),
        confirm_state=str(getattr(score, "confirm_state", "pending") or "pending"),
        exit_state=str(getattr(score, "exit_state", "normal") or "normal"),
        source_tag=str(getattr(score, "source_tag", "auto") or "auto"),
        rules=list(getattr(score, "rules_json", []) or []),
        rule_fail_reasons=rule_fail_reasons,
        limit_up_count=daily.limit_up_count if daily else 0,
        big_yang_count=daily.big_yang_count if daily else 0,
        net_inflow_main=net_wan,
        net_inflow_yi=round(net_wan / 10000, 2),
        inflow_days=flow.inflow_days if flow else 0,
        up_count=up_c,
        total_count=tot_c,
        up_ratio=round(up_c / tot_c, 4) if tot_c else 0,
        blow_up_rate=daily.blow_up_rate if daily else 0,
        position_hint=score.position_hint,
        leader={
            "stock_code": leader.stock_code,
            "stock_name": leader.stock_name or resolve_stock_name(leader.stock_code),
            "streak": leader.limit_up_streak,
            "pct_change": leader.pct_change,
        }
        if leader
        else None,
        stocks=stock_models,
        history=[
            {
                "trade_date": str(h.trade_date),
                "total_score": h.total_score,
                "stage": h.stage,
            }
            for h in history_rows
        ],
        flow_history=flow_history,
        data_missing_items=missing_items,
    )


@router.get("/review/{trade_date}", response_model=ReviewDayOut)
async def review_day(trade_date: date, db: AsyncSession = Depends(get_db)):
    scores = (
        await db.execute(
            select(SectorScoreDaily)
            .where(SectorScoreDaily.trade_date == trade_date)
            .order_by(SectorScoreDaily.rank)
            .limit(5)
        )
    ).scalars().all()
    sectors = []
    for s in scores:
        future = (
            await db.execute(
                select(SectorDaily).where(
                    SectorDaily.sector_code == s.sector_code,
                    SectorDaily.trade_date > trade_date,
                ).order_by(SectorDaily.trade_date).limit(5)
            )
        ).scalars().all()
        sectors.append(
            {
                "sector_code": s.sector_code,
                "sector_name": s.sector_name,
                "score": s.total_score,
                "stage": s.stage,
                "future_pcts": [f.pct_change for f in future],
            }
        )
    return ReviewDayOut(trade_date=trade_date, sectors=sectors)


@router.get("/a-strategy/main-lines", response_model=AStrategyListOut)
async def a_strategy_main_lines(
    trade_date: Optional[date] = None,
    include_rejected: bool = Query(True, description="是否包含未通过主线规则的板块"),
    db: AsyncSession = Depends(get_db),
):
    td = _normalize_requested_trade_date(trade_date) or await _latest_trade_date(db)
    if not td:
        return AStrategyListOut(trade_date=None, sectors=[])
    rows = (
        await db.execute(
            select(SectorScoreDaily)
            .where(SectorScoreDaily.trade_date == td)
            .order_by(SectorScoreDaily.rank)
        )
    ).scalars().all()
    leaders = (
        await db.execute(select(ThemeLeaderDaily).where(ThemeLeaderDaily.trade_date == td))
    ).scalars().all()
    leader_map = {l.sector_code: l for l in leaders}
    out = [_sector_score_out(s, leader_map.get(s.sector_code)) for s in rows]
    if not include_rejected:
        out = [s for s in out if s.is_main_line]
    return AStrategyListOut(trade_date=td, sectors=out)


@router.get("/a-strategy/main-lines/{sector_code}", response_model=SectorDetailOut)
async def a_strategy_main_line_detail(
    sector_code: str,
    trade_date: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
):
    return await sector_detail(sector_code=sector_code, trade_date=trade_date, db=db)


@router.get("/a-strategy/manual-inputs", response_model=list[AStrategyManualInputOut])
async def a_strategy_manual_inputs(trade_date: date):
    items = get_manual_inputs_for_day(trade_date)
    return [
        AStrategyManualInputOut(trade_date=trade_date, sector_code=code, values=dict(vals))
        for code, vals in sorted(items.items())
    ]


@router.get("/a-strategy/manual-inputs/{sector_code}", response_model=AStrategyManualInputOut)
async def a_strategy_manual_input_detail(trade_date: date, sector_code: str):
    item = get_manual_input(trade_date, sector_code)
    if item is None:
        return AStrategyManualInputOut(
            trade_date=trade_date,
            sector_code=sector_code,
            values={},
        )
    return AStrategyManualInputOut(
        trade_date=item.trade_date,
        sector_code=item.sector_code,
        values=item.values,
    )


@router.post("/a-strategy/manual-inputs", response_model=AStrategyManualInputOut)
async def set_a_strategy_manual_input(body: AStrategyManualInputIn):
    values: dict[str, Any] = {}
    if body.auction_passed is not None:
        values["auction_passed"] = body.auction_passed
    if body.negative_news is not None:
        values["negative_news"] = body.negative_news
    if body.northbound_5d_yi is not None:
        values["northbound_5d_yi"] = body.northbound_5d_yi
    if body.notes:
        values["notes"] = body.notes
    upsert_manual_input(body.trade_date, body.sector_code, values)
    merged = get_manual_input(body.trade_date, body.sector_code)
    return AStrategyManualInputOut(
        trade_date=body.trade_date,
        sector_code=body.sector_code,
        values=merged.values if merged else values,
    )


@router.delete("/a-strategy/manual-inputs/{sector_code}")
async def delete_a_strategy_manual_input(
    sector_code: str,
    trade_date: date,
):
    deleted = delete_manual_input(trade_date, sector_code)
    return {"deleted": deleted, "trade_date": str(trade_date), "sector_code": sector_code}


async def _run_backtest_task(run_id: int) -> None:
    from app.services.backtest_context import clear_backtest_context, set_backtest_sector_codes

    async with AsyncSessionLocal() as session:
        run = await session.get(BacktestRun, run_id)
        try:
            if run and run.strategy_id == "main_line_rotation":
                codes = list((run.params or {}).get("sector_codes") or [])
                set_backtest_sector_codes(codes)
            scoring_mode = None
            if run:
                scoring_mode = (run.params or {}).get("scoring_mode")
            engine = BacktestEngine(session, scoring_mode=scoring_mode)
            await engine.run(run_id)
            await session.commit()
        except Exception:
            await session.rollback()
            async with AsyncSessionLocal() as s2:
                run_fail = await s2.get(BacktestRun, run_id)
                if run_fail:
                    run_fail.status = "failed"
                    await s2.commit()
        finally:
            clear_backtest_context()


@router.get("/backtest/sector-candidates", response_model=BacktestSectorCandidatesOut)
async def backtest_sector_candidates():
    """回测可选板块：来自最近一次扫盘评分结果。"""
    snap = _resolve_dashboard_snapshot()
    if not snap or not snap.scores:
        raise HTTPException(
            status_code=400,
            detail="请先完成一次扫盘，再在回测页勾选板块",
        )
    sectors = sorted(snap.scores, key=lambda s: getattr(s, "rank", 999))
    if settings.effective_scoring_mode() == "a_strategy":
        sectors = [s for s in sectors if bool(getattr(s, "is_main_line", False))]
    return BacktestSectorCandidatesOut(
        trade_date=snap.trade_date,
        sectors=[
            BacktestSectorCandidateOut(
                sector_code=s.sector_code,
                sector_name=s.sector_name,
                rank=int(getattr(s, "rank", 0) or 0),
                total_score=float(getattr(s, "total_score", 0) or 0),
                stage=str(getattr(s, "stage", "dormant") or "dormant"),
                persistence_score=float(getattr(s, "persistence_score", 0) or 0),
                capital_score=float(getattr(s, "capital_score", 0) or 0),
                breadth_score=float(getattr(s, "breadth_score", 0) or 0),
                leader_score=float(getattr(s, "leader_score", 0) or 0),
                relative_score=float(getattr(s, "relative_score", 0) or 0),
                is_main_line=bool(getattr(s, "is_main_line", False)),
                main_line_tier=str(getattr(s, "main_line_tier", "rotation") or "rotation"),
                confirm_state=str(getattr(s, "confirm_state", "pending") or "pending"),
                exit_state=str(getattr(s, "exit_state", "normal") or "normal"),
                source_tag=str(getattr(s, "source_tag", "auto") or "auto"),
                rules=list(getattr(s, "rules_json", []) or []),
                rule_fail_reasons=(
                    [x for x in str(getattr(s, "rule_fail_reasons", "") or "").split("；") if x]
                ),
            )
            for s in sectors
        ],
    )


@router.post("/backtest/runs", response_model=BacktestRunOut)
async def create_backtest(
    body: BacktestCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    start_date, end_date = clamp_backtest_range(body.start_date, body.end_date)
    params = dict(body.params or {})
    params.setdefault("scoring_mode", settings.effective_scoring_mode())
    if body.strategy_id == "main_line_rotation":
        codes = params.get("sector_codes") or []
        if not codes:
            raise HTTPException(
                status_code=400,
                detail="主线轮动回测请至少勾选一个板块",
            )
        params.setdefault("initial_capital", 1_000_000)
        params.setdefault("position_ratio", 0.95)
        params.setdefault("main_line_streak_days", 3)
    run = BacktestRun(
        strategy_id=body.strategy_id,
        start_date=start_date,
        end_date=end_date,
        params=params,
        status="pending",
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    background_tasks.add_task(_run_backtest_task, run.id)
    return BacktestRunOut.model_validate(run)


@router.get("/backtest/runs", response_model=list[BacktestRunOut])
async def list_backtest_runs(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(BacktestRun).order_by(desc(BacktestRun.id)).limit(20))
    ).scalars().all()
    return [BacktestRunOut.model_validate(r) for r in rows]


@router.get("/backtest/runs/{run_id}", response_model=BacktestRunOut)
async def get_backtest_run(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return BacktestRunOut.model_validate(run)


@router.get("/backtest/runs/{run_id}/report", response_model=BacktestReport)
async def backtest_report(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    metrics = (
        await db.execute(select(BacktestMetric).where(BacktestMetric.run_id == run_id))
    ).scalars().first()
    equity = (
        await db.execute(
            select(BacktestEquityDaily)
            .where(BacktestEquityDaily.run_id == run_id)
            .order_by(BacktestEquityDaily.trade_date)
        )
    ).scalars().all()

    params = run.params or {}
    initial_capital = float(params.get("initial_capital") or 0)
    abs_mode = run.strategy_id == "main_line_rotation" or (
        bool(equity) and equity[0].equity >= 10_000
    )
    bench_scale = initial_capital if initial_capital >= 10_000 else 1_000_000

    equity_curve: list[EquityPointOut] = []
    for e in equity:
        bench = float(e.benchmark_equity)
        if abs_mode and bench < 1000:
            bench *= bench_scale
        equity_curve.append(
            EquityPointOut(
                trade_date=str(e.trade_date),
                equity=e.equity,
                benchmark=bench,
            )
        )

    report_metrics = None
    if metrics:
        report_metrics = {
            "total_return": metrics.total_return,
            "annual_return": metrics.annual_return,
            "max_drawdown": metrics.max_drawdown,
            "sharpe": metrics.sharpe,
            "win_rate": metrics.win_rate,
            "trade_count": metrics.trade_count,
            "fish_body_capture": metrics.fish_body_capture,
            "benchmark_return": metrics.benchmark_return,
        }
        if abs_mode and equity_curve and initial_capital >= 10_000:
            first_eq = equity_curve[0].equity
            last_eq = equity_curve[-1].equity
            if abs(last_eq - first_eq) > 1 and abs(metrics.total_return) < 0.01:
                report_metrics["total_return"] = round(
                    (last_eq - initial_capital) / initial_capital * 100, 2
                )
                report_metrics["annual_return"] = report_metrics["total_return"]
                peak = first_eq
                max_dd = 0.0
                for pt in equity_curve:
                    peak = max(peak, pt.equity)
                    if peak > 0:
                        max_dd = max(max_dd, (peak - pt.equity) / peak * 100)
                report_metrics["max_drawdown"] = round(max_dd, 2)

    return BacktestReport(
        run=BacktestRunOut.model_validate(run),
        strategy_name_cn=STRATEGY_LABELS.get(run.strategy_id, run.strategy_id),
        trade_mode_note=BACKTEST_TRADE_NOTE,
        metrics=report_metrics,
        equity_curve=equity_curve,
        stage_win_rates=metrics.extra.get("stage_win_rates", {}) if metrics else {},
    )


@router.get("/backtest/runs/{run_id}/trades", response_model=list[BacktestTradeOut])
async def backtest_trades(
    run_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(BacktestTrade)
            .where(BacktestTrade.run_id == run_id)
            .order_by(BacktestTrade.id)
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return [trade_to_out(r) for r in rows]


@router.delete("/backtest/runs/{run_id}")
async def delete_backtest(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    await db.delete(run)
    return {"deleted": run_id}


# ---------------------------------------------------------------------------
# A策略严格回测 (独立路由组，与上方 /backtest/* 共用 DB 表)
# ---------------------------------------------------------------------------

_A_BT_STRATEGY_ID = "a_strategy_strict"


async def _run_a_strategy_backtest_task(run_id: int) -> None:
    from app.services.backtest_context import clear_backtest_context, set_backtest_sector_codes
    from app.services.a_strategy_backtest_engine import AStrategyBacktestEngine

    async with AsyncSessionLocal() as session:
        run = await session.get(BacktestRun, run_id)
        try:
            if run:
                codes = list((run.params or {}).get("sector_codes") or [])
                set_backtest_sector_codes(codes)
            engine = AStrategyBacktestEngine(session)
            await engine.run(run_id)
            await session.commit()
        except Exception:
            await session.rollback()
            async with AsyncSessionLocal() as s2:
                run_fail = await s2.get(BacktestRun, run_id)
                if run_fail:
                    run_fail.status = "failed"
                    await s2.commit()
        finally:
            clear_backtest_context()


@router.post("/a-strategy-backtest/runs", response_model=BacktestRunOut)
async def create_a_strategy_backtest(
    body: BacktestCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    start_date, end_date = clamp_backtest_range(body.start_date, body.end_date)
    params = dict(body.params or {})
    codes = params.get("sector_codes") or []
    if not codes:
        raise HTTPException(400, "A策略回测请至少勾选一个板块")
    params.setdefault("initial_capital", 1_000_000)
    run = BacktestRun(
        strategy_id=_A_BT_STRATEGY_ID,
        start_date=start_date,
        end_date=end_date,
        params=params,
        status="pending",
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    background_tasks.add_task(_run_a_strategy_backtest_task, run.id)
    return BacktestRunOut.model_validate(run)


@router.get("/a-strategy-backtest/runs", response_model=list[BacktestRunOut])
async def list_a_strategy_backtest_runs(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(BacktestRun)
            .where(BacktestRun.strategy_id == _A_BT_STRATEGY_ID)
            .order_by(desc(BacktestRun.id))
            .limit(20)
        )
    ).scalars().all()
    return [BacktestRunOut.model_validate(r) for r in rows]


@router.get("/a-strategy-backtest/runs/{run_id}", response_model=BacktestRunOut)
async def get_a_strategy_backtest_run(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return BacktestRunOut.model_validate(run)


@router.get("/a-strategy-backtest/runs/{run_id}/report", response_model=BacktestReport)
async def a_strategy_backtest_report(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    metrics = (
        await db.execute(select(BacktestMetric).where(BacktestMetric.run_id == run_id))
    ).scalars().first()
    equity = (
        await db.execute(
            select(BacktestEquityDaily)
            .where(BacktestEquityDaily.run_id == run_id)
            .order_by(BacktestEquityDaily.trade_date)
        )
    ).scalars().all()

    params = run.params or {}
    initial_capital = float(params.get("initial_capital") or 1_000_000)
    bench_scale = initial_capital if initial_capital >= 10_000 else 1_000_000

    equity_curve: list[EquityPointOut] = []
    for e in equity:
        bench = float(e.benchmark_equity)
        if bench < 1000:
            bench *= bench_scale
        equity_curve.append(EquityPointOut(
            trade_date=str(e.trade_date),
            equity=e.equity,
            benchmark=bench,
        ))

    report_metrics = None
    if metrics:
        report_metrics = {
            "total_return": metrics.total_return,
            "annual_return": metrics.annual_return,
            "max_drawdown": metrics.max_drawdown,
            "sharpe": metrics.sharpe,
            "win_rate": metrics.win_rate,
            "trade_count": metrics.trade_count,
            "fish_body_capture": metrics.fish_body_capture,
            "benchmark_return": metrics.benchmark_return,
        }
        if equity_curve and initial_capital >= 10_000:
            first_eq = equity_curve[0].equity
            last_eq = equity_curve[-1].equity
            if abs(last_eq - first_eq) > 1 and abs(metrics.total_return) < 0.01:
                report_metrics["total_return"] = round(
                    (last_eq - initial_capital) / initial_capital * 100, 2
                )
                report_metrics["annual_return"] = report_metrics["total_return"]

    return BacktestReport(
        run=BacktestRunOut.model_validate(run),
        strategy_name_cn="A策略严格回测",
        trade_mode_note=(
            "回测标的为各概念板块的龙头个股。"
            "满足A策略6条硬性规则后，次日开盘价买入；"
            "退出信号触发或止损-8%时，次日开盘价卖出。"
        ),
        metrics=report_metrics,
        equity_curve=equity_curve,
        stage_win_rates=metrics.extra.get("stage_win_rates", {}) if metrics and metrics.extra else {},
    )


@router.get(
    "/a-strategy-backtest/runs/{run_id}/trades",
    response_model=list[BacktestTradeOut],
)
async def a_strategy_backtest_trades(
    run_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(BacktestTrade)
            .where(BacktestTrade.run_id == run_id)
            .order_by(BacktestTrade.id)
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return [trade_to_out(r) for r in rows]


@router.delete("/a-strategy-backtest/runs/{run_id}")
async def delete_a_strategy_backtest(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    await db.delete(run)
    return {"deleted": run_id}
