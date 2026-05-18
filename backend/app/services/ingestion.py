from datetime import date, timedelta
from typing import Callable, Optional

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.factory import get_adapter
from app.config import settings
from app.adapters.base import StockQuote
from app.models.tables import (
    MarketEnvDaily,
    SectorDaily,
    SectorFlowDaily,
    StockDaily,
    ThemeLeaderDaily,
)
from app.services.concept_select import select_concepts_for_ingest
from app.services.ingest_settings_store import (
    effective_max_stocks_per_concept,
    read_scan_sectors_selection,
)
from app.services.scan_pipeline import ScanPipelineTracker, get_tracker
from app.services.sector_aggregator import SectorAggregator
from app.services.stock_select import limit_stocks_for_ingest
from app.services.stock_names import resolve_stock_name
from app.services.volatile_scan import get_today_buffer, prepare_today_buffer
from app.utils.timing_log import log_elapsed

import logging

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.adapter = get_adapter()
        self.aggregator = SectorAggregator(self.adapter)

    async def ingest_day(
        self,
        trade_date: date,
        max_concepts: Optional[int] = None,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> None:
        with log_elapsed("拉取同花顺概念板块列表", logger_obj=logger):
            all_concepts = self.adapter.list_concepts()
        concepts = select_concepts_for_ingest(
            all_concepts,
            max_concepts=max_concepts,
        )
        if not concepts:
            use_explicit, _ = read_scan_sectors_selection()
            if use_explicit:
                raise RuntimeError(
                    "未勾选任何扫描板块：请在仪表盘「扫描板块」中至少勾选一个概念后再扫描"
                )
            raise RuntimeError(
                f"未匹配到概念（筛选词: {settings.ingest_concept_filter or '无'}）"
            )

        tracker = get_tracker()
        if tracker is None:
            tracker = ScanPipelineTracker(
                trade_date=str(trade_date),
                adapter=self.adapter.__class__.__name__,
                concept_count=len(concepts),
            )
        else:
            tracker.concept_count = len(concepts)
        tracker.log_plan()
        max_stocks_cfg = effective_max_stocks_per_concept()
        logger.info(
            "[数据] ingest_day 开始 trade_date=%s concepts=%d adapter=%s "
            "filter=%r max_stocks_per_concept=%d flow_lookback=%d price_lookback=%d volatile_storage=%s",
            trade_date,
            len(concepts),
            self.adapter.__class__.__name__,
            settings.ingest_concept_filter or "(none)",
            max_stocks_cfg,
            settings.ingest_flow_lookback_days,
            settings.ingest_price_lookback_days,
            settings.scan_volatile_storage,
        )
        if settings.scan_volatile_storage:
            from app.services.scan_context import get_allowed_trade_days

            allowed = get_allowed_trade_days()
            append = (
                allowed is not None
                and len(allowed) > 1
                and get_today_buffer() is not None
            )
            prepare_today_buffer(trade_date, append=append)
        codes = [c.code for c in concepts]
        names = {c.code: c.name for c in concepts}
        concept_total = len(codes)

        if on_progress:
            on_progress(0, concept_total, "大盘环境与沪深300")

        env_t0 = tracker.start_phase(
            "market_env",
            "大盘环境",
            "拉取沪深300近几日走势，并统计全市场涨跌家数、涨停家数（用于环境得分）",
        )
        from app.services.scan_context import get_allowed_trade_days

        allowed = get_allowed_trade_days()
        if allowed:
            prior = [d for d in allowed if d <= trade_date]
            index_start = prior[max(0, len(prior) - 6)] if prior else trade_date
        else:
            index_start = trade_date - timedelta(days=5)
        with log_elapsed("大盘环境 index_bars+market_breadth", logger_obj=logger):
            index_bars = self.adapter.get_index_bars(
                "000300.XSHG",
                index_start,
                trade_date,
            )
            index_pct = index_bars[-1].pct_change if index_bars else 0.0
            breadth = self.adapter.get_market_breadth(trade_date)
            from app.services.risk import RiskModule

            env = RiskModule().compute_env(
                breadth.limit_up_count, breadth.up_down_ratio, index_pct
            )
            env_row = MarketEnvDaily(
                trade_date=trade_date,
                env_score=env.env_score,
                limit_up_count=env.limit_up_count,
                up_down_ratio=env.up_down_ratio,
                index_pct=env.index_pct,
                conclusion=env.conclusion,
                can_long=env.can_long,
            )
            if settings.scan_volatile_storage:
                buf = get_today_buffer()
                if buf is None:
                    raise RuntimeError("volatile buffer 未初始化")
                buf.market_env = env_row
                logger.info(
                    "[数据] market_env_daily 仅存内存 volatile env_score=%.1f limit_up=%d",
                    env.env_score,
                    env.limit_up_count,
                )
            else:
                await self.session.merge(env_row)
                logger.info(
                    "[数据] market_env_daily 已写入 env_score=%.1f limit_up=%d",
                    env.env_score,
                    env.limit_up_count,
                )
        tracker.end_phase(
            "market_env",
            "大盘环境",
            f"{trade_date} 沪深300与全市场广度已就绪",
            env_t0,
            extra=f"涨停{env.limit_up_count}家 环境分{env.env_score:.0f}",
        )

        with log_elapsed(
            ("清理当日旧行情数据（已跳过volatile）")
            if settings.scan_volatile_storage
            else "清理当日旧行情数据",
            logger_obj=logger,
        ):
            if not settings.scan_volatile_storage:
                await self.session.execute(
                    delete(SectorDaily).where(SectorDaily.trade_date == trade_date)
                )
                await self.session.execute(
                    delete(SectorFlowDaily).where(SectorFlowDaily.trade_date == trade_date)
                )
                await self.session.execute(
                    delete(StockDaily).where(StockDaily.trade_date == trade_date)
                )
                await self.session.execute(
                    delete(ThemeLeaderDaily).where(ThemeLeaderDaily.trade_date == trade_date)
                )
            else:
                logger.info("[数据] volatile 模式：跳过 PostgreSQL 当日 DELETE")

        prefetch_fn = getattr(self.adapter, "prefetch_shared_market_data", None)
        if prefetch_fn is not None:
            pf_t0 = tracker.start_phase(
                "prefetch",
                "预取全市场公有数据",
                f"{trade_date} 按交易日批量拉取全市场日线、涨跌停价、主力资金流",
            )
            stats = prefetch_fn(
                trade_date,
                settings.ingest_flow_lookback_days,
                settings.ingest_price_lookback_days,
            )
            tracker.end_phase(
                "prefetch",
                "预取全市场公有数据",
                f"{trade_date} 后续各板块从缓存筛选，不再重复拉全市场表",
                pf_t0,
                extra=f"{stats.get('trade_days', 0)}个交易日",
            )

        if self.adapter.__class__.__name__ == "DemoAdapter":
            quotes = self.adapter.get_sector_quotes(trade_date, codes)
            for q in quotes:
                net, inflow_days = self.aggregator.aggregate_flow(q.sector_code, trade_date)
                stocks = self.adapter.get_concept_stocks(q.sector_code, trade_date)
                stock_quotes = self.adapter.get_stock_quotes(stocks, trade_date, q.sector_code)
                await self._persist_sector_bundle(trade_date, q, net, inflow_days, stock_quotes)
            if settings.scan_volatile_storage:
                logger.info("[数据] Demo volatile：跳过 flush")
            else:
                await self.session.flush()
            return

        # 实盘源：每个概念只拉一次成分股 + 从缓存筛行情/资金流
        total = len(codes)
        done = 0
        concepts_t0 = tracker.start_phase(
            "concepts_loop",
            "逐板块分析",
            f"共 {total} 个概念：拉成分股 → 筛 TopN → 从缓存取资金流/行情 → 写入",
        )
        for code in codes:
            label = names.get(code, code)
            if on_progress:
                on_progress(done, total, label)
            with log_elapsed(
                f"概念板块 [{label}]",
                logger_obj=logger,
                extra=f"code={code}",
            ):
                stocks = self.adapter.get_concept_stocks(code, trade_date)
                max_stocks = effective_max_stocks_per_concept()
                if max_stocks > 0 and stocks:
                    before = len(stocks)
                    with log_elapsed(
                        f"成分股筛选 Top{max_stocks}",
                        logger_obj=logger,
                        extra=f"{before}只→",
                    ):
                        stocks = limit_stocks_for_ingest(
                            self.adapter, stocks, trade_date, max_stocks
                        )
                    logger.info(
                        "[数据] 成分股限制 %d -> %d (max=%d)",
                        before,
                        len(stocks),
                        max_stocks,
                    )
                logger.info("[数据] 待分析成分股 count=%d", len(stocks))
                if not stocks:
                    with log_elapsed("板块聚合+入库(空成分股)", logger_obj=logger):
                        q = self.aggregator.aggregate_sector_from_quotes(
                            code, names[code], []
                        )
                        await self._persist_sector_bundle(
                            trade_date, q, 0.0, 0, []
                        )
                    logger.warning(
                        "[数据] 概念 %s 无可用成分股，已写入空板块记录避免仪表盘丢失",
                        label,
                    )
                    done += 1
                    if on_progress:
                        on_progress(done, total, label)
                    continue
                with log_elapsed(
                    "get_capital_flows",
                    logger_obj=logger,
                    extra=f"stocks={len(stocks)}",
                ):
                    flows = self.adapter.get_capital_flows(
                        stocks,
                        trade_date,
                        lookback=settings.ingest_flow_lookback_days,
                    )
                with log_elapsed(
                    "get_stock_quotes",
                    logger_obj=logger,
                    extra=f"stocks={len(stocks)}",
                ):
                    stock_quotes = self.adapter.get_stock_quotes(
                        stocks,
                        trade_date,
                        code,
                        price_lookback_days=settings.ingest_price_lookback_days,
                        capital_flows=flows,
                    )
                with log_elapsed("板块聚合+入库", logger_obj=logger):
                    q = self.aggregator.aggregate_sector_from_quotes(
                        code, names[code], stock_quotes
                    )
                    net, inflow_days = self.aggregator.aggregate_flow_from_flows(flows)
                    await self._persist_sector_bundle(
                        trade_date, q, net, inflow_days, stock_quotes
                    )
                logger.info(
                    "[数据] 概念入库完成 %s pct=%.2f limit_up=%d stocks_saved=%d net_inflow=%.0f",
                    label,
                    q.pct_change,
                    q.limit_up_count,
                    len(stock_quotes),
                    net,
                )
            done += 1
            if on_progress:
                on_progress(done, total, label)

        tracker.end_phase(
            "concepts_loop",
            "逐板块分析",
            f"已完成 {total} 个概念板块的数据聚合与写入",
            concepts_t0,
            extra=f"每板块≤{max_stocks_cfg}只" if max_stocks_cfg > 0 else "全成分股",
        )

        flush_t0 = tracker.start_phase(
            "flush",
            "刷写数据",
            "将内存中的板块/个股数据提交到数据库（volatile 模式则跳过）",
        )
        with log_elapsed("ingest_day flush", logger_obj=logger):
            if settings.scan_volatile_storage:
                logger.info("[数据] volatile：跳过 Session.flush（无 PostgreSQL 写入）")
            else:
                await self.session.flush()
        tracker.end_phase(
            "flush",
            "刷写数据",
            "入库阶段数据已落盘或保留在内存快照",
            flush_t0,
        )
        logger.info("[数据] ingest_day 全部完成 trade_date=%s concepts=%d", trade_date, concept_total)

    async def _persist_sector_bundle(
        self,
        trade_date: date,
        q,
        net: float,
        inflow_days: int,
        stock_quotes: list[StockQuote],
    ) -> None:
        if settings.scan_volatile_storage:
            await self._persist_sector_bundle_volatile(
                trade_date, q, net, inflow_days, stock_quotes
            )
            return

        self.session.add(
            SectorDaily(
                trade_date=trade_date,
                sector_code=q.sector_code,
                sector_name=q.sector_name,
                pct_change=q.pct_change,
                open=q.open,
                close=q.close,
                high=q.high,
                low=q.low,
                volume=q.volume,
                money=q.money,
                limit_up_count=q.limit_up_count,
                big_yang_count=q.big_yang_count,
                up_count=q.up_count,
                total_count=q.total_count,
                blow_up_rate=q.blow_up_rate,
            )
        )
        self.session.add(
            SectorFlowDaily(
                trade_date=trade_date,
                sector_code=q.sector_code,
                net_inflow_main=net,
                inflow_days=inflow_days,
            )
        )

        if not stock_quotes and self.adapter.__class__.__name__ != "DemoAdapter":
            stocks = self.adapter.get_concept_stocks(q.sector_code, trade_date)
            stock_quotes = self.adapter.get_stock_quotes(stocks, trade_date, q.sector_code)

        leader = self._pick_leader(stock_quotes)
        if leader:
            self.session.add(
                ThemeLeaderDaily(
                    trade_date=trade_date,
                    sector_code=q.sector_code,
                    stock_code=leader.stock_code,
                    stock_name=resolve_stock_name(leader.stock_code),
                    limit_up_streak=leader.limit_up_streak,
                    pct_change=leader.pct_change,
                    money=leader.money,
                )
            )
        for sq in stock_quotes:
            self.session.add(
                StockDaily(
                    trade_date=trade_date,
                    stock_code=sq.stock_code,
                    sector_code=q.sector_code,
                    open=sq.open,
                    close=sq.close,
                    high=sq.high,
                    low=sq.low,
                    pct_change=sq.pct_change,
                    volume=sq.volume,
                    money=sq.money,
                    is_limit_up=sq.is_limit_up,
                    is_big_yang=sq.is_big_yang,
                    is_blow_up=sq.is_blow_up,
                    limit_up_streak=sq.limit_up_streak,
                )
            )

    async def _persist_sector_bundle_volatile(
        self,
        trade_date: date,
        q,
        net: float,
        inflow_days: int,
        stock_quotes: list[StockQuote],
    ) -> None:
        buf = get_today_buffer()
        if buf is None:
            raise RuntimeError("volatile buffer 缺失，无法写入板块快照")

        sq_for_leader = list(stock_quotes)
        if not stock_quotes and self.adapter.__class__.__name__ != "DemoAdapter":
            stocks_reload = self.adapter.get_concept_stocks(q.sector_code, trade_date)
            sq_for_leader = list(
                self.adapter.get_stock_quotes(stocks_reload, trade_date, q.sector_code)
            )

        buf.sectors_by_code[q.sector_code] = SectorDaily(
            trade_date=trade_date,
            sector_code=q.sector_code,
            sector_name=q.sector_name,
            pct_change=q.pct_change,
            open=q.open,
            close=q.close,
            high=q.high,
            low=q.low,
            volume=q.volume,
            money=q.money,
            limit_up_count=q.limit_up_count,
            big_yang_count=q.big_yang_count,
            up_count=q.up_count,
            total_count=q.total_count,
            blow_up_rate=q.blow_up_rate,
        )
        buf.flows_by_code[q.sector_code] = SectorFlowDaily(
            trade_date=trade_date,
            sector_code=q.sector_code,
            net_inflow_main=net,
            inflow_days=inflow_days,
        )
        leader = self._pick_leader(sq_for_leader)
        if leader:
            buf.leaders_by_code[q.sector_code] = ThemeLeaderDaily(
                trade_date=trade_date,
                sector_code=q.sector_code,
                stock_code=leader.stock_code,
                stock_name=resolve_stock_name(leader.stock_code),
                limit_up_streak=leader.limit_up_streak,
                pct_change=leader.pct_change,
                money=leader.money,
            )
        else:
            buf.leaders_by_code.pop(q.sector_code, None)

        buf.stocks[:] = [
            r
            for r in buf.stocks
            if not (r.trade_date == trade_date and r.sector_code == q.sector_code)
        ]
        for sq in sq_for_leader:
            buf.stocks.append(
                StockDaily(
                    trade_date=trade_date,
                    stock_code=sq.stock_code,
                    sector_code=q.sector_code,
                    open=sq.open,
                    close=sq.close,
                    high=sq.high,
                    low=sq.low,
                    pct_change=sq.pct_change,
                    volume=sq.volume,
                    money=sq.money,
                    is_limit_up=sq.is_limit_up,
                    is_big_yang=sq.is_big_yang,
                    is_blow_up=sq.is_blow_up,
                    limit_up_streak=sq.limit_up_streak,
                )
            )

    def _pick_leader(self, quotes: list[StockQuote]) -> StockQuote | None:
        if not quotes:
            return None
        candidates = [q for q in quotes if q.is_limit_up or q.limit_up_streak > 0]
        pool = candidates or quotes
        return max(
            pool,
            key=lambda q: (q.limit_up_streak, q.money, q.pct_change),
        )

    async def backfill_range(
        self, start_date: date, end_date: date, max_concepts: Optional[int] = None
    ) -> int:
        days = self.adapter.get_trade_days(start_date, end_date)
        for d in days:
            await self.ingest_day(d, max_concepts=max_concepts)
        return len(days)
