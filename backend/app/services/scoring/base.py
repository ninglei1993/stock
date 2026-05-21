from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.services.theme_engine import ScoreResult


@dataclass(frozen=True)
class ScoreDimensionDef:
    key: str
    label: str
    weight_pct: int
    score_field: str
    description: str


class ScoringEngine(Protocol):
    mode: str

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
        market_money_by_day: dict | None = None,
        max_limit_up_streak: int = 0,
    ):
        ...

    def score_sector(
        self,
        metrics,
        rank_pct: float,
        prev_stage: str = "dormant",
    ) -> ScoreResult:
        ...

    def rank_sectors(
        self,
        scores: list[ScoreResult],
        *,
        keep_all: bool = False,
    ) -> list[ScoreResult]:
        ...

    def dimension_defs(self) -> list[ScoreDimensionDef]:
        ...
