from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from app.adapters.factory import get_adapter
from app.labels import TRADE_MODE_LEADER_STOCK
from app.models.tables import (
    BacktestEquityDaily,
    BacktestMetric,
    BacktestRun,
    BacktestTrade,
)
from app.services.ingestion import IngestionService
from app.services.scan_service import ScanService
from app.services.stock_names import resolve_stock_name

logger = logging.getLogger(__name__)


def score_row_to_dict(row: Any | None) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    return {
        "total": float(getattr(row, "total_score", 0.0) or 0.0),
        "persistence": float(getattr(row, "persistence_score", 0.0) or 0.0),
        "capital": float(getattr(row, "capital_score", 0.0) or 0.0),
        "breadth": float(getattr(row, "breadth_score", 0.0) or 0.0),
        "leader": float(getattr(row, "leader_score", 0.0) or 0.0),
        "relative": float(getattr(row, "relative_score", 0.0) or 0.0),
        "stage": str(getattr(row, "stage", "dormant") or "dormant"),
        "is_main_line": bool(getattr(row, "is_main_line", False)),
        "main_line_tier": str(getattr(row, "main_line_tier", "rotation") or "rotation"),
    }


class BacktestEngine:
    COMMISSION = 0.00025
    STAMP_TAX = 0.001
    SLIPPAGE = 0.001

    def __init__(self, scoring_mode: str | None = None):
        self.adapter = get_adapter()
        self._trade_days_cache: list[date] = []
        self.scoring_mode = scoring_mode

    async def run(self, run: BacktestRun) -> None:
        from app.services.backtest_store import flush_run, save_backtest_results

        run.status = "running"
        flush_run(run)

        try:
            days = self.adapter.get_trade_days(run.start_date, run.end_date)
            self._trade_days_cache = days
            run.total_days = len(days)
            flush_run(run)

            if run.strategy_id == "main_line_rotation":
                await self._run_main_line_rotation(run, days)
            else:
                await self._run_legacy_alerts(run, days)

            run.status = "done"
            from datetime import datetime
            run.finished_at = datetime.utcnow()
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)
            raise
        finally:
            flush_run(run)

    async def _run_main_line_rotation(
        self, run: BacktestRun, days: list[date]
    ) -> None:
        from app.services.backtest_store import flush_run, save_backtest_results

        params = run.params or {}
        sector_codes = set(params.get("sector_codes") or [])
        if not sector_codes:
            raise ValueError("主线轮动回测需至少勾选一个板块（sector_codes）")

        initial_capital = float(params.get("initial_capital", 1_000_000))
        position_ratio = float(params.get("position_ratio", 0.95))
        streak_need = int(params.get("main_line_streak_days", 3))

        ingestion = IngestionService()
        scanner = ScanService(scoring_mode=self.scoring_mode)

        cash = initial_capital
        position: Optional[dict[str, Any]] = None
        streak: dict[str, int] = {}
        trades: list[BacktestTrade] = []
        pending: Optional[dict[str, Any]] = None
        equity_series: list[float] = []
        equity_curve: list[BacktestEquityDaily] = []

        index_bars = {
            b.trade_date: b
            for b in self.adapter.get_index_bars("000300.XSHG", run.start_date, run.end_date)
        }
        benchmark = 1.0

        from app.services.volatile_scan import prepare_today_buffer

        if days:
            prepare_today_buffer(days[0], append=False)

        for i, td in enumerate(days):
            if pending:
                cash, position, closed_trade, pending, open_trade = (
                    await self._execute_pending_main_line(
                        run.id, pending, td, cash, position, position_ratio
                    )
                )
                if closed_trade:
                    trades.append(closed_trade)
                if open_trade:
                    trades.append(open_trade)

            await ingestion.ingest_day(td)
            await scanner.run_scan(td)
            run.progress = i + 1
            flush_run(run)

            pool_scores = self._pool_scores(td, sector_codes)
            score_map = {s.sector_code: s for s in pool_scores}
            rank1 = (
                self._pick_rank1_a_strategy(pool_scores)
                if self.scoring_mode == "a_strategy"
                else self._pick_rank1(pool_scores)
            )
            if rank1:
                streak = {rank1.sector_code: streak.get(rank1.sector_code, 0) + 1}
            else:
                streak = {}

            held_code = position["sector_code"] if position else None
            candidate = self._pick_main_line_candidate(
                streak, held_code, streak_need, score_map
            )

            if candidate and days[i + 1 : i + 2]:
                pending = {
                    "signal_date": td,
                    "buy_sector": candidate,
                    "entry_scores": score_row_to_dict(score_map[candidate]),
                    "exit_scores": (
                        score_row_to_dict(score_map[held_code])
                        if held_code and held_code in score_map
                        else None
                    ),
                    "rotate": position is not None,
                    "streak_days": streak.get(candidate, streak_need),
                }

            equity = await self._mark_equity(cash, position, td)
            equity_series.append(equity)
            if index_bars.get(td):
                benchmark *= 1 + index_bars[td].pct_change / 100

            bench_abs = benchmark * initial_capital
            equity_curve.append(BacktestEquityDaily(
                run_id=run.id,
                trade_date=td,
                equity=equity,
                benchmark_equity=bench_abs,
            ))

        unrealized_close = False
        if position and days:
            last_day = days[-1]
            final_equity, unrealized_close = await self._finalize_open_position_at_close(
                run.id,
                position,
                cash,
                last_day,
                trades,
                equity_series,
                equity_curve,
            )
            close_px = await self._stock_close_price(
                position["stock_code"], days[-1], position["sector_code"]
            )
            logger.info(
                "[回测] 区间结束仍持仓 sector=%s stock=%s close=%.2f 期末资产=%.0f",
                position.get("sector_code"),
                position.get("stock_code"),
                close_px or 0,
                final_equity,
            )
        else:
            final_equity = equity_series[-1] if equity_series else cash

        metrics = self._compute_metrics(
            run.id, trades, final_equity, benchmark,
            initial_capital=initial_capital,
            equity_series=equity_series,
            unrealized_close=unrealized_close,
        )
        save_backtest_results(run, trades, metrics, equity_curve)
        logger.info(
            "[回测] 主线轮动完成 run_id=%s 交易笔数=%d 期末资产=%.0f",
            run.id, len(trades), final_equity,
        )

    async def _execute_pending_main_line(
        self,
        run_id: int,
        pending: dict[str, Any],
        trade_date: date,
        cash: float,
        position: Optional[dict[str, Any]],
        position_ratio: float,
    ) -> tuple[
        float,
        Optional[dict[str, Any]],
        Optional[BacktestTrade],
        Optional[dict[str, Any]],
        Optional[BacktestTrade],
    ]:
        closed: Optional[BacktestTrade] = None
        opened: Optional[BacktestTrade] = None
        signal_date = pending["signal_date"]
        buy_sector = pending["buy_sector"]
        entry_scores = pending.get("entry_scores")

        if pending.get("rotate") and position:
            exit_price = await self._stock_execution_open_price(
                position["stock_code"], trade_date, position["sector_code"]
            )
            if not exit_price or exit_price <= 0:
                return cash, position, None, pending, None
            proceeds = position["shares"] * exit_price
            proceeds *= 1 - self.COMMISSION - self.STAMP_TAX - self.SLIPPAGE
            cash += proceeds
            closed = self._build_trade(
                run_id,
                position,
                exit_date=trade_date,
                exit_price=exit_price or position["entry_price"],
                exit_scores=pending.get("exit_scores") or position.get("entry_scores"),
                alert_code="MAIN_LINE_ROTATE",
                human_reason=f"新主线连续{pending.get('streak_days', 3)}日第一，换仓卖出",
            )
            position = None
            pending["rotate"] = False

        leader_code, leader_name = self._leader_with_name(signal_date, buy_sector)
        buy_price = await self._stock_execution_open_price(leader_code, trade_date, buy_sector)
        if buy_price and buy_price > 0 and cash > 0:
            invest = cash * position_ratio
            shares = invest / buy_price
            cost = invest * (1 + self.COMMISSION + self.SLIPPAGE)
            if cost <= cash:
                cash -= cost
                sector_name = leader_name
                score_row = self._score_row(signal_date, buy_sector)
                if score_row:
                    sector_name = score_row.sector_name
                position = {
                    "sector_code": buy_sector,
                    "sector_name": sector_name,
                    "stock_code": leader_code,
                    "stock_name": leader_name,
                    "signal_date": signal_date,
                    "entry_date": trade_date,
                    "entry_price": buy_price,
                    "shares": shares,
                    "entry_scores": entry_scores,
                    "alert_code": "MAIN_LINE_BUY",
                    "reason": "规则主线连续领跑，买入主线龙头",
                }
                opened = self._build_open_trade(run_id, position)
                return cash, position, closed, None, opened

        return cash, position, closed, pending, None

    async def _run_legacy_alerts(
        self, run: BacktestRun, days: list[date]
    ) -> None:
        from app.services.backtest_store import flush_run, save_backtest_results

        ingestion = IngestionService()
        scanner = ScanService(scoring_mode=self.scoring_mode)

        equity = 1.0
        benchmark = 1.0
        positions: dict[str, dict[str, Any]] = {}
        trades: list[BacktestTrade] = []
        equity_curve: list[BacktestEquityDaily] = []

        index_bars = {
            b.trade_date: b
            for b in self.adapter.get_index_bars("000300.XSHG", run.start_date, run.end_date)
        }

        for i, td in enumerate(days):
            await ingestion.ingest_day(td)
            await scanner.run_scan(td)
            run.progress = i + 1
            flush_run(run)

            from app.services.volatile_scan import get_today_buffer
            buf = get_today_buffer()
            env_row = buf.market_env if buf else None

            pool_scores = self._pool_scores(td, set())
            score_map = {s.sector_code: s for s in pool_scores}

            next_day = days[i + 1] if i + 1 < len(days) else None

            for code, sector in score_map.items():
                if self._should_buy(run.strategy_id, "NEW_SPROUT", sector, env_row):
                    if code in positions:
                        continue
                    if len(positions) >= run.params.get("max_positions", 3):
                        continue
                    if env_row and not env_row.can_long and run.strategy_id != "fixed_hold":
                        continue
                    price = await self._entry_price(code, td, next_day)
                    if price is None:
                        continue
                    leader_code, leader_name = self._leader_with_name(td, code)
                    positions[code] = {
                        "signal_date": td,
                        "entry_date": next_day or td,
                        "entry_price": price,
                        "sector_name": sector.sector_name,
                        "stock_code": leader_code,
                        "stock_name": leader_name,
                        "alert_code": "NEW_SPROUT",
                        "reason": "新晋萌芽",
                        "stage": sector.stage,
                    }

            if index_bars.get(td):
                benchmark *= 1 + index_bars[td].pct_change / 100

            equity_curve.append(BacktestEquityDaily(
                run_id=run.id,
                trade_date=td,
                equity=equity,
                benchmark_equity=benchmark,
            ))

        if positions:
            logger.info(
                "[回测] 区间结束仍持仓 %d 个板块（未触发卖出，不强制平仓）",
                len(positions),
            )

        metrics = self._compute_metrics(run.id, trades, equity, benchmark)
        save_backtest_results(run, trades, metrics, equity_curve)

    def _pool_scores(self, td: date, sector_codes: set[str]) -> list:
        from app.services.volatile_scan import get_today_buffer

        buf = get_today_buffer()
        rows: list = []
        if buf and td in buf.scores_by_date:
            rows = list(buf.scores_by_date[td])
        if not sector_codes:
            return rows
        return [
            s
            for s in rows
            if (
                s.sector_code in sector_codes
                and not getattr(s, "is_filtered", False)
                and (
                    self.scoring_mode != "a_strategy"
                    or bool(getattr(s, "is_main_line", False))
                )
            )
        ]

    def _score_row(self, td: date, sector_code: str):
        pool = self._pool_scores(td, {sector_code})
        return pool[0] if pool else None

    @staticmethod
    def _pick_rank1(scores: list) -> Any:
        if not scores:
            return None
        return sorted(
            scores,
            key=lambda s: (
                -float(getattr(s, "total_score", 0) or 0),
                -float(getattr(s, "capital_score", 0) or 0),
                getattr(s, "sector_code", ""),
            ),
        )[0]

    @staticmethod
    def _pick_rank1_a_strategy(scores: list) -> Any:
        if not scores:
            return None
        tier_order = {"top": 0, "secondary": 1, "rotation": 2}
        return sorted(
            scores,
            key=lambda s: (
                0 if bool(getattr(s, "is_main_line", False)) else 1,
                tier_order.get(str(getattr(s, "main_line_tier", "rotation") or "rotation"), 9),
                -float(getattr(s, "persistence_score", 0) or 0),
                -float(getattr(s, "capital_score", 0) or 0),
                getattr(s, "sector_code", ""),
            ),
        )[0]

    @staticmethod
    def _pick_main_line_candidate(
        streak: dict[str, int],
        held_code: Optional[str],
        min_days: int,
        score_map: dict,
    ) -> Optional[str]:
        best_code: Optional[str] = None
        best_key: tuple = ()
        for code, days in streak.items():
            if days < min_days:
                continue
            if held_code and code == held_code:
                continue
            s = score_map.get(code)
            if not s:
                continue
            key = (
                days,
                float(getattr(s, "total_score", 0) or 0),
                float(getattr(s, "capital_score", 0) or 0),
            )
            if key > best_key:
                best_key = key
                best_code = code
        return best_code

    async def _mark_equity(
        self, cash: float, position: Optional[dict[str, Any]], td: date
    ) -> float:
        if not position:
            return cash
        price = await self._stock_mark_price(
            position["stock_code"], td, position["sector_code"]
        )
        if not price:
            price = position["entry_price"]
        return cash + position["shares"] * price

    def _build_open_trade(self, run_id: int, pos: dict[str, Any]) -> BacktestTrade:
        return BacktestTrade(
            run_id=run_id,
            sector_code=pos["sector_code"],
            sector_name=pos["sector_name"],
            stock_code=pos["stock_code"],
            stock_name=pos.get("stock_name"),
            sell_stock_code=pos["stock_code"],
            sell_stock_name=pos.get("stock_name"),
            alert_code="MAIN_LINE_BUY",
            signal_date=pos.get("signal_date"),
            entry_date=pos["entry_date"],
            exit_date=None,
            entry_price=pos["entry_price"],
            exit_price=None,
            return_pct=None,
            holding_days=None,
            trade_mode=TRADE_MODE_LEADER_STOCK,
            human_reason=pos.get("reason", "规则主线连续领跑，买入主线龙头"),
            entry_scores=pos.get("entry_scores"),
            exit_scores=None,
        )

    def _build_trade(
        self,
        run_id: int,
        pos: dict[str, Any],
        *,
        exit_date: date,
        exit_price: float,
        exit_scores: Optional[dict],
        alert_code: str,
        human_reason: str,
    ) -> BacktestTrade:
        ret = self._net_return(pos["entry_price"], exit_price) if exit_price else 0.0
        return BacktestTrade(
            run_id=run_id,
            sector_code=pos["sector_code"],
            sector_name=pos["sector_name"],
            stock_code=pos["stock_code"],
            stock_name=pos.get("stock_name"),
            sell_stock_code=pos["stock_code"],
            sell_stock_name=pos.get("stock_name"),
            alert_code=alert_code,
            signal_date=pos.get("signal_date"),
            entry_date=pos["entry_date"],
            exit_date=exit_date,
            entry_price=pos["entry_price"],
            exit_price=exit_price,
            return_pct=round(ret * 100, 2),
            holding_days=self._holding_days(pos["entry_date"], exit_date),
            trade_mode=TRADE_MODE_LEADER_STOCK,
            human_reason=human_reason,
            entry_scores=pos.get("entry_scores"),
            exit_scores=exit_scores,
        )

    async def _stock_open_price(
        self, stock_code: str, trade_date: date, sector_code: str
    ) -> Optional[float]:
        quotes = self.adapter.get_stock_quotes(
            [stock_code], trade_date, sector_code, skip_flows=True
        )
        if quotes:
            return quotes[0].open or quotes[0].close
        return None

    async def _stock_execution_open_price(
        self, stock_code: str, trade_date: date, sector_code: str
    ) -> Optional[float]:
        quotes = self.adapter.get_stock_quotes(
            [stock_code], trade_date, sector_code, skip_flows=True
        )
        if not quotes:
            return None
        px = quotes[0].open
        return px if px and px > 0 else None

    async def _stock_close_price(
        self, stock_code: str, trade_date: date, sector_code: str
    ) -> Optional[float]:
        quotes = self.adapter.get_stock_quotes(
            [stock_code], trade_date, sector_code, skip_flows=True
        )
        if not quotes:
            return None
        px = quotes[0].close
        return px if px and px > 0 else None

    async def _stock_mark_price(
        self, stock_code: str, trade_date: date, sector_code: str
    ) -> Optional[float]:
        close_px = await self._stock_close_price(stock_code, trade_date, sector_code)
        if close_px:
            return close_px
        quotes = self.adapter.get_stock_quotes(
            [stock_code], trade_date, sector_code, skip_flows=True
        )
        if not quotes:
            return None
        open_px = quotes[0].open
        return open_px if open_px and open_px > 0 else None

    async def _finalize_open_position_at_close(
        self,
        run_id: int,
        position: dict[str, Any],
        cash: float,
        last_day: date,
        trades: list[BacktestTrade],
        equity_series: list[float],
        equity_curve: list[BacktestEquityDaily],
    ) -> tuple[float, bool]:
        close_px = await self._stock_close_price(
            position["stock_code"], last_day, position["sector_code"]
        )
        if not close_px or close_px <= 0:
            mark = await self._mark_equity(cash, position, last_day)
            if equity_series:
                equity_series[-1] = mark
            return mark, False

        mark = cash + position["shares"] * close_px
        if equity_series:
            equity_series[-1] = mark
        for eq in equity_curve:
            if eq.trade_date == last_day:
                eq.equity = mark
                break

        exit_row = self._score_row(last_day, position["sector_code"])
        exit_scores = score_row_to_dict(exit_row) if exit_row else None
        float_ret = round(self._net_return(position["entry_price"], close_px) * 100, 2)
        for t in trades:
            if t.exit_date is None and t.alert_code == "MAIN_LINE_BUY":
                t.return_pct = float_ret
                t.exit_scores = exit_scores
                t.holding_days = self._holding_days(t.entry_date, last_day)
                t.human_reason = (
                    f"{t.human_reason or ''}；区间结束按{last_day}收盘价估算收益"
                ).strip("；")

        return mark, True

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
        leader = self._leader(signal_date, sector_code)
        if not leader:
            return 10.0
        return await self._stock_execution_open_price(leader, trade_date, sector_code)

    def _leader_with_name(
        self, trade_date: date, sector_code: str
    ) -> tuple[str, str]:
        from app.services.volatile_scan import get_today_buffer

        buf = get_today_buffer()
        if buf and sector_code in buf.leaders_by_code:
            leader = buf.leaders_by_code[sector_code]
            if getattr(leader, "trade_date", None) == trade_date:
                name = leader.stock_name or resolve_stock_name(leader.stock_code)
                return leader.stock_code, name

        stocks = self.adapter.get_concept_stocks(sector_code, trade_date)
        code = stocks[0] if stocks else "000001.XSHE"
        return code, resolve_stock_name(code)

    def _leader(self, trade_date: date, sector_code: str) -> str:
        code, _ = self._leader_with_name(trade_date, sector_code)
        return code

    def _compute_metrics(
        self,
        run_id: int,
        trades: list[BacktestTrade],
        equity: float,
        benchmark: float,
        *,
        initial_capital: float = 1.0,
        equity_series: Optional[list[float]] = None,
        unrealized_close: bool = False,
    ) -> BacktestMetric:
        closed = [t for t in trades if t.exit_date is not None and t.return_pct is not None]
        wins = [t for t in closed if (t.return_pct or 0) > 0]
        win_rate = len(wins) / len(closed) if closed else 0
        fish_body = sum(
            1
            for t in closed
            if t.alert_code
            in ("EXIT_CLIMAX", "EXIT_DECAY", "MAIN_LINE_ROTATE")
            and (t.return_pct or 0) > 0
        )
        fish_rate = fish_body / len(closed) if closed else 0

        abs_mode = initial_capital >= 10_000
        if abs_mode and equity_series:
            equity = equity_series[-1]
            peak = equity_series[0]
            max_dd = 0.0
            for eq in equity_series:
                peak = max(peak, eq)
                if peak > 0:
                    max_dd = max(max_dd, (peak - eq) / peak * 100)
        else:
            returns = [t.return_pct or 0 for t in closed]
            max_dd = 0.0
            if returns:
                peak = 0.0
                cum = 0.0
                for r in returns:
                    cum += r
                    peak = max(peak, cum)
                    max_dd = max(max_dd, peak - cum)

        if abs_mode:
            total_ret = (equity - initial_capital) / initial_capital * 100
            bench_ret = (benchmark * initial_capital - initial_capital) / initial_capital * 100
        else:
            total_ret = (equity - 1) * 100
            bench_ret = (benchmark - 1) * 100

        return BacktestMetric(
            run_id=run_id,
            total_return=round(total_ret, 2),
            annual_return=round(total_ret, 2),
            max_drawdown=round(max_dd, 2),
            sharpe=0.0,
            win_rate=round(win_rate * 100, 2),
            trade_count=len(closed),
            fish_body_capture=round(fish_rate * 100, 2),
            benchmark_return=round(bench_ret, 2),
            extra={
                "stage_win_rates": {},
                "initial_capital": initial_capital,
                "unrealized_close": unrealized_close,
            },
        )
