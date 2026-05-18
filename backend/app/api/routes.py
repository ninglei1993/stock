from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
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
from app.config import settings
from app.api.backtest_helpers import trade_to_out
from app.labels import BACKTEST_TRADE_NOTE, STRATEGY_LABELS
from app.schemas.common import (
    AlertOut,
    BacktestCreate,
    BacktestReport,
    BacktestRunOut,
    BacktestTradeOut,
    DashboardOut,
    EquityPointOut,
    FlowDayOut,
    MarketEnvOut,
    ReviewDayOut,
    SectorDetailOut,
    ConceptOut,
    SectorListOut,
    SectorScoreOut,
    StockInSector,
    SystemStatusOut,
    TaskStatusOut,
    JqDataRangeOut,
    DataSourcesOut,
    DataSourceOptionOut,
    SetDataSourceIn,
    SetIngestSettingsIn,
    ScanSectorsOut,
    SetScanSectorsIn,
)
from app.services.trade_calendar import (
    clamp_backtest_range,
    jq_data_end,
    jq_data_start,
    jq_range_label,
    latest_trade_day_in_range,
    resolve_scan_date,
    resolve_scan_trade_days,
    should_use_jq_bounds,
    ui_default_scan_date,
    ui_default_scan_range,
)
from app.services.task_status import (
    fail_scan,
    finish_scan,
    get_scan_task,
    start_scan,
    update_scan_progress,
)
from app.services.stock_names import resolve_stock_name
from app.services.backtest_engine import BacktestEngine
from app.services.ingestion import IngestionService
from app.services.scan_service import ScanService

router = APIRouter(prefix="/api")

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

    by_key: dict[tuple[str, date], Any] = {}
    for r in rows:
        if getattr(r, "sector_code", None) != sector_code:
            continue
        by_key[(r.stock_code, r.trade_date)] = r

    anchor_rows = [r for (code, d), r in by_key.items() if d == trade_date]
    anchor_rows.sort(key=lambda r: r.pct_change, reverse=True)

    out: list[StockInSector] = []
    for s in anchor_rows[:limit]:
        hist = [
            StockPctDayOut(trade_date=d, pct_change=by_key[(s.stock_code, d)].pct_change)
            for d in display_days
            if (s.stock_code, d) in by_key
        ]
        out.append(
            StockInSector(
                stock_code=s.stock_code,
                stock_name=getattr(s, "stock_name", None) or resolve_stock_name(s.stock_code),
                pct_change=s.pct_change,
                pct_trade_date=trade_date,
                is_limit_up=s.is_limit_up,
                limit_up_streak=s.limit_up_streak,
                money=s.money,
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


async def _latest_trade_date(session: AsyncSession) -> Optional[date]:
    from app.services.volatile_scan import get_dashboard_snapshot

    snap = get_dashboard_snapshot()
    if snap is not None:
        return snap.trade_date

    row_db = (
        await session.execute(
            select(SectorScoreDaily.trade_date).order_by(desc(SectorScoreDaily.trade_date)).limit(1)
        )
    ).scalar_one_or_none()
    return row_db


def _sector_score_out(s, leader) -> SectorScoreOut:
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
        leader_stock_name=(
            (leader.stock_name or resolve_stock_name(leader.stock_code)) if leader else None
        ),
        leader_streak=leader.limit_up_streak if leader else None,
    )


@router.get("/health")
async def health():
    info = adapter_info()
    return {"status": "ok", "product": "ThemeRadar", **info}


@router.post("/system/reload-config")
async def reload_config():
    """修改 .env 后调用，重新加载聚宽连接与概念缓存（无需整容器重启）。"""
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


def _build_data_sources() -> DataSourcesOut:
    current = settings.effective_data_source()
    try:
        adapter_name = get_adapter().__class__.__name__
    except RuntimeError:
        adapter_name = "—"

    def opt(sid: str, label: str, desc: str, configured: bool) -> DataSourceOptionOut:
        return DataSourceOptionOut(
            id=sid,
            label=label,
            description=desc,
            configured=configured,
            active=current == sid,
        )

    options = [
        opt(
            "auto",
            "自动",
            "优先聚宽，其次 Tushare",
            settings.jq_configured() or settings.tushare_configured(),
        ),
        opt(
            "jqdata",
            "聚宽 JQData",
            "聚宽概念与行情（注意日配额）",
            settings.jq_configured(),
        ),
        opt(
            "tushare",
            "Tushare Pro",
            "同花顺概念板块（需 Token 与积分）",
            settings.tushare_configured(),
        ),
    ]
    return DataSourcesOut(current=current, active_adapter=adapter_name, options=options)


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


def _jq_range_out() -> Optional[JqDataRangeOut]:
    if not should_use_jq_bounds():
        return None
    return JqDataRangeOut(
        start=jq_data_start(),
        end=jq_data_end(),
        latest_trade_day=latest_trade_day_in_range(),
        label=jq_range_label(),
    )


@router.get("/system/data-sources", response_model=DataSourcesOut)
async def list_data_sources():
    return _build_data_sources()


@router.post("/system/data-source")
async def set_data_source(body: SetDataSourceIn):
    from app.services.data_source_store import VALID_SOURCES, write_override

    src = body.source.lower().strip()
    if src not in VALID_SOURCES:
        raise HTTPException(400, detail=f"无效数据源，可选: {', '.join(sorted(VALID_SOURCES))}")
    if src == "jqdata" and not settings.jq_configured():
        raise HTTPException(400, detail="未配置聚宽账号，请在 .env 设置 JQDATA_USERNAME/PASSWORD")
    if src == "tushare" and not settings.tushare_configured():
        raise HTTPException(400, detail="未配置 Tushare，请在 .env 设置 TUSHARE_TOKEN")
    if src == "demo":
        raise HTTPException(400, detail="演示数据已下线，请选择 Tushare 或聚宽")

    write_override(src)
    _reset_data_source_runtime()

    from app.services.concept_cache import get_cached_concepts

    try:
        adapter = get_adapter()
        concepts, _ = get_cached_concepts(force_refresh=True)
        info = adapter_info()
        return {
            "message": f"已切换数据源为 {src}",
            "adapter": adapter.__class__.__name__,
            "concepts": len(concepts),
            **info,
            "data_sources": _build_data_sources().model_dump(),
        }
    except RuntimeError as exc:
        raise HTTPException(502, detail=str(exc)) from exc


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
        demo_mode=info["demo_mode"],
        is_live_data=info.get("is_live_data", False),
        data_source_label=info.get("data_source_label", ""),
        data_source_short=info.get("data_source_short", ""),
        data_source=info.get("data_source", settings.effective_data_source()),
        jq_configured=info.get("jq_configured", settings.jq_configured()),
        tushare_configured=info.get("tushare_configured", settings.tushare_configured()),
        universe_total=info["universe_total"],
        ingest_max_concepts=settings.ingest_max_concepts,
        ingest_concept_filter=settings.ingest_concept_filter,
        scan_scope_label=resolve_scan_scope_label(),
        ingest_max_stocks_per_concept=effective_max_stocks_per_concept(),
        use_explicit_sector_selection=use_explicit,
        selected_sector_count=len(selected),
        scan_volatile_storage=settings.scan_volatile_storage,
        scan_task=TaskStatusOut(**scan.to_dict()),
        jq_data_range=_jq_range_out(),
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


@router.post("/system/clear-data")
async def clear_all_data(db: AsyncSession = Depends(get_db)):
    """清空缓存、内存快照与库内扫描/演示数据。"""
    from app.services.data_reset import (
        clear_demo_data_source_override,
        clear_runtime_caches,
        clear_scan_database,
    )

    clear_runtime_caches()
    migrated = clear_demo_data_source_override()
    counts = await clear_scan_database(db)
    _reset_data_source_runtime()
    return {
        "message": "已清空缓存与扫描数据",
        "data_source_migrated_to": migrated,
        "deleted": counts,
    }


@router.post("/system/ingest-settings")
async def set_ingest_settings(body: SetIngestSettingsIn):
    """设置每个板块最多分析的成分股数（0=全部）。写入 ingest_settings.override.json。"""
    from app.services.ingest_settings_store import write_max_stocks_override

    write_max_stocks_override(body.max_stocks_per_concept)
    return {
        "message": "入库参数已保存",
        "ingest_max_stocks_per_concept": body.max_stocks_per_concept,
    }


@router.get("/tasks/scan", response_model=TaskStatusOut)
async def scan_task_status():
    """查询后台扫盘任务进度（供前端轮询）。真正启动扫盘请用 POST /scan/latest。"""
    return TaskStatusOut(**get_scan_task().to_dict())


@router.get("/concepts", response_model=list[ConceptOut])
async def list_all_concepts():
    from app.services.concept_cache import get_cached_concepts

    concepts, _ = get_cached_concepts()
    return [ConceptOut(sector_code=c.code, sector_name=c.name) for c in concepts]


def _scan_concept_total() -> int:
    try:
        from app.services.concept_select import select_concepts_for_ingest

        adapter = get_adapter()
        selected = select_concepts_for_ingest(adapter.list_concepts())
        return max(len(selected), 1)
    except Exception:
        return max(settings.ingest_max_concepts, 1)


def _run_scan_sync(trade_days: list[date]) -> None:
    """
    在线程池执行扫盘。使用独立 asyncio 引擎/会话，避免与 Uvicorn 主事件循环冲突。
    支持多日：按交易日顺序依次 ingest + 评分，最终以最后一日的快照更新仪表盘。
    """
    import asyncio
    import logging

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.config import settings

    if not trade_days:
        return
    last_td = trade_days[-1]
    td_str = str(last_td)
    concepts_per_day = _scan_concept_total()
    # 每日步骤：+1 准备/环境、+N 各概念、+1 五维评分、+1 提交完成 = N+3
    OVERHEAD_PER_DAY = 3
    steps_per_day = concepts_per_day + OVERHEAD_PER_DAY
    total = steps_per_day * len(trade_days)
    n_days = len(trade_days)
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
            "[数据] _run_scan_sync 开始 交易日(升序)=%s concepts_per_day=%d steps_per_day=%d total=%d",
            [str(d) for d in trade_days],
            concepts_per_day,
            steps_per_day,
            total,
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

                for day_idx, trade_date in enumerate(trade_days):
                    day_offset = day_idx * steps_per_day
                    day_label = f"[{day_idx + 1}/{n_days}] {trade_date}"

                    # 步骤 0：准备环境（概念列表 + 大盘数据）
                    update_scan_progress(
                        day_offset,
                        total,
                        f"{day_label} 拉取概念列表与大盘数据…",
                        current_trade_date=str(trade_date),
                    )

                    def _make_on_progress(
                        d_offset: int, td: date, d_idx: int
                    ):
                        def on_progress(
                            done: int, concept_total: int, label: str = ""
                        ) -> None:
                            # done=0 来自 ingest_day 初始"大盘环境"调用
                            # done=1..N 来自各概念逐个完成
                            step = d_offset + 1 + done  # +1 跳过步骤0（准备）
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
                    await ingestion.ingest_day(trade_date, on_progress=on_progress)
                    log.info(
                        "[数据] ingest_day 完成 trade_date=%s 耗时=%.2fs",
                        trade_date,
                        time.monotonic() - ingest_t0,
                    )

                    # 步骤 N+2：五维评分
                    update_scan_progress(
                        day_offset + 1 + concepts_per_day,
                        total,
                        f"{day_label} 五维评分与预警…",
                        current_trade_date=str(trade_date),
                    )
                    scanner = ScanService(session)
                    day_scores = await scanner.run_scan(trade_date)
                    scores = day_scores
                    if settings.scan_volatile_storage:
                        from app.services.volatile_scan import get_today_buffer

                        buf_day = get_today_buffer()
                        if buf_day is not None:
                            buf_day.scores_by_date[trade_date] = list(day_scores)
                    if not settings.scan_volatile_storage:
                        await session.commit()

                    # 步骤 N+3：本日完成
                    update_scan_progress(
                        day_offset + steps_per_day,
                        total,
                        f"{day_label} 完成",
                        current_trade_date=str(trade_date),
                    )

                score_phase_t0 = tracker.start_phase(
                    "theme_score",
                    "五维评分与预警",
                    f"共 {len(trade_days)} 个交易日评分完成",
                )
                tracker.end_phase(
                    "theme_score",
                    "五维评分与预警",
                    "最终以最近交易日更新仪表盘",
                    score_phase_t0,
                    extra=f"{len(scores)}个板块 @ {last_td}",
                )
                if settings.scan_volatile_storage:
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

                    env_for_dash = buf_r.market_env if buf_r else None
                    lm = dict(buf_r.leaders_by_code) if buf_r else {}
                    if buf_r:
                        lm = {
                            code: leader
                            for code, leader in buf_r.leaders_by_code.items()
                            if getattr(leader, "trade_date", None) == last_td
                        }
                    set_dashboard_snapshot(
                        VolatileDashboardSnapshot(
                            trade_date=last_td,
                            env=env_for_dash,
                            scores=list(scores),
                            leader_map=lm,
                            scan_trade_days=list(trade_days),
                        )
                    )
                    await session.rollback()
                    log.info(
                        "[数据] volatile：已发布内存快照 trade_date=%s scores=%d PostgreSQL rollback",
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
            "jq_data_range": jq_range_label() if should_use_jq_bounds() else None,
        }
    concepts_count = _scan_concept_total()
    total = (concepts_count + 3) * len(trade_days)
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
    if should_use_jq_bounds():
        msg += f"（聚宽权限 {jq_range_label()}）"
    return {
        "trade_date": str(last_td),
        "start_date": str(trade_days[0]),
        "end_date": str(last_td),
        "trade_days": [str(d) for d in trade_days],
        "status": "started",
        "message": msg,
        "jq_data_range": jq_range_label() if should_use_jq_bounds() else None,
    }


@router.post("/scan/{trade_date}")
async def trigger_scan(trade_date: date, db: AsyncSession = Depends(get_db)):
    trade_date = resolve_scan_date(trade_date)
    ingestion = IngestionService(db)
    await ingestion.ingest_day(trade_date)
    scanner = ScanService(db)
    scores = await scanner.run_scan(trade_date)

    if settings.scan_volatile_storage:
        from app.services.volatile_scan import (
            VolatileDashboardSnapshot,
            get_today_buffer,
            set_dashboard_snapshot,
        )

        buf = get_today_buffer()
        lm = dict(buf.leaders_by_code) if buf else {}
        set_dashboard_snapshot(
            VolatileDashboardSnapshot(
                trade_date=trade_date,
                env=(buf.market_env if buf else None),
                scores=list(scores),
                leader_map=lm,
            )
        )
        await db.rollback()

    return {"trade_date": str(trade_date), "sectors_scored": len(scores)}


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(
    trade_date: Optional[date] = None, db: AsyncSession = Depends(get_db)
):
    td = trade_date or await _latest_trade_date(db)
    if not td:
        return DashboardOut(trade_date=None, market_env=None, top_sectors=[])

    if settings.scan_volatile_storage:
        from app.services.volatile_scan import get_dashboard_snapshot

        snap = get_dashboard_snapshot()
        snap_td = snap.trade_date if snap else None
        snap_days = list(snap.scan_trade_days) if snap and snap.scan_trade_days else []
        use_snap = snap and (
            td == snap_td or (snap_days and td in snap_days) or td is None
        )
        if use_snap:
            anchor = snap_td or td
            env_out = MarketEnvOut.model_validate(snap.env) if snap.env else None
            leaders = snap.leader_map
            top: list[SectorScoreOut] = []
            scored = sorted(snap.scores, key=lambda x: x.rank)
            for s in scored:
                l = leaders.get(s.sector_code)
                top.append(_sector_score_out(s, l))
            return DashboardOut(trade_date=anchor, market_env=env_out, top_sectors=top)

    env_row = await db.get(MarketEnvDaily, td)
    env_out = MarketEnvOut.model_validate(env_row) if env_row else None

    scores = (
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

    top = [_sector_score_out(s, leader_map.get(s.sector_code)) for s in scores]

    return DashboardOut(trade_date=td, market_env=env_out, top_sectors=top)


@router.get("/alerts", response_model=list[AlertOut])
async def list_alerts(
    trade_date: Optional[date] = None,
    alert_code: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    td = trade_date or await _latest_trade_date(db)
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

    td = trade_date or await _latest_trade_date(db)
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

    def _score_out(s: SectorScoreDaily) -> SectorScoreOut:
        l = leader_map.get(s.sector_code)
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
            leader_stock=l.stock_code if l else None,
            leader_streak=l.limit_up_streak if l else None,
            pct_change=pct_map.get(s.sector_code),
            is_filtered=s.is_filtered,
            filter_reason=s.filter_reason,
            is_scored=True,
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
        demo_mode=info["demo_mode"],
        is_live_data=info.get("is_live_data", False),
        data_source=info["adapter"],
        data_source_label=info.get("data_source_label", ""),
        data_source_short=info.get("data_source_short", ""),
        jq_configured=info["jq_configured"],
        sectors=sectors,
    )


@router.get("/sectors/{sector_code}", response_model=SectorDetailOut)
async def sector_detail(
    sector_code: str,
    trade_date: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
):
    td = trade_date or await _latest_trade_date(db)
    if not td:
        raise HTTPException(404, "No data")

    if settings.scan_volatile_storage:
        from app.services.volatile_scan import get_dashboard_snapshot, get_today_buffer

        snap = get_dashboard_snapshot()
        buf = get_today_buffer()
        snap_days = list(snap.scan_trade_days) if snap and snap.scan_trade_days else []
        buf_ok = buf is not None and (
            buf.trade_date == td or any(getattr(r, "trade_date", None) == td for r in buf.stocks)
        )
        if snap and (td == snap.trade_date or td in snap_days) and buf_ok:
            score_row = next(
                (s for s in snap.scores if s.sector_code == sector_code), None
            )
            if score_row:
                daily = buf.sectors_by_code.get(sector_code)
                flow = buf.flows_by_code.get(sector_code)
                leader = buf.leaders_by_code.get(sector_code)
                scan_days = list(snap.scan_trade_days) if snap.scan_trade_days else [td]
                display_days = _pct_display_days(td, scan_days)
                stock_models = _build_stocks_in_sector(
                    sector_code, td, buf.stocks, display_days
                )
                stock_models = _backfill_pct_history(
                    stock_models, display_days, anchor=td
                )
                from app.schemas.common import ScoreDimensionOut

                dim_defs = [
                    ("persistence", "持续性", 25, score_row.persistence_score, ""),
                    ("capital", "资金", 30, score_row.capital_score, ""),
                    ("breadth", "广度", 25, score_row.breadth_score, ""),
                    ("leader", "龙头", 15, score_row.leader_score, ""),
                    ("relative", "相对强度", 5, score_row.relative_score, ""),
                ]
                score_dimensions = [
                    ScoreDimensionOut(
                        key=k, label=label, weight_pct=w, score=s, description=desc
                    )
                    for k, label, w, s, desc in dim_defs
                ]
                net_wan = flow.net_inflow_main if flow else 0.0
                up_c = daily.up_count if daily else 0
                tot_c = daily.total_count if daily else 1
                return SectorDetailOut(
                    sector_code=sector_code,
                    sector_name=score_row.sector_name,
                    trade_date=td,
                    pct_display_days=display_days,
                    stage=score_row.stage,
                    total_score=score_row.total_score,
                    scores={
                        "persistence": score_row.persistence_score,
                        "capital": score_row.capital_score,
                        "breadth": score_row.breadth_score,
                        "leader": score_row.leader_score,
                        "relative": score_row.relative_score,
                    },
                    score_dimensions=score_dimensions,
                    limit_up_count=daily.limit_up_count if daily else 0,
                    big_yang_count=daily.big_yang_count if daily else 0,
                    net_inflow_main=net_wan,
                    net_inflow_yi=round(net_wan / 10000, 2),
                    inflow_days=flow.inflow_days if flow else 0,
                    up_count=up_c,
                    total_count=tot_c,
                    up_ratio=round(up_c / tot_c, 4) if tot_c else 0,
                    blow_up_rate=daily.blow_up_rate if daily else 0,
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
        sector_code, td, list(stock_rows_multi), display_days
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

    from app.schemas.common import ScoreDimensionOut

    dim_defs = [
        ("persistence", "持续性", 25, score.persistence_score, "近3日板块涨幅排名、连续强势天数"),
        ("capital", "资金", 30, score.capital_score, "主力净流入连续天数、流入强度"),
        ("breadth", "广度", 25, score.breadth_score, "涨停家数、大阳线数量、上涨占比"),
        ("leader", "龙头", 15, score.leader_score, "连板高度、龙头涨幅与成交额占比"),
        ("relative", "相对强度", 5, score.relative_score, "相对沪深300超额收益"),
    ]
    score_dimensions = [
        ScoreDimensionOut(
            key=k, label=label, weight_pct=w, score=s, description=desc
        )
        for k, label, w, s, desc in dim_defs
    ]
    net_wan = flow.net_inflow_main if flow else 0.0
    up_c = daily.up_count if daily else 0
    tot_c = daily.total_count if daily else 1

    return SectorDetailOut(
        sector_code=sector_code,
        sector_name=score.sector_name,
        trade_date=td,
        pct_display_days=display_days,
        stage=score.stage,
        total_score=score.total_score,
        scores={
            "persistence": score.persistence_score,
            "capital": score.capital_score,
            "breadth": score.breadth_score,
            "leader": score.leader_score,
            "relative": score.relative_score,
        },
        score_dimensions=score_dimensions,
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


async def _run_backtest_task(run_id: int) -> None:
    async with AsyncSessionLocal() as session:
        engine = BacktestEngine(session)
        try:
            await engine.run(run_id)
            await session.commit()
        except Exception:
            await session.rollback()
            async with AsyncSessionLocal() as s2:
                run = await s2.get(BacktestRun, run_id)
                if run:
                    run.status = "failed"
                    await s2.commit()


@router.post("/backtest/runs", response_model=BacktestRunOut)
async def create_backtest(
    body: BacktestCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    start_date, end_date = clamp_backtest_range(body.start_date, body.end_date)
    run = BacktestRun(
        strategy_id=body.strategy_id,
        start_date=start_date,
        end_date=end_date,
        params=body.params,
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
    return BacktestReport(
        run=BacktestRunOut.model_validate(run),
        strategy_name_cn=STRATEGY_LABELS.get(run.strategy_id, run.strategy_id),
        trade_mode_note=BACKTEST_TRADE_NOTE,
        metrics={
            "total_return": metrics.total_return,
            "annual_return": metrics.annual_return,
            "max_drawdown": metrics.max_drawdown,
            "sharpe": metrics.sharpe,
            "win_rate": metrics.win_rate,
            "trade_count": metrics.trade_count,
            "fish_body_capture": metrics.fish_body_capture,
            "benchmark_return": metrics.benchmark_return,
        }
        if metrics
        else None,
        equity_curve=[
            EquityPointOut(
                trade_date=str(e.trade_date),
                equity=e.equity,
                benchmark=e.benchmark_equity,
            )
            for e in equity
        ],
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
