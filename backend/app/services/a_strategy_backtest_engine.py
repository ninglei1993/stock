"""A策略回测引擎 —— 严格按照6条规则买入、退出信号卖出、-8%止损。

与已有 BacktestEngine（主线轮动）完全独立，复用 IngestionService / ScanService
数据管线以及 evaluate_main_line_rules / evaluate_confirm_exit_signals 判定函数。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.factory import get_adapter
from app.labels import TRADE_MODE_LEADER_STOCK
from app.models.tables import (
    BacktestEquityDaily,
    BacktestMetric,
    BacktestRun,
    BacktestTrade,
    ThemeLeaderDaily,
)
from app.services.ingestion import IngestionService
from app.services.scan_service import ScanService
from app.services.stock_names import resolve_stock_name

logger = logging.getLogger(__name__)

STRATEGY_ID = "a_strategy_strict"

ALERT_BUY = "A_STRATEGY_BUY"
ALERT_EXIT = "A_STRATEGY_EXIT"
ALERT_STOP_LOSS = "A_STRATEGY_STOP_LOSS"

STOP_LOSS_PCT = -0.08


def _score_snapshot(score_row: Any) -> Optional[dict[str, Any]]:
    if score_row is None:
        return None
    return {
        "total": float(getattr(score_row, "total_score", 0) or 0),
        "persistence": 0.0,
        "capital": 0.0,
        "breadth": 0.0,
        "leader": 0.0,
        "relative": 0.0,
        "stage": str(getattr(score_row, "stage", "dormant") or "dormant"),
        "is_main_line": bool(getattr(score_row, "is_main_line", False)),
        "main_line_tier": str(getattr(score_row, "main_line_tier", "rotation") or "rotation"),
    }


class AStrategyBacktestEngine:
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

            await self._run_strict(run_id, run, days)

            run.status = "done"
            run.finished_at = datetime.utcnow()
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)[:2000]
            raise
        finally:
            await self.session.flush()

    async def _run_strict(
        self, run_id: int, run: BacktestRun, days: list[date]
    ) -> None:
        params = run.params or {}
        sector_codes = set(params.get("sector_codes") or [])
        if not sector_codes:
            raise ValueError("A策略回测需至少勾选一个板块")

        initial_capital = float(params.get("initial_capital", 1_000_000))

        ingestion = IngestionService(self.session)
        scanner = ScanService(self.session, scoring_mode="a_strategy")

        cash = initial_capital
        positions: dict[str, _Position] = {}
        all_trades: list[BacktestTrade] = []
        equity_series: list[float] = []

        await self.session.execute(
            delete(BacktestEquityDaily).where(BacktestEquityDaily.run_id == run_id)
        )

        index_bars = {
            b.trade_date: b
            for b in self.adapter.get_index_bars("000300.XSHG", run.start_date, run.end_date)
        }
        benchmark = 1.0

        from app.services.volatile_scan import prepare_today_buffer
        if days:
            prepare_today_buffer(days[0], append=False)

        pending_buys: list[_PendingBuy] = []
        pending_sells: list[_PendingSell] = []

        for i, td in enumerate(days):
            if pending_buys or pending_sells:
                cash = await self._execute_pending(
                    run_id, td, cash, positions, all_trades,
                    pending_buys, pending_sells,
                )
                pending_buys.clear()
                pending_sells.clear()

            await ingestion.ingest_day(td)
            await scanner.run_scan(td)
            run.progress = i + 1
            await self.session.flush()

            score_map = await self._get_scores(td, sector_codes)

            for sector_code in list(positions.keys()):
                pos = positions[sector_code]
                close_px = await self._stock_close_price(pos.stock_code, td, sector_code)
                if close_px and close_px > 0:
                    pos.last_close = close_px

                if close_px and close_px > 0 and pos.entry_price > 0:
                    unrealized_ret = close_px / pos.entry_price - 1
                    if unrealized_ret <= STOP_LOSS_PCT:
                        pending_sells.append(_PendingSell(
                            sector_code=sector_code,
                            signal_date=td,
                            reason=f"龙头止损：浮亏{unrealized_ret*100:.1f}%，触发-8%止损线",
                            alert_code=ALERT_STOP_LOSS,
                            exit_scores=_score_snapshot(score_map.get(sector_code)),
                        ))
                        continue

                score = score_map.get(sector_code)
                if score and str(getattr(score, "exit_state", "normal")) == "exit":
                    pending_sells.append(_PendingSell(
                        sector_code=sector_code,
                        signal_date=td,
                        reason="A策略退出信号触发（5条退出条件中至少2条满足）",
                        alert_code=ALERT_EXIT,
                        exit_scores=_score_snapshot(score),
                    ))

            sell_sector_codes = {s.sector_code for s in pending_sells}
            for sector_code in sector_codes:
                if sector_code in positions:
                    continue
                if sector_code in sell_sector_codes:
                    continue
                score = score_map.get(sector_code)
                if not score:
                    continue
                if not bool(getattr(score, "is_main_line", False)):
                    continue

                leader_code, leader_name = await self._leader_with_name(td, sector_code)
                pending_buys.append(_PendingBuy(
                    sector_code=sector_code,
                    sector_name=str(getattr(score, "sector_name", sector_code)),
                    signal_date=td,
                    leader_code=leader_code,
                    leader_name=leader_name,
                    entry_scores=_score_snapshot(score),
                    tier=str(getattr(score, "main_line_tier", "rotation") or "rotation"),
                ))

            equity = self._calc_equity(cash, positions)
            equity_series.append(equity)

            if index_bars.get(td):
                benchmark *= 1 + index_bars[td].pct_change / 100

            bench_abs = benchmark * initial_capital
            self.session.add(BacktestEquityDaily(
                run_id=run_id,
                trade_date=td,
                equity=equity,
                benchmark_equity=bench_abs,
            ))

        if pending_sells and days:
            last_day = days[-1]
            for ps in pending_sells:
                pos = positions.pop(ps.sector_code, None)
                if pos:
                    close_px = pos.last_close or pos.entry_price
                    trade = self._build_close_trade(
                        run_id, pos, last_day, close_px, ps,
                    )
                    all_trades.append(trade)

        for sector_code, pos in list(positions.items()):
            if days:
                close_px = await self._stock_close_price(
                    pos.stock_code, days[-1], sector_code,
                )
                if close_px and close_px > 0:
                    pos.last_close = close_px

        if positions and days and equity_series:
            final_eq = self._calc_equity(cash, positions)
            equity_series[-1] = final_eq
            await self.session.execute(
                update(BacktestEquityDaily)
                .where(
                    BacktestEquityDaily.run_id == run_id,
                    BacktestEquityDaily.trade_date == days[-1],
                )
                .values(equity=final_eq)
            )
            for sector_code, pos in positions.items():
                if pos.last_close and pos.entry_price > 0:
                    ret = self._net_return(pos.entry_price, pos.last_close)
                    for t in all_trades:
                        if (
                            t.stock_code == pos.stock_code
                            and t.exit_date is None
                            and t.alert_code == ALERT_BUY
                        ):
                            t.return_pct = round(ret * 100, 2)
                            t.holding_days = self._holding_days(t.entry_date, days[-1])
                            t.human_reason = (
                                f"{t.human_reason}；区间结束按{days[-1]}收盘价估算收益"
                            )

        final_equity = equity_series[-1] if equity_series else cash
        await self._save_results(
            run_id, all_trades, final_equity, benchmark,
            initial_capital=initial_capital,
            equity_series=equity_series,
        )
        logger.info(
            "[A策略回测] 完成 run_id=%s 交易笔数=%d 期末资产=%.0f",
            run_id, len(all_trades), final_equity,
        )

    async def _execute_pending(
        self,
        run_id: int,
        trade_date: date,
        cash: float,
        positions: dict[str, _Position],
        all_trades: list[BacktestTrade],
        pending_buys: list[_PendingBuy],
        pending_sells: list[_PendingSell],
    ) -> float:
        for ps in pending_sells:
            pos = positions.pop(ps.sector_code, None)
            if not pos:
                continue
            exit_price = await self._stock_open_price(
                pos.stock_code, trade_date, ps.sector_code,
            )
            if not exit_price or exit_price <= 0:
                exit_price = pos.last_close or pos.entry_price
            proceeds = pos.shares * exit_price
            proceeds *= (1 - self.COMMISSION - self.STAMP_TAX - self.SLIPPAGE)
            cash += proceeds
            trade = self._build_close_trade(run_id, pos, trade_date, exit_price, ps)
            all_trades.append(trade)
            logger.info(
                "[A策略回测] 卖出 %s %s@%.2f 原因=%s",
                pos.stock_code, pos.stock_name, exit_price, ps.reason,
            )

        if pending_buys and cash > 10000:
            alloc_per_sector = cash / len(pending_buys)
            for pb in pending_buys:
                if pb.sector_code in positions:
                    continue
                buy_price = await self._stock_open_price(
                    pb.leader_code, trade_date, pb.sector_code,
                )
                if not buy_price or buy_price <= 0:
                    continue
                invest = alloc_per_sector * 0.95
                shares = invest / buy_price
                cost = invest * (1 + self.COMMISSION + self.SLIPPAGE)
                if cost > cash:
                    continue
                cash -= cost
                pos = _Position(
                    sector_code=pb.sector_code,
                    sector_name=pb.sector_name,
                    stock_code=pb.leader_code,
                    stock_name=pb.leader_name,
                    signal_date=pb.signal_date,
                    entry_date=trade_date,
                    entry_price=buy_price,
                    shares=shares,
                    entry_scores=pb.entry_scores,
                    last_close=buy_price,
                )
                positions[pb.sector_code] = pos
                open_trade = BacktestTrade(
                    run_id=run_id,
                    sector_code=pb.sector_code,
                    sector_name=pb.sector_name,
                    stock_code=pb.leader_code,
                    stock_name=pb.leader_name,
                    sell_stock_code=pb.leader_code,
                    sell_stock_name=pb.leader_name,
                    alert_code=ALERT_BUY,
                    signal_date=pb.signal_date,
                    entry_date=trade_date,
                    exit_date=None,
                    entry_price=buy_price,
                    exit_price=None,
                    return_pct=None,
                    holding_days=None,
                    trade_mode=TRADE_MODE_LEADER_STOCK,
                    human_reason=f"A策略6条件全部满足，买入{pb.sector_name}龙头",
                    entry_scores=pb.entry_scores,
                    exit_scores=None,
                )
                all_trades.append(open_trade)
                logger.info(
                    "[A策略回测] 买入 %s %s@%.2f sector=%s",
                    pb.leader_code, pb.leader_name, buy_price, pb.sector_name,
                )

        return cash

    def _build_close_trade(
        self,
        run_id: int,
        pos: _Position,
        exit_date: date,
        exit_price: float,
        ps: _PendingSell,
    ) -> BacktestTrade:
        ret = self._net_return(pos.entry_price, exit_price)
        return BacktestTrade(
            run_id=run_id,
            sector_code=pos.sector_code,
            sector_name=pos.sector_name,
            stock_code=pos.stock_code,
            stock_name=pos.stock_name,
            sell_stock_code=pos.stock_code,
            sell_stock_name=pos.stock_name,
            alert_code=ps.alert_code,
            signal_date=ps.signal_date,
            entry_date=pos.entry_date,
            exit_date=exit_date,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            return_pct=round(ret * 100, 2),
            holding_days=self._holding_days(pos.entry_date, exit_date),
            trade_mode=TRADE_MODE_LEADER_STOCK,
            human_reason=ps.reason,
            entry_scores=pos.entry_scores,
            exit_scores=ps.exit_scores,
        )

    def _calc_equity(self, cash: float, positions: dict[str, _Position]) -> float:
        total = cash
        for pos in positions.values():
            total += pos.shares * (pos.last_close or pos.entry_price)
        return total

    async def _get_scores(self, td: date, sector_codes: set[str]) -> dict[str, Any]:
        from app.services.storage_mode import uses_scan_memory_buffer
        from app.services.volatile_scan import get_today_buffer

        rows: list = []
        if uses_scan_memory_buffer():
            buf = get_today_buffer()
            if buf and td in buf.scores_by_date:
                rows = list(buf.scores_by_date[td])
        if not rows:
            from app.models.tables import SectorScoreDaily
            rows = list(
                (await self.session.execute(
                    select(SectorScoreDaily).where(SectorScoreDaily.trade_date == td)
                )).scalars().all()
            )
        return {
            s.sector_code: s
            for s in rows
            if s.sector_code in sector_codes
        }

    async def _leader_with_name(
        self, trade_date: date, sector_code: str,
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

        from app.services.volatile_scan import get_today_buffer
        buf = get_today_buffer()
        if buf and sector_code in buf.leaders_by_code:
            leader = buf.leaders_by_code[sector_code]
            code = getattr(leader, "stock_code", None)
            if code:
                name = getattr(leader, "stock_name", None) or resolve_stock_name(code)
                return code, name

        stocks = self.adapter.get_concept_stocks(sector_code, trade_date)
        code = stocks[0] if stocks else "000001.XSHE"
        return code, resolve_stock_name(code)

    async def _stock_open_price(
        self, stock_code: str, trade_date: date, sector_code: str,
    ) -> Optional[float]:
        quotes = self.adapter.get_stock_quotes(
            [stock_code], trade_date, sector_code, skip_flows=True,
        )
        if not quotes:
            return None
        px = quotes[0].open
        return px if px and px > 0 else None

    async def _stock_close_price(
        self, stock_code: str, trade_date: date, sector_code: str,
    ) -> Optional[float]:
        quotes = self.adapter.get_stock_quotes(
            [stock_code], trade_date, sector_code, skip_flows=True,
        )
        if not quotes:
            return None
        px = quotes[0].close
        return px if px and px > 0 else None

    def _net_return(self, entry: float, exit_px: float) -> float:
        if entry <= 0:
            return 0.0
        gross = exit_px / entry - 1
        cost = self.COMMISSION * 2 + self.STAMP_TAX + self.SLIPPAGE * 2
        return gross - cost

    def _holding_days(self, entry: date, exit_d: date) -> int:
        if not self._trade_days_cache:
            return max(0, (exit_d - entry).days)
        try:
            i0 = self._trade_days_cache.index(entry)
            i1 = self._trade_days_cache.index(exit_d)
            return max(0, i1 - i0)
        except ValueError:
            return max(0, (exit_d - entry).days)

    async def _save_results(
        self,
        run_id: int,
        trades: list[BacktestTrade],
        equity: float,
        benchmark: float,
        *,
        initial_capital: float = 1_000_000,
        equity_series: Optional[list[float]] = None,
    ) -> None:
        await self.session.execute(
            delete(BacktestTrade).where(BacktestTrade.run_id == run_id)
        )
        await self.session.execute(
            delete(BacktestMetric).where(BacktestMetric.run_id == run_id)
        )
        for t in trades:
            self.session.add(t)

        closed = [t for t in trades if t.exit_date is not None and t.return_pct is not None]
        wins = [t for t in closed if (t.return_pct or 0) > 0]
        win_rate = len(wins) / len(closed) if closed else 0

        if equity_series and len(equity_series) > 1:
            peak = equity_series[0]
            max_dd = 0.0
            for eq in equity_series:
                peak = max(peak, eq)
                if peak > 0:
                    max_dd = max(max_dd, (peak - eq) / peak * 100)
        else:
            max_dd = 0.0

        total_ret = (equity - initial_capital) / initial_capital * 100 if initial_capital > 0 else 0
        bench_ret = (benchmark * initial_capital - initial_capital) / initial_capital * 100

        self.session.add(BacktestMetric(
            run_id=run_id,
            total_return=round(total_ret, 2),
            annual_return=round(total_ret, 2),
            max_drawdown=round(max_dd, 2),
            sharpe=0.0,
            win_rate=round(win_rate * 100, 2),
            trade_count=len(closed),
            fish_body_capture=0.0,
            benchmark_return=round(bench_ret, 2),
            extra={
                "strategy": STRATEGY_ID,
                "initial_capital": initial_capital,
            },
        ))


class _Position:
    __slots__ = (
        "sector_code", "sector_name", "stock_code", "stock_name",
        "signal_date", "entry_date", "entry_price", "shares",
        "entry_scores", "last_close",
    )

    def __init__(
        self, *, sector_code: str, sector_name: str,
        stock_code: str, stock_name: str,
        signal_date: date, entry_date: date,
        entry_price: float, shares: float,
        entry_scores: Optional[dict], last_close: float,
    ):
        self.sector_code = sector_code
        self.sector_name = sector_name
        self.stock_code = stock_code
        self.stock_name = stock_name
        self.signal_date = signal_date
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.shares = shares
        self.entry_scores = entry_scores
        self.last_close = last_close


class _PendingBuy:
    __slots__ = (
        "sector_code", "sector_name", "signal_date",
        "leader_code", "leader_name", "entry_scores", "tier",
    )

    def __init__(
        self, *, sector_code: str, sector_name: str,
        signal_date: date, leader_code: str, leader_name: str,
        entry_scores: Optional[dict], tier: str,
    ):
        self.sector_code = sector_code
        self.sector_name = sector_name
        self.signal_date = signal_date
        self.leader_code = leader_code
        self.leader_name = leader_name
        self.entry_scores = entry_scores
        self.tier = tier


class _PendingSell:
    __slots__ = (
        "sector_code", "signal_date", "reason", "alert_code", "exit_scores",
    )

    def __init__(
        self, *, sector_code: str, signal_date: date,
        reason: str, alert_code: str,
        exit_scores: Optional[dict],
    ):
        self.sector_code = sector_code
        self.signal_date = signal_date
        self.reason = reason
        self.alert_code = alert_code
        self.exit_scores = exit_scores
