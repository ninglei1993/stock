"""A策略回测引擎 —— 严格按照6条规则买入、退出信号卖出、-8%止损。

与已有 BacktestEngine（主线轮动）完全独立，复用 IngestionService / ScanService
数据管线以及 evaluate_main_line_rules / evaluate_confirm_exit_signals 判定函数。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from types import SimpleNamespace
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

STRATEGY_ID = "a_strategy_strict"
WARMUP_TRADE_DAYS = 0

ALERT_BUY = "A_STRATEGY_BUY"
ALERT_EXIT = "A_STRATEGY_EXIT"
ALERT_STOP_LOSS = "A_STRATEGY_STOP_LOSS"

STOP_LOSS_PCT = -0.08
DEFAULT_RULE_TEMPLATES = [
    ("trend_ma20_up", "趋势条件（站上MA20且MA20向上）", "close > MA20 and MA20 > MA20_prev"),
    ("pct_20d_tier", "20日涨幅分级", ">=10%（>=18%为顶级主线）"),
    ("volume_heat", "量能持续性", "vol_ratio_5d>=1.6 and share8d>=4.5%"),
    ("capital_inflow", "资金连续流入", "主力连续6日净流入 and 北向5日净流入>=2亿"),
    ("money_effect", "板块赚钱效应", "up_ratio>=65%, max连板>=3, 涨停>=5"),
    ("no_negative_news", "竞价与基本面无压制", "竞价门槛通过且无监管利空/集体减持/政策降温"),
]


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

    def __init__(self):
        self.adapter = get_adapter()
        self._trade_days_cache: list[date] = []

    async def run(self, run: BacktestRun) -> None:
        from app.services.backtest_store import flush_run

        logger.info(
            "[A策略回测] 启动 run_id=%s 区间=%s~%s params=%s",
            run.id, run.start_date, run.end_date, run.params or {},
        )
        run.status = "running"
        run.progress = 0
        run.total_days = 0
        flush_run(run)

        try:
            days = self.adapter.get_trade_days(run.start_date, run.end_date)
            self._trade_days_cache = days
            run.total_days = len(days)
            logger.info("[A策略回测] run_id=%s 命中交易日=%d", run.id, len(days))

            await self._run_strict(run, days)

            run.status = "done"
            run.finished_at = datetime.utcnow()
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)[:2000]
            raise
        finally:
            flush_run(run)

    async def _run_strict(
        self, run: BacktestRun, days: list[date]
    ) -> None:
        from app.services.backtest_store import flush_run, save_backtest_results

        params = run.params or {}
        sector_codes = set(params.get("sector_codes") or [])
        if not sector_codes:
            raise ValueError("A策略回测需至少勾选一个板块")

        initial_capital = float(params.get("initial_capital", 1_000_000))
        warmup_count = int(params.get("warmup_days", WARMUP_TRADE_DAYS))
        logger.info(
            "[A策略回测] run_id=%s 选中板块=%d 初始资金=%.2f warmup=%d",
            run.id, len(sector_codes), initial_capital, warmup_count,
        )

        ingestion = IngestionService()
        scanner = ScanService(scoring_mode="a_strategy")

        warmup_days = self._get_warmup_days(run.start_date, warmup_count)
        all_scan_days = warmup_days + days
        logger.info(
            "[A策略回测] run_id=%s warmup区间=%s~%s(%d日) 正式区间=%s~%s(%d日)",
            run.id,
            warmup_days[0] if warmup_days else "-",
            warmup_days[-1] if warmup_days else "-",
            len(warmup_days),
            days[0] if days else "-",
            days[-1] if days else "-",
            len(days),
        )

        from app.services.scan_context import set_scan_bounds
        set_scan_bounds(all_scan_days)

        cash = initial_capital
        positions: dict[str, _Position] = {}
        all_trades: list[BacktestTrade] = []
        equity_series: list[float] = []
        equity_curve: list[BacktestEquityDaily] = []
        near_miss_items: list[dict[str, Any]] = []

        index_bars = {
            b.trade_date: b
            for b in self.adapter.get_index_bars("000300.XSHG", run.start_date, run.end_date)
        }
        benchmark = 1.0

        from app.services.volatile_scan import prepare_today_buffer
        if all_scan_days:
            prepare_today_buffer(all_scan_days[0], append=False)

        total_phases = len(warmup_days) + len(days)
        run.total_days = total_phases
        flush_run(run)

        for wi, wd in enumerate(warmup_days):
            logger.info(
                "[A策略回测] 预热 %d/%d trade_date=%s",
                wi + 1, len(warmup_days), wd,
            )
            await ingestion.ingest_day(wd, skip_market_env=True)
            await scanner.run_scan(wd)
            run.progress = wi + 1
            flush_run(run)

        pending_buys: list[_PendingBuy] = []
        pending_sells: list[_PendingSell] = []

        for i, td in enumerate(days):
            overall_idx = len(warmup_days) + i
            logger.info(
                "[A策略回测] 进度 %d/%d trade_date=%s cash=%.2f 持仓=%d 待买=%d 待卖=%d",
                overall_idx + 1, total_phases, td, cash,
                len(positions), len(pending_buys), len(pending_sells),
            )
            if pending_buys or pending_sells:
                cash = await self._execute_pending(
                    run.id, td, cash, positions, all_trades,
                    pending_buys, pending_sells,
                )
                pending_buys.clear()
                pending_sells.clear()

            await ingestion.ingest_day(td)
            await scanner.run_scan(td)

            score_map = self._get_scores(td, sector_codes, scanner)
            env_row = self._get_env(td)
            logger.info(
                "[A策略回测] trade_date=%s 可用评分板块=%d/%d env_score=%.0f",
                td, len(score_map), len(sector_codes),
                env_row.env_score if env_row else -1,
            )

            for sc_code in sorted(sector_codes):
                sc_row = score_map.get(sc_code)
                raw_rules = (
                    (getattr(sc_row, "rules_json", None) or getattr(sc_row, "rules", None) or [])
                    if sc_row is not None
                    else []
                )
                if not raw_rules:
                    raw_rules = [
                        {
                            "key": key,
                            "label": label,
                            "passed": False,
                            "threshold": threshold,
                            "current": None,
                            "source": "auto",
                        }
                        for key, label, threshold in DEFAULT_RULE_TEMPLATES
                    ]
                passed_rules = [
                    r for r in raw_rules
                    if isinstance(r, dict) and bool(r.get("passed"))
                ]
                passed_count = len(passed_rules)
                total_rules = len(raw_rules)
                if total_rules > 0:
                    rfr = getattr(sc_row, "rule_fail_reasons", None) if sc_row is not None else None
                    if isinstance(rfr, str):
                        rfr_list = [x for x in rfr.split("；") if x]
                    elif isinstance(rfr, list):
                        rfr_list = list(rfr)
                    else:
                        rfr_list = []
                    if sc_row is None:
                        rfr_list = ["当日未产出该板块评分，规则按未通过展示"]
                    item: dict[str, Any] = {
                        "trade_date": td.isoformat(),
                        "sector_code": sc_code,
                        "sector_name": str(getattr(sc_row, "sector_name", sc_code)) if sc_row is not None else sc_code,
                        "pass_count": passed_count,
                        "total_rules": total_rules,
                        "all_passed": passed_count >= total_rules and total_rules > 0,
                        "rules": list(raw_rules),
                        "passed_rule_labels": [
                            str(r.get("label") or r.get("key") or "")
                            for r in passed_rules
                            if str(r.get("label") or r.get("key") or "").strip()
                        ],
                        "rule_fail_reasons": rfr_list,
                        "stage": str(getattr(sc_row, "stage", "dormant")) if sc_row is not None else "dormant",
                        "total_score": float(getattr(sc_row, "total_score", 0) or 0) if sc_row is not None else 0.0,
                        "is_main_line": bool(getattr(sc_row, "is_main_line", False)) if sc_row is not None else False,
                        "main_line_tier": str(getattr(sc_row, "main_line_tier", "rotation") or "rotation") if sc_row is not None else "rotation",
                    }
                    if env_row:
                        item["env_score"] = round(env_row.env_score, 1)
                        item["can_long"] = env_row.can_long
                    if sc_row is not None:
                        item["confirm_state"] = str(getattr(sc_row, "confirm_state", "pending") or "pending")
                        item["exit_state"] = str(getattr(sc_row, "exit_state", "normal") or "normal")
                    near_miss_items.append(item)

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

                leader_code, leader_name = self._leader_with_name(td, sector_code)
                pending_buys.append(_PendingBuy(
                    sector_code=sector_code,
                    sector_name=str(getattr(score, "sector_name", sector_code)),
                    signal_date=td,
                    leader_code=leader_code,
                    leader_name=leader_name,
                    entry_scores=_score_snapshot(score),
                    tier=str(getattr(score, "main_line_tier", "rotation") or "rotation"),
                ))
                logger.info(
                    "[A策略回测] 生成买入信号 trade_date=%s sector=%s leader=%s(%s) tier=%s",
                    td, getattr(score, "sector_name", sector_code),
                    leader_code, leader_name,
                    str(getattr(score, "main_line_tier", "rotation") or "rotation"),
                )

            equity = self._calc_equity(cash, positions)
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
            run.progress = len(warmup_days) + i + 1
            flush_run(run)
            logger.info(
                "[A策略回测] 日终 trade_date=%s equity=%.2f cash=%.2f 持仓=%d 待买=%d 待卖=%d",
                td, equity, cash, len(positions), len(pending_buys), len(pending_sells),
            )

        if pending_sells and days:
            last_day = days[-1]
            for ps in pending_sells:
                pos = positions.pop(ps.sector_code, None)
                if pos:
                    close_px = pos.last_close or pos.entry_price
                    trade = self._build_close_trade(
                        run.id, pos, last_day, close_px, ps,
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
            for eq in equity_curve:
                if eq.trade_date == days[-1]:
                    eq.equity = final_eq
                    break
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
        metrics = self._compute_metrics(
            run.id, all_trades, final_equity, benchmark,
            initial_capital=initial_capital,
            equity_series=equity_series,
        )
        save_backtest_results(run, all_trades, metrics, equity_curve, near_miss=near_miss_items)
        logger.info(
            "[A策略回测] 完成 run_id=%s 交易笔数=%d 期末资产=%.0f near_miss=%d",
            run.id, len(all_trades), final_equity, len(near_miss_items),
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

    def _get_warmup_days(self, start_date: date, count: int) -> list[date]:
        lookback_start = start_date - timedelta(days=count * 3)
        all_days = self.adapter.get_trade_days(lookback_start, start_date - timedelta(days=1))
        if not all_days:
            return []
        return all_days[-count:]

    def _get_scores(
        self,
        td: date,
        sector_codes: set[str],
        scanner: ScanService,
    ) -> dict[str, Any]:
        from app.services.volatile_scan import get_today_buffer

        rows: list = []
        buf = get_today_buffer()
        if buf and td in buf.scores_by_date:
            rows = list(buf.scores_by_date[td])
        score_map = {
            s.sector_code: s
            for s in rows
            if s.sector_code in sector_codes
        }
        missing = [code for code in sector_codes if code not in score_map]
        if missing:
            score_map.update(
                self._rebuild_missing_scores(td, missing, scanner)
            )
        return score_map

    def _rebuild_missing_scores(
        self,
        td: date,
        missing_sector_codes: list[str],
        scanner: ScanService,
    ) -> dict[str, Any]:
        from app.adapters.factory import get_adapter
        from app.services.a_strategy_manual_store import get_manual_inputs_for_day
        from app.services.volatile_merge import merge_leaders, merge_sector_daily, merge_sector_flow
        from app.services.volatile_scan import get_today_buffer

        lookback_start = td - timedelta(days=60)
        daily_all = merge_sector_daily(lookback_start, td)
        flow_all = merge_sector_flow(lookback_start, td)
        leader_map = {l.sector_code: l for l in merge_leaders(td)}
        env_row = self._get_env(td)
        index_pct = env_row.index_pct if env_row else 0.0
        manual_inputs = get_manual_inputs_for_day(td)
        adapter = get_adapter()

        market_money_by_day: dict[date, float] = {}
        for row in daily_all:
            market_money_by_day[row.trade_date] = (
                market_money_by_day.get(row.trade_date, 0.0)
                + float(getattr(row, "money", 0.0) or 0.0)
            )

        max_streak_map: dict[str, int] = {}
        buf = get_today_buffer()
        stocks = list(buf.stocks) if buf else []
        for s in stocks:
            if getattr(s, "trade_date", None) != td:
                continue
            code = getattr(s, "sector_code", "")
            streak = int(getattr(s, "limit_up_streak", 0) or 0)
            if streak > max_streak_map.get(code, 0):
                max_streak_map[code] = streak

        rebuilt: dict[str, Any] = {}
        for code in missing_sector_codes:
            d_rows = sorted(
                [r for r in daily_all if r.sector_code == code],
                key=lambda x: x.trade_date,
            )
            if not d_rows:
                continue
            f_rows = sorted(
                [r for r in flow_all if r.sector_code == code],
                key=lambda x: x.trade_date,
            )
            name = str(getattr(d_rows[-1], "sector_name", code) or code)
            leader = leader_map.get(code)
            streak = int(getattr(leader, "limit_up_streak", 0) or 0)
            pct5 = float(sum(float(getattr(r, "pct_change", 0.0) or 0.0) for r in d_rows[-5:]))
            total_money = float(getattr(d_rows[-1], "money", 0.0) or 0.0)
            leader_money = float(getattr(leader, "money", 0.0) or 0.0) if leader else 0.0
            leader_share = (leader_money / total_money) if total_money > 0 else 0.0

            metrics = scanner.engine.build_metrics_from_db(
                code,
                name,
                d_rows,
                f_rows,
                streak,
                pct5,
                leader_share,
                index_pct,
                market_money_by_day=market_money_by_day,
                max_limit_up_streak=max_streak_map.get(code, 0),
            )
            metrics.manual_flags = dict(manual_inputs.get(code, {}))
            idx_fn = getattr(adapter, "get_concept_index_history", None)
            if callable(idx_fn):
                idx_start = d_rows[0].trade_date - timedelta(days=60)
                idx_hist = idx_fn(code, idx_start, d_rows[-1].trade_date)
                if idx_hist:
                    self._override_trend_series_from_ths_index(metrics, idx_hist)

            sr = scanner.engine.score_sector(metrics, rank_pct=0.5, prev_stage="dormant")
            if env_row and not env_row.can_long:
                sr.position_hint = scanner.risk.adjust_position_hint(
                    sr.position_hint,
                    scanner.risk.env_from_model(env_row),
                )
            rebuilt[code] = self._score_result_row(td, sr)
        return rebuilt

    @staticmethod
    def _override_trend_series_from_ths_index(metrics: Any, idx_hist: dict[date, dict[str, Any]]) -> None:
        if not idx_hist:
            return
        ordered_days = sorted(idx_hist.keys())
        closes = [
            float(idx_hist[dt].get("close", 0.0) or 0.0)
            for dt in ordered_days
            if float(idx_hist[dt].get("close", 0.0) or 0.0) > 0
        ]
        if not closes:
            return
        ma20 = float(sum(closes[-20:]) / len(closes[-20:])) if len(closes) >= 20 else float(sum(closes) / len(closes))
        prev_slice = closes[-21:-1] if len(closes) >= 21 else closes[:-1]
        ma20_prev = (
            float(sum(prev_slice) / len(prev_slice))
            if prev_slice
            else ma20
        )
        metrics.close_history = closes
        metrics.ma20 = ma20
        metrics.ma20_prev = ma20_prev
        metrics.ma20_slope_up = ma20 > ma20_prev
        if len(closes) > 20 and closes[-21]:
            metrics.pct_20d = float((closes[-1] - closes[-21]) / closes[-21] * 100.0)

        volumes = [float(idx_hist[dt].get("volume", 0.0) or 0.0) for dt in ordered_days]
        monies = [float(idx_hist[dt].get("money", 0.0) or 0.0) for dt in ordered_days]
        if len(volumes) >= 5:
            ma5 = float(sum(volumes[-5:]) / 5.0)
            metrics.volume_history = volumes
            metrics.money_history = monies
            metrics.vol_ratio_5d = float(volumes[-1] / ma5) if ma5 > 0 else 0.0
            metrics.vol_ratio_debug = {
                "vol_last": volumes[-1],
                "vol_ma5": ma5,
                "vol_values_last6": volumes[-6:],
            }

    @staticmethod
    def _score_result_row(td: date, score_result: Any) -> Any:
        return SimpleNamespace(
            trade_date=td,
            sector_code=str(getattr(score_result, "sector_code", "")),
            sector_name=str(getattr(score_result, "sector_name", "")),
            rules_json=list(getattr(score_result, "rules", []) or []),
            rule_fail_reasons=list(getattr(score_result, "rule_fail_reasons", []) or []),
            stage=str(getattr(score_result, "stage", "dormant") or "dormant"),
            total_score=float(getattr(score_result, "total_score", 0.0) or 0.0),
            is_main_line=bool(getattr(score_result, "is_main_line", False)),
            main_line_tier=str(getattr(score_result, "main_line_tier", "rotation") or "rotation"),
            confirm_state=str(getattr(score_result, "confirm_state", "pending") or "pending"),
            exit_state=str(getattr(score_result, "exit_state", "normal") or "normal"),
        )

    @staticmethod
    def _get_env(td: date):
        from app.services.volatile_merge import get_market_env_merged
        return get_market_env_merged(td)

    def _leader_with_name(
        self, trade_date: date, sector_code: str,
    ) -> tuple[str, str]:
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

    def _compute_metrics(
        self,
        run_id: int,
        trades: list[BacktestTrade],
        equity: float,
        benchmark: float,
        *,
        initial_capital: float = 1_000_000,
        equity_series: Optional[list[float]] = None,
    ) -> BacktestMetric:
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

        return BacktestMetric(
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
        )


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
