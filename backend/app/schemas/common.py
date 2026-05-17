from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ConceptOut(BaseModel):
    sector_code: str
    sector_name: str


class SectorScoreOut(BaseModel):
    sector_code: str
    sector_name: str
    total_score: float
    stage: str
    rank: int
    is_scored: bool = True
    persistence_score: float
    capital_score: float
    breadth_score: float
    leader_score: float
    relative_score: float
    position_hint: str
    leader_stock: Optional[str] = None
    leader_streak: Optional[int] = None
    pct_change: Optional[float] = None
    is_filtered: bool = False
    filter_reason: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class SectorListOut(BaseModel):
    trade_date: Optional[date]
    universe_total: int
    sectors_scored: int
    demo_mode: bool
    is_live_data: bool = False
    data_source: str
    data_source_label: str = ""
    data_source_short: str = ""
    jq_configured: bool
    sectors: list[SectorScoreOut]


class TaskStatusOut(BaseModel):
    task_type: str
    status: str
    message: str = ""
    trade_date: Optional[str] = None
    progress: int = 0
    total: int = 0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None


class JqDataRangeOut(BaseModel):
    start: date
    end: date
    latest_trade_day: date
    label: str


class SystemStatusOut(BaseModel):
    adapter: str
    demo_mode: bool
    is_live_data: bool = False
    data_source_label: str = ""
    data_source_short: str = ""
    jq_configured: bool
    universe_total: int
    ingest_max_concepts: int
    scan_task: TaskStatusOut
    jq_data_range: Optional[JqDataRangeOut] = None
    default_scan_date: Optional[date] = None


class MarketEnvOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trade_date: date
    env_score: float
    limit_up_count: int
    up_down_ratio: float
    index_pct: float
    conclusion: str
    can_long: bool


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trade_date: date
    sector_code: str
    sector_name: str
    alert_code: str
    human_reason: str
    created_at: datetime


class DashboardOut(BaseModel):
    trade_date: Optional[date]
    market_env: Optional[MarketEnvOut]
    top_sectors: list[SectorScoreOut]
    latest_scan: Optional[datetime] = None


class StockInSector(BaseModel):
    stock_code: str
    stock_name: str = ""
    pct_change: float
    is_limit_up: bool
    limit_up_streak: int
    money: float


class ScoreDimensionOut(BaseModel):
    key: str
    label: str
    weight_pct: int
    score: float
    description: str


class FlowDayOut(BaseModel):
    trade_date: date
    net_inflow_wan: float
    net_inflow_yi: float


class SectorDetailOut(BaseModel):
    sector_code: str
    sector_name: str
    trade_date: date
    stage: str
    total_score: float
    scores: dict[str, float]
    score_dimensions: list[ScoreDimensionOut] = []
    limit_up_count: int
    big_yang_count: int
    net_inflow_main: float
    net_inflow_yi: float = 0.0
    inflow_days: int = 0
    up_count: int = 0
    total_count: int = 0
    up_ratio: float = 0.0
    blow_up_rate: float = 0.0
    position_hint: str = "observe"
    leader: Optional[dict[str, Any]] = None
    stocks: list[StockInSector] = []
    history: list[dict[str, Any]] = []
    flow_history: list[FlowDayOut] = []


class ReviewDayOut(BaseModel):
    trade_date: date
    sectors: list[dict[str, Any]]


class BacktestCreate(BaseModel):
    strategy_id: str = "fish_body"
    start_date: date
    end_date: date
    params: dict[str, Any] = Field(default_factory=dict)


class BacktestRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    strategy_id: str
    start_date: date
    end_date: date
    progress: int
    total_days: int
    error_message: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None


class BacktestTradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sector_code: str
    sector_name: str
    stock_code: str
    stock_name: str = ""
    sell_stock_code: Optional[str] = None
    sell_stock_name: str = ""
    alert_code: str
    alert_name_cn: str = ""
    signal_date: Optional[date] = None
    entry_date: date
    exit_date: Optional[date] = None
    entry_price: float
    exit_price: Optional[float] = None
    return_pct: Optional[float] = None
    holding_days: Optional[int] = None
    trade_mode: str = "板块龙头个股"
    entry_timing_cn: str = "信号日次日开盘价"
    exit_timing_cn: str = "卖出信号日次日开盘价"
    human_reason: str


class EquityPointOut(BaseModel):
    trade_date: str
    equity: float
    benchmark: float


class BacktestReport(BaseModel):
    run: BacktestRunOut
    metrics: Optional[dict[str, Any]] = None
    equity_curve: list[EquityPointOut] = []
    stage_win_rates: dict[str, float] = {}
    trade_mode_note: str = ""
    strategy_name_cn: str = ""
