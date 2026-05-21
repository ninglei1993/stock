"""主线轮动回测逻辑单元测试。"""

from types import SimpleNamespace

from app.services.backtest_engine import BacktestEngine


def _score(code: str, total: float, capital: float = 50.0):
    return SimpleNamespace(
        sector_code=code,
        sector_name=code,
        total_score=total,
        capital_score=capital,
        persistence_score=capital,
        is_main_line=True,
        main_line_tier="secondary",
        is_filtered=False,
    )


def test_pick_rank1_highest_total():
    scores = [_score("A", 80), _score("B", 90)]
    top = BacktestEngine._pick_rank1(scores)
    assert top.sector_code == "B"


def test_streak_candidate_requires_min_days_and_not_held():
    streak = {"A": 3, "B": 1}
    score_map = {"A": _score("A", 70), "B": _score("B", 95)}
    assert BacktestEngine._pick_main_line_candidate(streak, "C", 3, score_map) == "A"
    assert BacktestEngine._pick_main_line_candidate(streak, "A", 3, score_map) is None
    assert BacktestEngine._pick_main_line_candidate(streak, None, 3, score_map) == "A"


def test_streak_candidate_tiebreak_by_score():
    streak = {"A": 3, "B": 3}
    score_map = {"A": _score("A", 70), "B": _score("B", 85)}
    assert BacktestEngine._pick_main_line_candidate(streak, None, 3, score_map) == "B"


def test_pick_rank1_a_strategy_tier_priority():
    a = _score("A", 66, 60)
    b = _score("B", 50, 90)
    a.main_line_tier = "secondary"
    b.main_line_tier = "top"
    top = BacktestEngine._pick_rank1_a_strategy([a, b])
    assert top.sector_code == "B"


def test_save_results_abs_mode_uses_equity_series():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    with patch("app.services.backtest_engine.get_adapter"):
        engine = BacktestEngine(MagicMock())
    engine.session = AsyncMock()
    engine.session.execute = AsyncMock()

    async def _run():
        await engine._save_results(
            1,
            [],
            1_000_000,
            1.2,
            initial_capital=1_000_000,
            equity_series=[1_000_000, 1_200_000, 1_000_000, 1_350_000],
        )

    asyncio.run(_run())
    metric = engine.session.add.call_args[0][0]
    assert metric.total_return == 35.0
    assert metric.max_drawdown == round((1_200_000 - 1_000_000) / 1_200_000 * 100, 2)
