from datetime import date

from app.services.a_strategy_manual_store import (
    delete_manual_input,
    get_manual_input,
    get_manual_inputs_for_day,
    upsert_manual_input,
)


def test_manual_store_upsert_and_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import settings

    settings.data_dir = tmp_path
    td = date(2026, 5, 20)
    upsert_manual_input(
        td,
        "BK001",
        {
            "auction_passed": True,
            "negative_news": False,
            "northbound_5d_yi": 3.2,
        },
    )
    day_map = get_manual_inputs_for_day(td)
    assert "BK001" in day_map
    got = get_manual_input(td, "BK001")
    assert got is not None
    assert got.values["auction_passed"] is True
    assert delete_manual_input(td, "BK001") is True
    assert get_manual_input(td, "BK001") is None
