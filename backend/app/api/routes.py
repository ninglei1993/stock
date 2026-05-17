from datetime import date
from typing import Optional

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
)
from app.services.trade_calendar import (
    clamp_backtest_range,
    jq_data_end,
    jq_data_start,
    jq_range_label,
    latest_trade_day_in_range,
    resolve_scan_date,
    should_use_jq_bounds,
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


async def _latest_trade_date(session: AsyncSession) -> Optional[date]:
    row = (
        await session.execute(select(SectorScoreDaily.trade_date).order_by(desc(SectorScoreDaily.trade_date)).limit(1))
    ).scalar_one_or_none()
    return row


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
            "优先聚宽，其次 Tushare，否则演示",
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
        opt("demo", "演示数据", "本地合成，不消耗外部配额", True),
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
    info = adapter_info()
    scan = get_scan_task()
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
        scan_task=TaskStatusOut(**scan.to_dict()),
        jq_data_range=_jq_range_out(),
        default_scan_date=resolve_scan_date(),
    )


@router.get("/tasks/scan", response_model=TaskStatusOut)
async def scan_task_status():
    return TaskStatusOut(**get_scan_task().to_dict())


@router.get("/concepts", response_model=list[ConceptOut])
async def list_all_concepts():
    from app.services.concept_cache import get_cached_concepts

    concepts, _ = get_cached_concepts()
    return [ConceptOut(sector_code=c.code, sector_name=c.name) for c in concepts]


async def _run_scan(trade_date: date) -> None:
    from app.database import AsyncSessionLocal

    td_str = str(trade_date)
    start_scan(td_str, "正在入库概念板块行情…")
    try:
        async with AsyncSessionLocal() as session:
            ingestion = IngestionService(session)
            concepts = ingestion.adapter.list_concepts()
            total = len(concepts)
            if settings.ingest_max_concepts > 0:
                total = min(total, settings.ingest_max_concepts)
            update_scan_progress(0, total, f"正在入库 0/{total} 个概念…")
            await ingestion.ingest_day(trade_date)
            update_scan_progress(total, total, "正在计算五维评分与预警…")
            scanner = ScanService(session)
            scores = await scanner.run_scan(trade_date)
            await session.commit()
            finish_scan(len(scores), td_str)
    except Exception as exc:
        fail_scan(str(exc))
        raise


@router.post("/scan/latest")
async def scan_latest(
    background_tasks: BackgroundTasks,
    trade_date: Optional[date] = Query(None, description="扫描交易日，须在聚宽权限范围内"),
):
    trade_date = resolve_scan_date(trade_date)
    current = get_scan_task()
    if current.status == "running":
        return {
            "trade_date": str(trade_date),
            "status": "running",
            "message": "已有扫描任务在执行中，请稍候",
            "jq_data_range": jq_range_label() if should_use_jq_bounds() else None,
        }
    background_tasks.add_task(_run_scan, trade_date)
    start_scan(str(trade_date), f"收盘扫描已启动（交易日 {trade_date}）…")
    msg = f"正在扫描交易日 {trade_date}"
    if should_use_jq_bounds():
        msg += f"（聚宽权限 {jq_range_label()}）"
    return {
        "trade_date": str(trade_date),
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
    return {"trade_date": str(trade_date), "sectors_scored": len(scores)}


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(
    trade_date: Optional[date] = None, db: AsyncSession = Depends(get_db)
):
    td = trade_date or await _latest_trade_date(db)
    if not td:
        return DashboardOut(trade_date=None, market_env=None, top_sectors=[])

    env_row = await db.get(MarketEnvDaily, td)
    env_out = MarketEnvOut.model_validate(env_row) if env_row else None

    scores = (
        await db.execute(
            select(SectorScoreDaily)
            .where(SectorScoreDaily.trade_date == td)
            .order_by(SectorScoreDaily.rank)
            .limit(5)
        )
    ).scalars().all()

    leaders = (
        await db.execute(select(ThemeLeaderDaily).where(ThemeLeaderDaily.trade_date == td))
    ).scalars().all()
    leader_map = {l.sector_code: l for l in leaders}

    top = []
    for s in scores:
        l = leader_map.get(s.sector_code)
        top.append(
            SectorScoreOut(
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
            )
        )

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
    stocks = (
        await db.execute(
            select(StockDaily)
            .where(StockDaily.sector_code == sector_code, StockDaily.trade_date == td)
            .order_by(desc(StockDaily.pct_change))
            .limit(30)
        )
    ).scalars().all()

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
        stocks=[
            StockInSector(
                stock_code=s.stock_code,
                stock_name=resolve_stock_name(s.stock_code),
                pct_change=s.pct_change,
                is_limit_up=s.is_limit_up,
                limit_up_streak=s.limit_up_streak,
                money=s.money,
            )
            for s in stocks
        ],
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
