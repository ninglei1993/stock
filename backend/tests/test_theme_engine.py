from app.services.theme_engine import SectorMetrics, ThemeEngine


def test_sprout_stage():
    engine = ThemeEngine()
    m = SectorMetrics(
        sector_code="GN970",
        sector_name="商业航天",
        pct_change=2.5,
        limit_up_count=2,
        big_yang_count=5,
        up_ratio=0.7,
        blow_up_rate=0.1,
        net_inflow=50000,
        inflow_days=3,
        leader_streak=2,
        leader_pct_5d=15,
        leader_money_share=0.2,
        pct_history=[1.0, 1.5, 2.5],
        index_pct=0.5,
    )
    result = engine.score_sector(m, rank_pct=0.1, prev_stage="dormant")
    assert result.stage in ("sprout", "ferment", "dormant")
    assert result.total_score > 0


def test_fake_theme_one_day():
    engine = ThemeEngine()
    m = SectorMetrics(
        sector_code="X",
        sector_name="测试",
        pct_change=3.0,
        limit_up_count=0,
        big_yang_count=1,
        up_ratio=0.5,
        blow_up_rate=0,
        net_inflow=100,
        inflow_days=1,
        leader_streak=0,
        leader_pct_5d=0,
        leader_money_share=0,
        pct_history=[-1.0, 3.0],
        index_pct=0,
    )
    result = engine.score_sector(m, rank_pct=0.5)
    assert result.is_filtered is True
