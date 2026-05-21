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
    leader_stock_name: Optional[str] = None
    leader_streak: Optional[int] = None
    pct_change: Optional[float] = None
    is_filtered: bool = False
    filter_reason: Optional[str] = None
    is_main_line: bool = False
    main_line_tier: str = "rotation"
    confirm_state: str = "pending"
    exit_state: str = "normal"
    source_tag: str = "auto"
    rules: list[dict[str, Any]] = Field(default_factory=list)
    rule_fail_reasons: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class SectorListOut(BaseModel):
    trade_date: Optional[date]
    universe_total: int
    sectors_scored: int
    is_live_data: bool = False
    data_source: str
    data_source_label: str = ""
    data_source_short: str = ""
    sectors: list[SectorScoreOut]


class TaskStatusOut(BaseModel):
    task_type: str
    status: str
    message: str = ""
    trade_date: Optional[str] = None
    scan_start_date: Optional[str] = None
    scan_end_date: Optional[str] = None
    trade_days: list[str] = Field(default_factory=list)
    progress: int = 0
    total: int = 0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None


class SetIngestSettingsIn(BaseModel):
    max_stocks_per_concept: int = Field(ge=0, le=500, description="0=不限制，分析全部成分股")


class ScanSectorsOut(BaseModel):
    use_explicit_selection: bool = False
    selected_codes: list[str] = Field(default_factory=list)
    universe: list[ConceptOut] = Field(default_factory=list)


class SetScanSectorsIn(BaseModel):
    use_explicit_selection: bool = True
    selected_codes: list[str] = Field(default_factory=list)


class TusharePingOut(BaseModel):
    ok: bool
    tushare_configured: bool = False
    adapter: str = ""
    endpoint: str = ""
    latency_ms: Optional[int] = None
    sample_rows: Optional[int] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None


class SystemStatusOut(BaseModel):
    adapter: str
    is_live_data: bool = False
    data_source_label: str = ""
    data_source_short: str = ""
    tushare_configured: bool = False
    universe_total: int
    ingest_max_concepts: int
    ingest_concept_filter: str = ""
    scan_scope_label: str = ""
    ingest_max_stocks_per_concept: int = 0
    use_explicit_sector_selection: bool = False
    selected_sector_count: int = 0
    scan_volatile_storage: bool = False
    scan_task: TaskStatusOut
    default_scan_date: Optional[date] = None
    default_scan_start: Optional[date] = None
    default_scan_end: Optional[date] = None


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
    market_overview: Optional[dict[str, Any]] = None


class StockPctDayOut(BaseModel):
    trade_date: date
    pct_change: float


class StockInSector(BaseModel):
    stock_code: str
    stock_name: str = ""
    pct_change: float
    pct_trade_date: Optional[date] = None
    is_limit_up: bool
    limit_up_streak: int
    money: float
    pct_history: list[StockPctDayOut] = Field(default_factory=list)


class RuleEvalOut(BaseModel):
    key: str
    label: str
    passed: bool
    threshold: str = ""
    current: Any = None
    source: str = "auto"


class FlowDayOut(BaseModel):
    trade_date: date
    net_inflow_wan: float
    net_inflow_yi: float


class SectorDetailOut(BaseModel):
    sector_code: str
    sector_name: str
    trade_date: date
    pct_display_days: list[date] = Field(default_factory=list)
    stage: str
    total_score: float
    is_main_line: bool = False
    main_line_tier: str = "rotation"
    confirm_state: str = "pending"
    exit_state: str = "normal"
    source_tag: str = "auto"
    rules: list[RuleEvalOut] = Field(default_factory=list)
    rule_fail_reasons: list[str] = Field(default_factory=list)
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
    data_missing_items: list[str] = []


class ReviewDayOut(BaseModel):
    trade_date: date
    sectors: list[dict[str, Any]]


class ScoreSnapshotOut(BaseModel):
    total: float = 0
    persistence: float = 0
    capital: float = 0
    breadth: float = 0
    leader: float = 0
    relative: float = 0
    stage: str = "dormant"
    is_main_line: bool = False
    main_line_tier: str = "rotation"


class BacktestSectorCandidateOut(BaseModel):
    sector_code: str
    sector_name: str
    rank: int = 0
    total_score: float = 0
    stage: str = "dormant"
    persistence_score: float = 0
    capital_score: float = 0
    breadth_score: float = 0
    leader_score: float = 0
    relative_score: float = 0
    is_main_line: bool = False
    main_line_tier: str = "rotation"
    confirm_state: str = "pending"
    exit_state: str = "normal"
    source_tag: str = "auto"
    rules: list[dict[str, Any]] = Field(default_factory=list)
    rule_fail_reasons: list[str] = Field(default_factory=list)


class AStrategyManualInputIn(BaseModel):
    trade_date: date
    sector_code: str
    auction_passed: Optional[bool] = None
    negative_news: Optional[bool] = None
    northbound_5d_yi: Optional[float] = None
    notes: str = ""


class AStrategyManualInputOut(BaseModel):
    trade_date: date
    sector_code: str
    values: dict[str, Any] = Field(default_factory=dict)


class AStrategyListOut(BaseModel):
    trade_date: Optional[date]
    sectors: list[SectorScoreOut] = Field(default_factory=list)


class BacktestSectorCandidatesOut(BaseModel):
    trade_date: Optional[date] = None
    sectors: list[BacktestSectorCandidateOut] = Field(default_factory=list)


class BacktestCreate(BaseModel):
    strategy_id: str = "main_line_rotation"
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
    params: dict[str, Any] = {}
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
    entry_scores: Optional[ScoreSnapshotOut] = None
    exit_scores: Optional[ScoreSnapshotOut] = None


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
