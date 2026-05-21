from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.tables import SectorDaily, SectorFlowDaily


STAGES = ("dormant", "sprout", "ferment", "climax", "decay")


@dataclass
class SectorMetrics:
    sector_code: str
    sector_name: str
    pct_change: float
    limit_up_count: int
    big_yang_count: int
    up_ratio: float
    blow_up_rate: float
    net_inflow: float
    inflow_days: int
    leader_streak: int
    leader_pct_5d: float
    leader_money_share: float
    pct_history: list[float]
    index_pct: float = 0.0
    close_history: list[float] = field(default_factory=list)
    volume_history: list[float] = field(default_factory=list)
    money_history: list[float] = field(default_factory=list)
    market_money_share_history: list[float] = field(default_factory=list)
    net_inflow_history: list[float] = field(default_factory=list)
    pct_20d: float = 0.0
    ma20: float = 0.0
    ma20_prev: float = 0.0
    ma20_slope_up: bool = False
    vol_ratio_5d: float = 0.0
    market_share_8d_ok: bool = False
    # 为 A 策略“量能持续性/成交额占比”规则提供可核算的中间量（用于排查口径/数据源）
    vol_ratio_debug: dict = field(default_factory=dict)
    market_share_8d_debug: list[dict] = field(default_factory=list)
    inflow_streak_days: int = 0
    max_limit_up_streak: int = 0
    manual_flags: dict | None = field(default_factory=dict)


@dataclass
class ScoreResult:
    sector_code: str
    sector_name: str
    total_score: float
    persistence_score: float
    capital_score: float
    breadth_score: float
    leader_score: float
    relative_score: float
    stage: str
    is_filtered: bool
    filter_reason: Optional[str]
    position_hint: str
    is_main_line: bool = False
    main_line_tier: str = "rotation"
    confirm_state: str = "pending"
    exit_state: str = "normal"
    rules: list[dict] | None = None
    rule_fail_reasons: list[str] | None = None
    source_tag: str = "auto"


class ThemeEngine:
    """
    A 策略需要的公共能力仅为“从已入库/内存快照的板块多日数据构建指标”。
    五维评分/阶段机已移除；具体规则评估与排序由各策略适配器负责。
    """

    def rank_sectors(self, scores: list[ScoreResult], *, keep_all: bool = False) -> list[ScoreResult]:
        del keep_all
        return sorted(scores, key=lambda x: x.total_score, reverse=True)

    def build_metrics_from_db(
        self,
        sector_code: str,
        sector_name: str,
        daily_rows: list,
        flow_rows: list,
        leader_streak: int,
        leader_pct_5d: float,
        leader_money_share: float,
        index_pct: float,
        market_money_by_day: dict[date, float] | None = None,
        max_limit_up_streak: int = 0,
    ) -> SectorMetrics:
        today = daily_rows[-1] if daily_rows else None
        flow = flow_rows[-1] if flow_rows else None
        pcts = [r.pct_change for r in daily_rows]
        closes = [float(getattr(r, "close", 0) or 0.0) for r in daily_rows]
        volumes = [float(getattr(r, "volume", 0) or 0.0) for r in daily_rows]
        monies = [float(getattr(r, "money", 0) or 0.0) for r in daily_rows]
        inflow_hist = [float(getattr(r, "net_inflow_main", 0) or 0.0) for r in flow_rows]
        total = today.total_count if today and today.total_count else 1
        up_ratio = (today.up_count / total) if today else 0

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

        def _calc_vol_ratio_5d(volume_values: list[float]) -> float:
            # 与同花顺日K成交量 MA5 对齐：MA5 使用“最近5日（含当日）”
            if len(volume_values) < 5:
                return 0.0
            ma5 = _avg(volume_values[-5:])
            if ma5 <= 0:
                return 0.0
            return float(volume_values[-1] / ma5)

        def _calc_share_history() -> list[float]:
            if not market_money_by_day:
                return []
            values: list[float] = []
            for r in daily_rows[-8:]:
                mk = float(market_money_by_day.get(r.trade_date, 0.0) or 0.0)
                if mk <= 0:
                    values.append(0.0)
                else:
                    values.append(
                        float((float(getattr(r, "money", 0) or 0.0) / mk) * 100.0)
                    )
            return values

        # ---- 可核算中间量（用于排查） ----
        def _calc_vol_ratio_debug(volume_values: list[float]) -> dict:
            if len(volume_values) < 5:
                return {}
            tail = [float(v or 0.0) for v in volume_values[-6:]]
            vol_last = tail[-1] if tail else 0.0
            ma5 = _avg([float(v or 0.0) for v in volume_values[-5:]])
            return {"vol_last": vol_last, "vol_ma5": ma5, "vol_values_last6": tail}

        def _calc_share_8d_debug() -> list[dict]:
            if not market_money_by_day:
                return []
            out: list[dict] = []
            for r in daily_rows[-8:]:
                td = str(getattr(r, "trade_date", ""))
                mk = float(market_money_by_day.get(getattr(r, "trade_date", None), 0.0) or 0.0)
                sector_money = float(getattr(r, "money", 0) or 0.0)
                share = 0.0 if mk <= 0 else float((sector_money / mk) * 100.0)
                out.append(
                    {
                        "trade_date": td,
                        "sector_money": sector_money,
                        "market_money": mk,
                        "share_pct": share,
                    }
                )
            return out

        def _streak_positive(values: list[float]) -> int:
            streak = 0
            for v in reversed(values):
                if v > 0:
                    streak += 1
                else:
                    break
            return streak

        ma20, ma20_prev = _calc_ma20(closes)
        pct_20d = _calc_pct_20d(closes)
        vol_ratio_5d = _calc_vol_ratio_5d(volumes)
        share_hist = _calc_share_history()
        share_8d_ok = len(share_hist) >= 8 and all(v >= 4.5 for v in share_hist[-8:])
        inflow_streak = _streak_positive(inflow_hist)
        vol_ratio_dbg = _calc_vol_ratio_debug(volumes)
        share_8d_dbg = _calc_share_8d_debug()

        return SectorMetrics(
            sector_code=sector_code,
            sector_name=sector_name,
            pct_change=today.pct_change if today else 0,
            limit_up_count=today.limit_up_count if today else 0,
            big_yang_count=today.big_yang_count if today else 0,
            up_ratio=up_ratio,
            blow_up_rate=today.blow_up_rate if today else 0,
            net_inflow=flow.net_inflow_main if flow else 0,
            inflow_days=flow.inflow_days if flow else 0,
            leader_streak=leader_streak,
            leader_pct_5d=leader_pct_5d,
            leader_money_share=leader_money_share,
            pct_history=pcts,
            index_pct=index_pct,
            close_history=closes,
            volume_history=volumes,
            money_history=monies,
            market_money_share_history=share_hist,
            net_inflow_history=inflow_hist,
            pct_20d=pct_20d,
            ma20=ma20,
            ma20_prev=ma20_prev,
            ma20_slope_up=ma20 > ma20_prev,
            vol_ratio_5d=vol_ratio_5d,
            market_share_8d_ok=share_8d_ok,
            vol_ratio_debug=vol_ratio_dbg,
            market_share_8d_debug=share_8d_dbg,
            inflow_streak_days=inflow_streak,
            max_limit_up_streak=max_limit_up_streak,
            manual_flags={},
        )
