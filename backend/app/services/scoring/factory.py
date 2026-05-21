from __future__ import annotations

from app.services.scoring.base import ScoringEngine


def get_scoring_engine(mode: str | None = None) -> ScoringEngine:
    from app.services.scoring.a_strategy_adapter import AStrategyScoringAdapter

    del mode
    return AStrategyScoringAdapter()
