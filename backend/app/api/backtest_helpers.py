from typing import Any, Optional

from app.labels import ALERT_LABELS
from app.models.tables import BacktestTrade
from app.schemas.common import BacktestTradeOut, ScoreSnapshotOut
from app.services.stock_names import resolve_stock_name


def _scores_out(raw: Any) -> Optional[ScoreSnapshotOut]:
    if not raw or not isinstance(raw, dict):
        return None
    return ScoreSnapshotOut(
        total=float(raw.get("total", 0) or 0),
        persistence=float(raw.get("persistence", 0) or 0),
        capital=float(raw.get("capital", 0) or 0),
        breadth=float(raw.get("breadth", 0) or 0),
        leader=float(raw.get("leader", 0) or 0),
        relative=float(raw.get("relative", 0) or 0),
        stage=str(raw.get("stage", "dormant") or "dormant"),
    )


__all__ = ["trade_to_out"]


def trade_to_out(row: BacktestTrade) -> BacktestTradeOut:
    sell_code = row.sell_stock_code or row.stock_code
    stock_name = row.stock_name or resolve_stock_name(row.stock_code)
    sell_name = row.sell_stock_name or row.stock_name or resolve_stock_name(sell_code)
    return BacktestTradeOut(
        id=row.id,
        sector_code=row.sector_code,
        sector_name=row.sector_name,
        stock_code=row.stock_code,
        stock_name=stock_name,
        sell_stock_code=sell_code,
        sell_stock_name=sell_name,
        alert_code=row.alert_code,
        alert_name_cn=ALERT_LABELS.get(row.alert_code, row.alert_code),
        signal_date=row.signal_date or row.entry_date,
        entry_date=row.entry_date,
        exit_date=row.exit_date,
        entry_price=row.entry_price,
        exit_price=row.exit_price,
        return_pct=row.return_pct,
        holding_days=row.holding_days,
        trade_mode=row.trade_mode or "板块龙头个股",
        entry_timing_cn="信号日次日开盘（约09:30）",
        exit_timing_cn=(
            "信号日次日开盘（约09:30）"
            if row.exit_date
            else (
                "持仓中（收益按结束日收盘价估算）"
                if row.alert_code == "MAIN_LINE_BUY" and row.return_pct is not None
                else (
                    "持仓中（区间结束未触发卖出）"
                    if row.alert_code == "MAIN_LINE_BUY"
                    else "—"
                )
            )
        ),
        human_reason=row.human_reason,
        entry_scores=_scores_out(row.entry_scores),
        exit_scores=_scores_out(row.exit_scores),
    )
