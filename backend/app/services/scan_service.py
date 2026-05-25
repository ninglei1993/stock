from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.storage_mode import uses_scan_memory_buffer
from app.models.tables import SectorScoreDaily
from app.services.alert_service import AlertService
from app.services.volatile_merge import (
    get_market_env_merged,
    merge_leaders,
    merge_sector_daily,
    merge_sector_flow,
)
from app.services.risk import RiskModule
from app.services.scoring.factory import get_scoring_engine
from app.utils.timing_log import log_elapsed
from app.services.a_strategy_manual_store import get_manual_inputs_for_day
from app.adapters.factory import get_adapter

import logging
import pandas as pd

logger = logging.getLogger(__name__)


class ScanService:
    def __init__(self, session: AsyncSession, scoring_mode: str | None = None):
        self.session = session
        self.scoring_mode = scoring_mode or settings.effective_scoring_mode()
        self.engine = get_scoring_engine(self.scoring_mode)
        self.risk = RiskModule()
        self.alerts = AlertService()

    async def run_scan(self, trade_date: date) -> list[SectorScoreDaily]:
        logger.info(
            "[流程] 板块评分(mode=%s)：从数据库/内存读取各板块多日行情与资金流，不再调用 Tushare 全市场接口",
            self.scoring_mode,
        )
        logger.info("[数据] ScanService.run_scan 开始 trade_date=%s", trade_date)
        with log_elapsed("ScanService.run_scan 读库+评分+预警", logger_obj=logger):
            return await self._run_scan_inner(trade_date)

    async def _run_scan_inner(self, trade_date: date) -> list[SectorScoreDaily]:
        def _avg(values: list[float]) -> float:
            return float(sum(values) / len(values)) if values else 0.0

        def _calc_ma20(history: list[float]) -> tuple[float, float]:
            if not history:
                return 0.0, 0.0
            ma20_now = _avg(history[-20:]) if len(history) >= 20 else _avg(history)
            prev_slice = history[-21:-1] if len(history) >= 21 else history[:-1]
            ma20_prev = _avg(prev_slice) if prev_slice else ma20_now
            return ma20_now, ma20_prev

        def _calc_pct_20d(history: list[float]) -> float:
            if len(history) <= 20:
                return 0.0
            base = history[-21]
            if not base:
                return 0.0
            return float((history[-1] - base) / base * 100.0)

        def _override_trend_series_from_ths_index(metrics, daily_rows: list, idx_hist: dict) -> None:
            if not idx_hist:
                return
            ordered_days = sorted(idx_hist.keys())
            closes = [
                float(idx_hist[td].get("close", 0.0) or 0.0)
                for td in ordered_days
                if float(idx_hist[td].get("close", 0.0) or 0.0) > 0
            ]
            if not closes or closes[-1] <= 0:
                return
            ma20, ma20_prev = _calc_ma20(closes)
            metrics.close_history = closes
            metrics.ma20 = ma20
            metrics.ma20_prev = ma20_prev
            metrics.ma20_slope_up = ma20 > ma20_prev
            metrics.pct_20d = _calc_pct_20d(closes)
            # 若 ths_daily 提供指数成交量，则优先采用同花顺板块指数口径计算 MA5/放量比。
            vol_hist = [float(idx_hist[td].get("volume", 0.0) or 0.0) for td in ordered_days]
            money_hist = [float(idx_hist[td].get("money", 0.0) or 0.0) for td in ordered_days]
            if vol_hist and all(v > 0 for v in vol_hist[-5:]) and len(vol_hist) >= 5:
                ma5 = _avg(vol_hist[-5:])
                metrics.volume_history = vol_hist
                metrics.money_history = money_hist
                metrics.vol_ratio_5d = float(vol_hist[-1] / ma5) if ma5 > 0 else 0.0
                metrics.vol_ratio_debug = {
                    "vol_last": vol_hist[-1],
                    "vol_ma5": ma5,
                    "vol_values_last6": vol_hist[-6:],
                }

        lookback_start = trade_date - timedelta(days=60)
        daily_all = await merge_sector_daily(
            self.session, lookback_start, trade_date
        )

        flow_all = await merge_sector_flow(
            self.session, lookback_start, trade_date
        )

        leaders = await merge_leaders(self.session, trade_date)
        leader_map = {l.sector_code: l for l in leaders}

        env_row = await get_market_env_merged(self.session, trade_date)
        index_pct = env_row.index_pct if env_row else 0.0

        sectors_today = {r.sector_code for r in daily_all if r.trade_date == trade_date}
        market_money_by_day: dict[date, float] = {}
        if settings.market_cache_enabled:
            from app.services.market_cache import MarketTable, get_market_cache

            store = get_market_cache()
            need_days = sorted({r.trade_date for r in daily_all})
            for td in need_days:
                df = store.load(MarketTable.DAILY, td)
                if df is None or df.empty:
                    continue
                if "amount" not in df.columns:
                    continue
                total = float(pd.to_numeric(df["amount"], errors="coerce").fillna(0.0).sum())
                if total > 0:
                    market_money_by_day[td] = total

        # 兜底：若全市场缓存缺失，则退化为“已入库板块成交额求和”。
        # 注意：当用户只勾选很少板块时，这会导致市占=100%（仅用于兜底，不作为正确口径）。
        if not market_money_by_day:
            for row in daily_all:
                market_money_by_day[row.trade_date] = (
                    market_money_by_day.get(row.trade_date, 0.0)
                    + float(getattr(row, "money", 0.0) or 0.0)
                )
        pct_sorted = sorted(
            [r.pct_change for r in daily_all if r.trade_date == trade_date],
            reverse=True,
        )
        max_streak_map: dict[str, int] = {}
        from app.services.volatile_scan import get_today_buffer

        buf = get_today_buffer()
        stocks = list(buf.stocks) if buf else []
        for s in stocks:
            if getattr(s, "trade_date", None) != trade_date:
                continue
            code = getattr(s, "sector_code", "")
            streak = int(getattr(s, "limit_up_streak", 0) or 0)
            if streak > max_streak_map.get(code, 0):
                max_streak_map[code] = streak

        manual_inputs = get_manual_inputs_for_day(trade_date) if self.scoring_mode == "a_strategy" else {}
        adapter = get_adapter() if self.scoring_mode == "a_strategy" else None

        yesterday = trade_date - timedelta(days=1)
        from app.services.theme_engine import ScoreResult

        prev_score_map: dict[str, ScoreResult] = {}
        prev_rows: list = []
        buf = get_today_buffer()
        if buf and yesterday in buf.scores_by_date:
            prev_rows = list(buf.scores_by_date[yesterday])
        for r in prev_rows:
            prev_score_map[r.sector_code] = ScoreResult(
                sector_code=r.sector_code,
                sector_name=r.sector_name,
                total_score=r.total_score,
                persistence_score=r.persistence_score,
                capital_score=r.capital_score,
                breadth_score=r.breadth_score,
                leader_score=r.leader_score,
                relative_score=r.relative_score,
                stage=r.stage,
                is_filtered=r.is_filtered,
                filter_reason=r.filter_reason,
                position_hint=r.position_hint,
            )

        results: list[ScoreResult] = []
        for code in sectors_today:
            d_rows = sorted(
                [r for r in daily_all if r.sector_code == code], key=lambda x: x.trade_date
            )
            f_rows = sorted(
                [r for r in flow_all if r.sector_code == code], key=lambda x: x.trade_date
            )
            if not d_rows:
                continue
            name = d_rows[-1].sector_name
            leader = leader_map.get(code)
            streak = leader.limit_up_streak if leader else 0
            pct5 = sum(r.pct_change for r in d_rows[-5:]) if d_rows else 0
            total_money = d_rows[-1].money or 1
            leader_share = (leader.money / total_money) if leader and total_money else 0

            metrics = self.engine.build_metrics_from_db(
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
            if self.scoring_mode == "a_strategy":
                metrics.manual_flags = dict(manual_inputs.get(code, {}))
                idx_fn = getattr(adapter, "get_concept_index_history", None) if adapter is not None else None
                if callable(idx_fn):
                    idx_start = d_rows[0].trade_date - timedelta(days=60)
                    idx_hist = idx_fn(code, idx_start, d_rows[-1].trade_date)
                    if idx_hist:
                        _override_trend_series_from_ths_index(metrics, d_rows, idx_hist)
            try:
                rank_pct = pct_sorted.index(d_rows[-1].pct_change) / len(pct_sorted)
            except ValueError:
                rank_pct = 0.5
            prev_stage = prev_score_map.get(code).stage if code in prev_score_map else "dormant"
            sr = self.engine.score_sector(metrics, rank_pct, prev_stage)
            if env_row and not env_row.can_long:
                sr.position_hint = self.risk.adjust_position_hint(sr.position_hint, self.risk.env_from_model(env_row))
            results.append(sr)

        from app.services.ingest_settings_store import read_scan_sectors_selection

        use_explicit, _ = read_scan_sectors_selection()
        ranked = self.engine.rank_sectors(results, keep_all=use_explicit)

        today_map = {r.sector_code: r for r in ranked}
        saved: list[SectorScoreDaily] = []
        for i, sr in enumerate(ranked):
            row = SectorScoreDaily(
                trade_date=trade_date,
                sector_code=sr.sector_code,
                sector_name=sr.sector_name,
                total_score=sr.total_score,
                persistence_score=sr.persistence_score,
                capital_score=sr.capital_score,
                breadth_score=sr.breadth_score,
                leader_score=sr.leader_score,
                relative_score=sr.relative_score,
                stage=sr.stage,
                rank=i + 1,
                is_filtered=sr.is_filtered,
                filter_reason=sr.filter_reason,
                position_hint=sr.position_hint,
                is_main_line=sr.is_main_line,
                main_line_tier=sr.main_line_tier,
                confirm_state=sr.confirm_state,
                exit_state=sr.exit_state,
                rules_json=sr.rules or [],
                rule_fail_reasons="；".join(sr.rule_fail_reasons or []),
                source_tag=sr.source_tag,
            )
            saved.append(row)

        env_bad = False
        if env_row:
            prev_env = await get_market_env_merged(self.session, yesterday)
            if prev_env and env_row.env_score < 40 and env_row.env_score < prev_env.env_score - 20:
                env_bad = True

        alert_items = self.alerts.diff_alerts(
            trade_date, today_map, prev_score_map, env_bad=env_bad
        )

        buf = get_today_buffer()
        if buf is not None:
            buf.scores_by_date[trade_date] = list(saved)

        logger.info(
            "[数据] ScanService.run_scan 完成 trade_date=%s sectors_scored=%d alerts=%d memory_buffer=%s",
            trade_date,
            len(saved),
            len(alert_items),
            uses_scan_memory_buffer(),
        )
        return saved
