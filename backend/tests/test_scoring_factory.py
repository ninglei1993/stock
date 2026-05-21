from app.services.scoring.a_strategy_adapter import AStrategyScoringAdapter
from app.services.scoring.factory import get_scoring_engine


def test_get_scoring_engine_always_a_strategy():
    assert isinstance(get_scoring_engine(None), AStrategyScoringAdapter)
    assert isinstance(get_scoring_engine("a_strategy"), AStrategyScoringAdapter)
    # five_dim 已移除，仍应回退到 A 策略实现
    assert isinstance(get_scoring_engine("five_dim"), AStrategyScoringAdapter)


def test_dimension_defs_empty_for_a_strategy():
    eng = get_scoring_engine()
    assert eng.dimension_defs() == []
