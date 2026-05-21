from app.services.scoring.a_strategy_adapter import AStrategyScoringAdapter
from app.services.theme_engine import SectorMetrics


def _metrics(**overrides) -> SectorMetrics:
    base = dict(
        sector_code="GN001",
        sector_name="测试主线",
        pct_change=2.0,
        limit_up_count=3,
        big_yang_count=6,
        up_ratio=0.65,
        blow_up_rate=0.15,
        net_inflow=220000,
        inflow_days=3,
        leader_streak=2,
        leader_pct_5d=12.0,
        leader_money_share=0.25,
        pct_history=[0.5, 1.2, 2.0],
        index_pct=0.4,
    )
    base.update(overrides)
    return SectorMetrics(**base)


def test_a_strategy_scores_and_stage():
    engine = AStrategyScoringAdapter()
    result = engine.score_sector(_metrics(), rank_pct=0.15, prev_stage="dormant")
    assert 0 <= result.total_score <= 100
    assert result.persistence_score in (0, 100)
    assert result.capital_score in (0, 100)
    assert result.breadth_score in (0, 100)
    assert result.leader_score in (0, 100)
    assert result.relative_score in (0, 100)
    assert result.stage in ("dormant", "sprout", "ferment", "climax", "decay")
    assert isinstance(result.rules, list)
    assert result.main_line_tier in ("top", "secondary", "rotation")


def test_a_strategy_fail_has_reasons():
    engine = AStrategyScoringAdapter()
    result = engine.score_sector(
        _metrics(
            inflow_days=1,
            limit_up_count=0,
            up_ratio=0.2,
            max_limit_up_streak=0,
            close_history=[100] * 8,
        ),
        rank_pct=0.5,
        prev_stage="dormant",
    )
    assert result.is_filtered is True
    assert result.is_main_line is False
    assert len(result.rule_fail_reasons or []) >= 1
