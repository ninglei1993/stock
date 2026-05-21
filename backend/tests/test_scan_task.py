"""扫盘任务状态与交易日解析回归测试。"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.services import task_status
from app.services.trade_calendar import (
    normalize_to_trade_day,
    resolve_scan_date,
    resolve_scan_trade_days,
)


@pytest.fixture(autouse=True)
def reset_task():
    task_status._scan_task.status = "idle"
    task_status._scan_task.progress = 0
    task_status._scan_task.total = 0
    task_status._scan_task.message = ""
    task_status._scan_task.trade_date = None
    task_status._scan_task.scan_start_date = None
    task_status._scan_task.scan_end_date = None
    task_status._scan_task.trade_days = []
    yield


def test_start_scan_preserves_total():
    task_status.start_scan("2026-04-17", "启动", total=50)
    t = task_status.get_scan_task()
    assert t.total == 50
    assert t.progress == 0
    assert t.trade_date == "2026-04-17"


def test_progress_not_wiped_by_second_start_scan_with_total():
    task_status.start_scan("2026-04-17", "启动", total=50)
    task_status.update_scan_progress(12, 50, "正在入库 12/50…")
    task_status.start_scan("2026-04-17", "误触发的二次启动", total=50)
    t = task_status.get_scan_task()
    assert t.total == 50
    assert t.progress == 0


def test_update_progress_after_start():
    task_status.start_scan("2026-02-13", total=50)
    task_status.update_scan_progress(3, 50, "正在入库 3/50…")
    t = task_status.get_scan_task()
    assert t.progress == 3
    assert t.message == "正在入库 3/50…"


def test_normalize_to_trade_day_snaps_weekend():
    mock_adapter = MagicMock()
    mock_adapter.get_trade_days.return_value = [
        date(2026, 4, 15),
        date(2026, 4, 16),
        date(2026, 4, 17),
    ]
    with patch("app.adapters.factory.get_adapter", return_value=mock_adapter):
        assert normalize_to_trade_day(date(2026, 4, 18)) == date(2026, 4, 17)
        assert normalize_to_trade_day(date(2026, 4, 17)) == date(2026, 4, 17)


def test_resolve_scan_date_tushare_mode():
    with (
        patch("app.services.trade_calendar._latest_completed_trade_day", return_value=date(2026, 4, 17)),
        patch("app.services.trade_calendar.normalize_to_trade_day", return_value=date(2026, 4, 17)),
    ):
        assert resolve_scan_date(date(2026, 4, 18)) == date(2026, 4, 17)


def test_resolve_scan_trade_days_sorts_descending_calendar():
    """Tushare trade_cal 可能倒序返回，解析后应升序。"""
    unsorted = [
        date(2026, 5, 15),
        date(2026, 5, 12),
        date(2026, 5, 8),
        date(2026, 5, 6),
    ]
    mock_adapter = MagicMock()
    mock_adapter.get_trade_days.return_value = unsorted
    with (
        patch("app.adapters.factory.get_adapter", return_value=mock_adapter),
    ):
        picked = resolve_scan_trade_days(date(2026, 5, 1), date(2026, 5, 15), quiet=True)
    assert picked == sorted(unsorted)


def test_lookback_trade_days_empty_when_anchor_before_range():
    from app.services import scan_context

    may = [date(2026, 5, 6), date(2026, 5, 7)]
    scan_context.set_scan_bounds(may, calendar_start=date(2026, 5, 6), calendar_end=date(2026, 5, 7))
    try:
        days = scan_context.lookback_trade_days(date(2026, 5, 1), 5)
        assert days == []
    finally:
        scan_context.clear_scan_context()


def test_lookback_trade_days_clamped_to_scan_boundary():
    from app.services import scan_context

    may = [
        date(2026, 5, 6),
        date(2026, 5, 7),
        date(2026, 5, 8),
        date(2026, 5, 9),
        date(2026, 5, 12),
    ]
    scan_context.set_scan_bounds(
        may, calendar_start=date(2026, 5, 6), calendar_end=date(2026, 5, 12)
    )
    try:
        days = scan_context.lookback_trade_days(date(2026, 5, 12), 8)
        assert days == may
        assert date(2026, 4, 22) not in days
    finally:
        scan_context.clear_scan_context()


def test_finish_scan_sets_progress_to_total():
    task_status.start_scan("2026-05-15", total=20)
    task_status.update_scan_progress(5, 20)
    task_status.finish_scan(3, "2026-05-15")
    t = task_status.get_scan_task()
    assert t.status == "done"
    assert t.progress == 20
    assert t.total == 20


def test_resolve_scan_trade_days_uses_explicit_calendar_range():
    """用户选 5/1~5/15 时不应被 resolve_scan_date 对齐到 4 月。"""
    may_days = [
        date(2026, 5, 6),
        date(2026, 5, 7),
        date(2026, 5, 8),
        date(2026, 5, 11),
        date(2026, 5, 12),
    ]
    mock_adapter = MagicMock()

    def _trade_days(start, end):
        if start == date(2026, 5, 1) and end == date(2026, 5, 15):
            return may_days
        return []

    mock_adapter.get_trade_days.side_effect = _trade_days
    with (
        patch("app.adapters.factory.get_adapter", return_value=mock_adapter),
    ):
        picked = resolve_scan_trade_days(date(2026, 5, 1), date(2026, 5, 15))
    assert picked == may_days
    mock_adapter.get_trade_days.assert_called_with(date(2026, 5, 1), date(2026, 5, 15))
