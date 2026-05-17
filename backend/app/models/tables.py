from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TradeCalendar(Base):
    __tablename__ = "trade_calendar"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_open: Mapped[bool] = mapped_column(default=True)


class SectorDaily(Base):
    __tablename__ = "sector_daily"
    __table_args__ = (UniqueConstraint("trade_date", "sector_code", name="uq_sector_daily"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    sector_code: Mapped[str] = mapped_column(String(32), index=True)
    sector_name: Mapped[str] = mapped_column(String(128))
    sector_type: Mapped[str] = mapped_column(String(16), default="concept")
    open: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pct_change: Mapped[float] = mapped_column(Float, default=0.0)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    money: Mapped[float] = mapped_column(Float, default=0.0)
    limit_up_count: Mapped[int] = mapped_column(Integer, default=0)
    big_yang_count: Mapped[int] = mapped_column(Integer, default=0)
    up_count: Mapped[int] = mapped_column(Integer, default=0)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    blow_up_rate: Mapped[float] = mapped_column(Float, default=0.0)


class SectorFlowDaily(Base):
    __tablename__ = "sector_flow_daily"
    __table_args__ = (UniqueConstraint("trade_date", "sector_code", name="uq_sector_flow"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    sector_code: Mapped[str] = mapped_column(String(32), index=True)
    net_inflow_main: Mapped[float] = mapped_column(Float, default=0.0)
    inflow_days: Mapped[int] = mapped_column(Integer, default=0)


class StockDaily(Base):
    __tablename__ = "stock_daily"
    __table_args__ = (
        UniqueConstraint("trade_date", "stock_code", "sector_code", name="uq_stock_daily"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    stock_code: Mapped[str] = mapped_column(String(32), index=True)
    sector_code: Mapped[str] = mapped_column(String(32), index=True)
    open: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pct_change: Mapped[float] = mapped_column(Float, default=0.0)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    money: Mapped[float] = mapped_column(Float, default=0.0)
    is_limit_up: Mapped[bool] = mapped_column(default=False)
    is_big_yang: Mapped[bool] = mapped_column(default=False)
    is_blow_up: Mapped[bool] = mapped_column(default=False)
    limit_up_streak: Mapped[int] = mapped_column(Integer, default=0)


class SectorScoreDaily(Base):
    __tablename__ = "sector_score_daily"
    __table_args__ = (UniqueConstraint("trade_date", "sector_code", name="uq_sector_score"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    sector_code: Mapped[str] = mapped_column(String(32), index=True)
    sector_name: Mapped[str] = mapped_column(String(128))
    total_score: Mapped[float] = mapped_column(Float, default=0.0)
    persistence_score: Mapped[float] = mapped_column(Float, default=0.0)
    capital_score: Mapped[float] = mapped_column(Float, default=0.0)
    breadth_score: Mapped[float] = mapped_column(Float, default=0.0)
    leader_score: Mapped[float] = mapped_column(Float, default=0.0)
    relative_score: Mapped[float] = mapped_column(Float, default=0.0)
    stage: Mapped[str] = mapped_column(String(16), default="dormant")
    rank: Mapped[int] = mapped_column(Integer, default=0)
    is_filtered: Mapped[bool] = mapped_column(default=False)
    filter_reason: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    position_hint: Mapped[str] = mapped_column(String(32), default="observe")


class ThemeLeaderDaily(Base):
    __tablename__ = "theme_leader_daily"
    __table_args__ = (UniqueConstraint("trade_date", "sector_code", name="uq_theme_leader"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    sector_code: Mapped[str] = mapped_column(String(32), index=True)
    stock_code: Mapped[str] = mapped_column(String(32))
    stock_name: Mapped[str] = mapped_column(String(64), default="")
    limit_up_streak: Mapped[int] = mapped_column(Integer, default=0)
    pct_change: Mapped[float] = mapped_column(Float, default=0.0)
    money: Mapped[float] = mapped_column(Float, default=0.0)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    sector_code: Mapped[str] = mapped_column(String(32), index=True)
    sector_name: Mapped[str] = mapped_column(String(128))
    alert_code: Mapped[str] = mapped_column(String(32), index=True)
    human_reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MarketEnvDaily(Base):
    __tablename__ = "market_env_daily"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    env_score: Mapped[float] = mapped_column(Float, default=50.0)
    limit_up_count: Mapped[int] = mapped_column(Integer, default=0)
    up_down_ratio: Mapped[float] = mapped_column(Float, default=0.5)
    index_pct: Mapped[float] = mapped_column(Float, default=0.0)
    conclusion: Mapped[str] = mapped_column(String(32), default="caution")
    can_long: Mapped[bool] = mapped_column(default=True)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    strategy_id: Mapped[str] = mapped_column(String(32))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    total_days: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    sector_code: Mapped[str] = mapped_column(String(32))
    sector_name: Mapped[str] = mapped_column(String(128))
    stock_code: Mapped[str] = mapped_column(String(32))
    sell_stock_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    alert_code: Mapped[str] = mapped_column(String(32))
    signal_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    entry_date: Mapped[date] = mapped_column(Date)
    exit_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    return_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    holding_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    trade_mode: Mapped[str] = mapped_column(String(32), default="板块龙头个股")
    human_reason: Mapped[str] = mapped_column(Text, default="")


class BacktestMetric(Base):
    __tablename__ = "backtest_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    total_return: Mapped[float] = mapped_column(Float, default=0.0)
    annual_return: Mapped[float] = mapped_column(Float, default=0.0)
    max_drawdown: Mapped[float] = mapped_column(Float, default=0.0)
    sharpe: Mapped[float] = mapped_column(Float, default=0.0)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)
    trade_count: Mapped[int] = mapped_column(Integer, default=0)
    fish_body_capture: Mapped[float] = mapped_column(Float, default=0.0)
    benchmark_return: Mapped[float] = mapped_column(Float, default=0.0)
    extra: Mapped[dict] = mapped_column(JSONB, default=dict)


class BacktestEquityDaily(Base):
    __tablename__ = "backtest_equity_daily"
    __table_args__ = (UniqueConstraint("run_id", "trade_date", name="uq_bt_equity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    trade_date: Mapped[date] = mapped_column(Date)
    equity: Mapped[float] = mapped_column(Float)
    benchmark_equity: Mapped[float] = mapped_column(Float, default=1.0)
