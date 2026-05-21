from datetime import date

from app.services import trade_calendar as tc


class _FakeAdapter:
    def get_trade_days(self, start_date: date, end_date: date) -> list[date]:
        return [
            d
            for d in (
                date(2026, 5, 16),
                date(2026, 5, 17),
                date(2026, 5, 18),
                date(2026, 5, 19),
                date(2026, 5, 20),
            )
            if start_date <= d <= end_date
        ]


def test_resolve_scan_date_clamps_to_completed_day(monkeypatch):
    monkeypatch.setattr(tc, "_latest_completed_trade_day", lambda: date(2026, 5, 19))
    monkeypatch.setattr(tc, "normalize_to_trade_day", lambda d: d)
    got = tc.resolve_scan_date(date(2026, 5, 20))
    assert got == date(2026, 5, 19)


def test_ui_default_scan_date_uses_completed_day(monkeypatch):
    monkeypatch.setattr(tc, "_latest_completed_trade_day", lambda: date(2026, 5, 19))
    assert tc.ui_default_scan_date() == date(2026, 5, 19)


def test_resolve_scan_trade_days_clamps_end(monkeypatch):
    import app.adapters.factory as factory

    monkeypatch.setattr(tc, "_latest_completed_trade_day", lambda: date(2026, 5, 19))
    monkeypatch.setattr(factory, "get_adapter", lambda: _FakeAdapter())
    days = tc.resolve_scan_trade_days(date(2026, 5, 18), date(2026, 5, 20), quiet=True)
    assert days == [date(2026, 5, 18), date(2026, 5, 19)]


def test_resolve_scan_trade_days_default_uses_completed_day(monkeypatch):
    import app.adapters.factory as factory

    monkeypatch.setattr(tc, "_latest_completed_trade_day", lambda: date(2026, 5, 19))
    monkeypatch.setattr(factory, "get_adapter", lambda: _FakeAdapter())
    days = tc.resolve_scan_trade_days(quiet=True)
    assert days[-1] == date(2026, 5, 19)
