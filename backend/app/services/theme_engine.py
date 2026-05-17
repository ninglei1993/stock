from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import numpy as np

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


class ThemeEngine:
    WEIGHTS = {
        "persistence": 0.25,
        "capital": 0.30,
        "breadth": 0.25,
        "leader": 0.15,
        "relative": 0.05,
    }

    def score_sector(
        self,
        metrics: SectorMetrics,
        rank_pct: float,
        prev_stage: str = "dormant",
    ) -> ScoreResult:
        persistence = self._persistence_score(metrics, rank_pct)
        capital = self._capital_score(metrics)
        breadth = self._breadth_score(metrics)
        leader = self._leader_score(metrics)
        relative = self._relative_score(metrics)

        total = (
            persistence * self.WEIGHTS["persistence"]
            + capital * self.WEIGHTS["capital"]
            + breadth * self.WEIGHTS["breadth"]
            + leader * self.WEIGHTS["leader"]
            + relative * self.WEIGHTS["relative"]
        )

        is_filtered, reason = self._fake_theme_filter(metrics)
        if is_filtered:
            total *= 0.5

        stage = self._determine_stage(metrics, total, prev_stage)
        hint = self._position_hint(stage, total)

        return ScoreResult(
            sector_code=metrics.sector_code,
            sector_name=metrics.sector_name,
            total_score=round(total, 2),
            persistence_score=round(persistence, 2),
            capital_score=round(capital, 2),
            breadth_score=round(breadth, 2),
            leader_score=round(leader, 2),
            relative_score=round(relative, 2),
            stage=stage,
            is_filtered=is_filtered,
            filter_reason=reason,
            position_hint=hint,
        )

    def _persistence_score(self, m: SectorMetrics, rank_pct: float) -> float:
        if len(m.pct_history) >= 2:
            if m.pct_history[-1] > 0 and m.pct_history[-2] < -1:
                return 10.0
        consecutive_strong = sum(1 for p in m.pct_history[-3:] if p > 0)
        base = min(100, consecutive_strong * 25 + (1 - rank_pct) * 40)
        return float(np.clip(base, 0, 100))

    def _capital_score(self, m: SectorMetrics) -> float:
        inflow_score = min(60, m.inflow_days * 20)
        amount_score = min(40, max(0, m.net_inflow / 1e5))
        return float(np.clip(inflow_score + amount_score, 0, 100))

    def _breadth_score(self, m: SectorMetrics) -> float:
        lu = min(50, m.limit_up_count * 8)
        by = min(30, m.big_yang_count * 4)
        up = min(20, m.up_ratio * 20)
        return float(np.clip(lu + by + up, 0, 100))

    def _leader_score(self, m: SectorMetrics) -> float:
        streak = min(50, m.leader_streak * 15)
        pct5 = min(30, max(0, m.leader_pct_5d))
        share = min(20, m.leader_money_share * 100)
        return float(np.clip(streak + pct5 + share, 0, 100))

    def _relative_score(self, m: SectorMetrics) -> float:
        excess = m.pct_change - m.index_pct
        return float(np.clip(50 + excess * 10, 0, 100))

    def _fake_theme_filter(self, m: SectorMetrics) -> tuple[bool, Optional[str]]:
        if len(m.pct_history) >= 2 and m.pct_history[-1] > 2 and m.pct_history[-2] < -0.5:
            if len(m.pct_history) == 2 or m.pct_history[-3] < 0:
                return True, "一日游"
        if m.limit_up_count < 2 and m.inflow_days <= 1:
            return True, "观察：资金脉冲"
        return False, None

    def _determine_stage(self, m: SectorMetrics, total: float, prev: str) -> str:
        if m.net_inflow < 0 and len(m.pct_history) >= 3:
            if sum(m.pct_history[-3:]) < -3:
                return "decay"
        if m.blow_up_rate > 0.4 and total >= 70:
            return "decay"
        if total >= 85 and (m.blow_up_rate > 0.3 or m.limit_up_count >= 8):
            return "climax"
        if total >= 70 and (m.limit_up_count >= 5 or m.big_yang_count >= 8):
            return "ferment"
        if total >= 55 and m.inflow_days >= 2 and 1 <= m.limit_up_count <= 5:
            return "sprout"
        if total >= 55 and m.inflow_days >= 2:
            return "sprout"
        if prev in ("ferment", "climax") and total < 50:
            return "decay"
        return "dormant"

    def _position_hint(self, stage: str, total: float) -> str:
        hints = {
            "sprout": "light_position",
            "ferment": "hold",
            "climax": "reduce",
            "decay": "exit",
            "dormant": "observe",
        }
        return hints.get(stage, "observe")

    def rank_sectors(self, scores: list[ScoreResult]) -> list[ScoreResult]:
        active = [s for s in scores if not s.is_filtered or s.total_score >= 50]
        active.sort(key=lambda x: x.total_score, reverse=True)
        return active

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
    ) -> SectorMetrics:
        today = daily_rows[-1] if daily_rows else None
        flow = flow_rows[-1] if flow_rows else None
        pcts = [r.pct_change for r in daily_rows]
        total = today.total_count if today and today.total_count else 1
        up_ratio = (today.up_count / total) if today else 0
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
        )
