from datetime import date, timedelta
from typing import Optional

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
from app.services.sector_aggregator import SectorAggregator


class IngestionService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.adapter = get_adapter()
        self.aggregator = SectorAggregator(self.adapter)

    async def ingest_day(self, trade_date: date, max_concepts: Optional[int] = None) -> None:
        if max_concepts is None:
            max_concepts = settings.ingest_max_concepts
        concepts = self.adapter.list_concepts()
        if max_concepts > 0:
            concepts = concepts[:max_concepts]
        codes = [c.code for c in concepts]
        names = {c.code: c.name for c in concepts}

        index_bars = self.adapter.get_index_bars(
            "000300.XSHG",
            trade_date - timedelta(days=5),
            trade_date,
        )
        index_pct = index_bars[-1].pct_change if index_bars else 0.0

        breadth = self.adapter.get_market_breadth(trade_date)
        from app.services.risk import RiskModule

        env = RiskModule().compute_env(
            breadth.limit_up_count, breadth.up_down_ratio, index_pct
        )
        await self.session.merge(
            MarketEnvDaily(
                trade_date=trade_date,
                env_score=env.env_score,
                limit_up_count=env.limit_up_count,
                up_down_ratio=env.up_down_ratio,
                index_pct=env.index_pct,
                conclusion=env.conclusion,
                can_long=env.can_long,
            )
        )

        if self.adapter.__class__.__name__ == "DemoAdapter":
            quotes = self.adapter.get_sector_quotes(trade_date, codes)
        else:
            quotes = []
            for code in codes:
                q = self.aggregator.aggregate_sector(code, names[code], trade_date)
                quotes.append(q)

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

        for q in quotes:
            net, inflow_days = self.aggregator.aggregate_flow(q.sector_code, trade_date)
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

            stocks = self.adapter.get_concept_stocks(q.sector_code, trade_date)
            stock_quotes = self.adapter.get_stock_quotes(stocks, trade_date, q.sector_code)
            leader = self._pick_leader(stock_quotes)
            if leader:
                self.session.add(
                    ThemeLeaderDaily(
                        trade_date=trade_date,
                        sector_code=q.sector_code,
                        stock_code=leader.stock_code,
                        stock_name=leader.stock_code,
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

        await self.session.flush()

    def _pick_leader(self, quotes: list[StockQuote]) -> StockQuote | None:
        if not quotes:
            return None
        candidates = [q for q in quotes if q.is_limit_up or q.limit_up_streak > 0]
        pool = candidates or quotes
        return max(pool, key=lambda q: (q.limit_up_streak, q.money))

    async def backfill_range(
        self, start_date: date, end_date: date, max_concepts: Optional[int] = None
    ) -> int:
        days = self.adapter.get_trade_days(start_date, end_date)
        for d in days:
            await self.ingest_day(d, max_concepts=max_concepts)
        return len(days)
