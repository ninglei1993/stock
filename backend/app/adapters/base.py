from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class SectorQuote:
    sector_code: str
    sector_name: str
    sector_type: str = "concept"
    pct_change: float = 0.0
    open: Optional[float] = None
    close: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: float = 0.0
    money: float = 0.0
    limit_up_count: int = 0
    big_yang_count: int = 0
    up_count: int = 0
    total_count: int = 0
    blow_up_rate: float = 0.0


@dataclass
class StockQuote:
    stock_code: str
    sector_code: str
    pct_change: float = 0.0
    open: Optional[float] = None
    close: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    high_limit: Optional[float] = None
    volume: float = 0.0
    money: float = 0.0
    is_limit_up: bool = False
    is_big_yang: bool = False
    is_blow_up: bool = False
    limit_up_streak: int = 0
    net_inflow_main: float = 0.0


@dataclass
class CapitalFlow:
    sector_code: str
    net_inflow_main: float = 0.0
    inflow_days: int = 0


@dataclass
class IndexBar:
    code: str
    trade_date: date
    open: float
    close: float
    high: float
    low: float
    pre_close: Optional[float] = None
    pct_change: float = 0.0


@dataclass
class ConceptInfo:
    code: str
    name: str


@dataclass
class MarketBreadth:
    trade_date: date
    limit_up_count: int = 0
    up_count: int = 0
    down_count: int = 0
    total_count: int = 0

    @property
    def up_down_ratio(self) -> float:
        total = self.up_count + self.down_count
        return self.up_count / total if total > 0 else 0.5


class MarketDataAdapter(ABC):
    @abstractmethod
    def get_trade_days(self, start_date: date, end_date: date) -> list[date]:
        pass

    @abstractmethod
    def list_concepts(self) -> list[ConceptInfo]:
        pass

    @abstractmethod
    def get_concept_stocks(self, concept_code: str, trade_date: date) -> list[str]:
        pass

    @abstractmethod
    def get_sector_quotes(self, trade_date: date, concept_codes: list[str]) -> list[SectorQuote]:
        pass

    @abstractmethod
    def get_stock_quotes(
        self, stock_codes: list[str], trade_date: date, sector_code: str = ""
    ) -> list[StockQuote]:
        pass

    @abstractmethod
    def get_capital_flows(
        self, stock_codes: list[str], trade_date: date, lookback: int = 5
    ) -> dict[str, list[float]]:
        """Return stock_code -> list of daily net inflow (most recent last)."""
        pass

    @abstractmethod
    def get_index_bars(self, code: str, start_date: date, end_date: date) -> list[IndexBar]:
        pass

    @abstractmethod
    def get_market_breadth(self, trade_date: date) -> MarketBreadth:
        pass

    def get_limit_up_streaks(
        self, stock_codes: list[str], trade_date: date, lookback: int = 10
    ) -> dict[str, int]:
        return {c: 0 for c in stock_codes}
