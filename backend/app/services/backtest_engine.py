from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.factory import get_adapter
from app.labels import TRADE_MODE_LEADER_STOCK
from app.models.tables import (
    Alert,
    BacktestEquityDaily,
    BacktestMetric,
    BacktestRun,
    BacktestTrade,
    MarketEnvDaily,
    SectorScoreDaily,
    ThemeLeaderDaily,
)
from app.services.ingestion import IngestionService
from app.services.scan_service import ScanService
from app.services.stock_names import resolve_stock_name


class BacktestEngine:
    COMMISSION = 0.00025
    STAMP_TAX = 0.001
    SLIPPAGE = 0.001

    def __init__(self, session: AsyncSession):
        self.session = session
        self.adapter = get_adapter()
        self._trade_days_cache: list[date] = []

    async def run(self, run_id: int) -> None:
        run = await self.session.get(BacktestRun, run_id)
        if not run:
            return
        run.status = "running"
        await self.session.flush()

        try:
            days = self.adapter.get_trade_days(run.start_date, run.end_date)
            self._trade_days_cache = days
            run.total_days = len(days)
            await self.session.flush()

            ingestion = IngestionService(self.session)
            scanner = ScanService(self.session)

            equity = 1.0
            benchmark = 1.0
            positions: dict[str, dict[str, Any]] = {}
            trades: list[BacktestTrade] = []

            index_bars = {
                b.trade_date: b
                for b in self.adapter.get_index_bars("000300.XSHG", run.start_date, run.end_date)
            }

            for i, td in enumerate(days):
                await ingestion.ingest_day(td)
                await scanner.run_scan(td)
                run.progress = i + 1
                await self.session.flush()

                alerts = (
                    await self.session.execute(
                        select(Alert).where(Alert.trade_date == td)
                    )
                ).scalars().all()
                env = await self.session.get(MarketEnvDaily, td)
                scores = (
                    await self.session.execute(
                        select(SectorScoreDaily).where(SectorScoreDaily.trade_date == td)
                    )
                ).scalars().all()
                score_map = {s.sector_code: s for s in scores}

                next_day = days[i + 1] if i + 1 < len(days) else None

                for alert in alerts:
                    if alert.alert_code in ("ENV_BAD",):
                        continue
                    sector = score_map.get(alert.sector_code)
                    if not sector:
                        continue

                    if self._should_buy(run.strategy_id, alert.alert_code, sector, env):
                        if alert.sector_code in positions:
                            continue
                        if len(positions) >= run.params.get("max_positions", 3):
                            continue
                        if env and not env.can_long and run.strategy_id != "fixed_hold":
                            continue
                        price = await self._entry_price(alert.sector_code, td, next_day)
                        if price is None:
                            continue
                        leader_code, leader_name = await self._leader_with_name(
                            td, alert.sector_code
                        )
                        positions[alert.sector_code] = {
                            "signal_date": td,
                            "entry_date": next_day or td,
                            "entry_price": price,
                            "sector_name": alert.sector_name,
                            "stock_code": leader_code,
                            "stock_name": leader_name,
                            "alert_code": alert.alert_code,
                            "reason": alert.human_reason,
                            "stage": sector.stage,
                        }

                    if self._should_sell(run.strategy_id, alert.alert_code, sector):
                        pos = positions.pop(alert.sector_code, None)
                        if pos and next_day:
                            exit_price = await self._entry_price(
                                alert.sector_code, td, next_day
                            )
                            if exit_price:
                                ret = self._net_return(pos["entry_price"], exit_price)
                                equity *= 1 + ret * run.params.get("position_size", 0.1)
                                hold_days = self._holding_days(
                                    pos["entry_date"], next_day
                                )
                                trades.append(
                                    BacktestTrade(
                                        run_id=run_id,
                                        sector_code=alert.sector_code,
                                        sector_name=pos["sector_name"],
                                        stock_code=pos["stock_code"],
                                        stock_name=pos.get("stock_name"),
                                        sell_stock_code=pos["stock_code"],
                                        sell_stock_name=pos.get("stock_name"),
                                        alert_code=alert.alert_code,
                                        signal_date=pos["signal_date"],
                                        entry_date=pos["entry_date"],
                                        exit_date=next_day,
                                        entry_price=pos["entry_price"],
                                        exit_price=exit_price,
                                        return_pct=round(ret * 100, 2),
                                        holding_days=hold_days,
                                        trade_mode=TRADE_MODE_LEADER_STOCK,
                                        human_reason=pos["reason"],
                                    )
                                )

                if index_bars.get(td):
                    benchmark *= 1 + index_bars[td].pct_change / 100

                self.session.add(
                    BacktestEquityDaily(
                        run_id=run_id,
                        trade_date=td,
                        equity=equity,
                        benchmark_equity=benchmark,
                    )
                )

            for code, pos in list(positions.items()):
                last_day = days[-1]
                exit_price = pos["entry_price"]
                hold_days = self._holding_days(pos["entry_date"], last_day)
                trades.append(
                    BacktestTrade(
                        run_id=run_id,
                        sector_code=code,
                        sector_name=pos["sector_name"],
                        stock_code=pos["stock_code"],
                        stock_name=pos.get("stock_name"),
                        sell_stock_code=pos["stock_code"],
                        sell_stock_name=pos.get("stock_name"),
                        alert_code=pos["alert_code"],
                        signal_date=pos["signal_date"],
                        entry_date=pos["entry_date"],
                        exit_date=last_day,
                        entry_price=pos["entry_price"],
                        exit_price=exit_price,
                        return_pct=0.0,
                        holding_days=hold_days,
                        trade_mode=TRADE_MODE_LEADER_STOCK,
                        human_reason=pos["reason"],
                    )
                )

            await self._save_results(run_id, trades, equity, benchmark)
            run.status = "done"
            from datetime import datetime

            run.finished_at = datetime.utcnow()
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)
            raise
        finally:
            await self.session.flush()

    def _holding_days(self, entry: date, exit_d: date) -> int:
        if not self._trade_days_cache:
            return max(0, (exit_d - entry).days)
        try:
            i0 = self._trade_days_cache.index(entry)
            i1 = self._trade_days_cache.index(exit_d)
            return max(0, i1 - i0)
        except ValueError:
            return max(0, (exit_d - entry).days)

    def _should_buy(self, strategy: str, alert_code: str, sector, env) -> bool:
        if strategy == "fish_body":
            return alert_code == "STAGE_UP" and (not env or env.env_score >= 60)
        if strategy == "sprout_probe":
            return alert_code == "NEW_SPROUT" and sector.total_score >= 55
        if strategy == "top5_rotation":
            return sector.rank <= 5 and sector.stage in ("ferment", "climax")
        if strategy == "fixed_hold":
            return alert_code == "NEW_SPROUT"
        return False

    def _should_sell(self, strategy: str, alert_code: str, sector) -> bool:
        if strategy == "fixed_hold":
            return False
        return alert_code in ("EXIT_CLIMAX", "EXIT_DECAY")

    def _net_return(self, entry: float, exit: float) -> float:
        gross = exit / entry - 1
        cost = self.COMMISSION * 2 + self.STAMP_TAX + self.SLIPPAGE * 2
        return gross - cost

    async def _entry_price(
        self, sector_code: str, signal_date: date, trade_date: Optional[date]
    ) -> Optional[float]:
        if not trade_date:
            return None
        leader = await self._leader(signal_date, sector_code)
        if not leader:
            return 10.0
        quotes = self.adapter.get_stock_quotes([leader], trade_date, sector_code)
        if quotes:
            return quotes[0].open or quotes[0].close
        return None

    async def _leader_with_name(
        self, trade_date: date, sector_code: str
    ) -> tuple[str, str]:
        row = (
            await self.session.execute(
                select(ThemeLeaderDaily).where(
                    ThemeLeaderDaily.trade_date == trade_date,
                    ThemeLeaderDaily.sector_code == sector_code,
                )
            )
        ).scalar_one_or_none()
        if row:
            name = row.stock_name or resolve_stock_name(row.stock_code)
            return row.stock_code, name
        stocks = self.adapter.get_concept_stocks(sector_code, trade_date)
        code = stocks[0] if stocks else "000001.XSHE"
        return code, resolve_stock_name(code)

    async def _leader(self, trade_date: date, sector_code: str) -> str:
        code, _ = await self._leader_with_name(trade_date, sector_code)
        return code

    async def _save_results(
        self,
        run_id: int,
        trades: list[BacktestTrade],
        equity: float,
        benchmark: float,
    ) -> None:
        await self.session.execute(delete(BacktestTrade).where(BacktestTrade.run_id == run_id))
        await self.session.execute(
            delete(BacktestMetric).where(BacktestMetric.run_id == run_id)
        )
        for t in trades:
            self.session.add(t)

        closed = [t for t in trades if t.return_pct is not None]
        wins = [t for t in closed if (t.return_pct or 0) > 0]
        win_rate = len(wins) / len(closed) if closed else 0
        fish_body = sum(
            1
            for t in closed
            if t.alert_code in ("EXIT_CLIMAX", "EXIT_DECAY") and (t.return_pct or 0) > 0
        )
        fish_rate = fish_body / len(closed) if closed else 0

        returns = [t.return_pct or 0 for t in closed]
        max_dd = 0.0
        if returns:
            peak = 0.0
            cum = 0.0
            for r in returns:
                cum += r
                peak = max(peak, cum)
                max_dd = max(max_dd, peak - cum)

        self.session.add(
            BacktestMetric(
                run_id=run_id,
                total_return=round((equity - 1) * 100, 2),
                annual_return=round((equity - 1) * 100, 2),
                max_drawdown=round(max_dd, 2),
                sharpe=0.0,
                win_rate=round(win_rate * 100, 2),
                trade_count=len(closed),
                fish_body_capture=round(fish_rate * 100, 2),
                benchmark_return=round((benchmark - 1) * 100, 2),
                extra={"stage_win_rates": {}},
            )
        )
