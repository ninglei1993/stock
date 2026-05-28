from datetime import date, datetime

from app.models.tables import Alert, MarketEnvDaily
from app.schemas.common import AlertOut, MarketEnvOut


def test_market_env_from_dataclass():
    row = MarketEnvDaily(
        trade_date=date(2026, 5, 17),
        env_score=65.0,
        limit_up_count=50,
        up_down_ratio=0.55,
        index_pct=1.2,
        conclusion="caution",
        can_long=True,
    )
    out = MarketEnvOut.model_validate(row)
    assert out.env_score == 65.0
    assert out.conclusion == "caution"


def test_alert_from_dataclass():
    row = Alert(
        id=1,
        trade_date=date(2026, 5, 17),
        sector_code="GN759",
        sector_name="航空航天",
        alert_code="NEW_SPROUT",
        human_reason="test",
        created_at=datetime(2026, 5, 17, 15, 0, 0),
    )
    out = AlertOut.model_validate(row)
    assert out.alert_code == "NEW_SPROUT"
