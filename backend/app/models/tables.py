"""数据模型 — 纯 dataclass（不依赖 SQLAlchemy / 数据库）。

所有模型仅用于进程内内存缓冲和 JSON 序列化，字段保持向后兼容。
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass
class TradeCalendar:
    trade_date: date
    is_open: bool = True


@dataclass
class SectorDaily:
    trade_date: date = date(1970, 1, 1)
    sector_code: str = ""
    sector_name: str = ""
    sector_type: str = "concept"
    open: Optional[float] = None
    close: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    pct_change: float = 0.0
    volume: float = 0.0
    money: float = 0.0
    limit_up_count: int = 0
    big_yang_count: int = 0
    up_count: int = 0
    total_count: int = 0
    blow_up_rate: float = 0.0


@dataclass
class SectorFlowDaily:
    trade_date: date = date(1970, 1, 1)
    sector_code: str = ""
    net_inflow_main: float = 0.0
    inflow_days: int = 0


@dataclass
class StockDaily:
    trade_date: date = date(1970, 1, 1)
    stock_code: str = ""
    sector_code: str = ""
    open: Optional[float] = None
    close: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    pct_change: float = 0.0
    volume: float = 0.0
    money: float = 0.0
    is_limit_up: bool = False
    is_big_yang: bool = False
    is_blow_up: bool = False
    limit_up_streak: int = 0


@dataclass
class SectorScoreDaily:
    trade_date: date = date(1970, 1, 1)
    sector_code: str = ""
    sector_name: str = ""
    total_score: float = 0.0
    persistence_score: float = 0.0
    capital_score: float = 0.0
    breadth_score: float = 0.0
    leader_score: float = 0.0
    relative_score: float = 0.0
    stage: str = "dormant"
    rank: int = 0
    is_filtered: bool = False
    filter_reason: Optional[str] = None
    position_hint: str = "observe"
    is_main_line: bool = False
    main_line_tier: str = "rotation"
    confirm_state: str = "pending"
    exit_state: str = "normal"
    rules_json: Optional[list] = None
    rule_fail_reasons: Optional[str] = None
    source_tag: str = "auto"


@dataclass
class ThemeLeaderDaily:
    trade_date: date = date(1970, 1, 1)
    sector_code: str = ""
    stock_code: str = ""
    stock_name: str = ""
    limit_up_streak: int = 0
    pct_change: float = 0.0
    money: float = 0.0


@dataclass
class Alert:
    trade_date: date = date(1970, 1, 1)
    sector_code: str = ""
    sector_name: str = ""
    alert_code: str = ""
    human_reason: str = ""
    created_at: Optional[datetime] = None
    id: Optional[int] = None


@dataclass
class MarketEnvDaily:
    trade_date: date = date(1970, 1, 1)
    env_score: float = 50.0
    limit_up_count: int = 0
    up_down_ratio: float = 0.5
    index_pct: float = 0.0
    conclusion: str = "caution"
    can_long: bool = True


@dataclass
class BacktestRun:
    id: int = 0
    status: str = "pending"
    strategy_id: str = ""
    start_date: date = date(1970, 1, 1)
    end_date: date = date(1970, 1, 1)
    params: dict = field(default_factory=dict)
    progress: int = 0
    total_days: int = 0
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


@dataclass
class BacktestTrade:
    run_id: int = 0
    sector_code: str = ""
    sector_name: str = ""
    stock_code: str = ""
    stock_name: Optional[str] = None
    sell_stock_code: Optional[str] = None
    sell_stock_name: Optional[str] = None
    alert_code: str = ""
    signal_date: Optional[date] = None
    entry_date: date = date(1970, 1, 1)
    exit_date: Optional[date] = None
    entry_price: float = 0.0
    exit_price: Optional[float] = None
    return_pct: Optional[float] = None
    holding_days: Optional[int] = None
    trade_mode: str = "板块龙头个股"
    human_reason: str = ""
    entry_scores: Optional[dict] = None
    exit_scores: Optional[dict] = None
    id: int = 0


@dataclass
class BacktestMetric:
    run_id: int = 0
    total_return: float = 0.0
    annual_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    win_rate: float = 0.0
    trade_count: int = 0
    fish_body_capture: float = 0.0
    benchmark_return: float = 0.0
    extra: dict = field(default_factory=dict)
    id: int = 0


@dataclass
class BacktestEquityDaily:
    run_id: int = 0
    trade_date: date = date(1970, 1, 1)
    equity: float = 0.0
    benchmark_equity: float = 1.0
    id: int = 0
