"""单次收盘扫描的易失快照（不写 PostgreSQL，仅内存）。

启用 `SCAN_VOLATILE_STORAGE=true` 时使用：仍会经历完整行情拉取与评分计算，
但能去掉「入库」环节的 DELETE / INSERT / commit，适合验证瓶颈不在磁盘写入时使用。

仪表盘优先读最近一次内存快照。多 worker / 重启后快照丢失——正式环境慎用。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional


@dataclass
class VolatileTodayBuffer:
    """本次扫描交易日的板块/资金流/龙头/市场环境（不写库）。"""

    trade_date: date
    market_env: Any | None = None
    sectors_by_code: dict[str, Any] = field(default_factory=dict)
    flows_by_code: dict[str, Any] = field(default_factory=dict)
    stocks: list[Any] = field(default_factory=list)
    leaders_by_code: dict[str, Any] = field(default_factory=dict)
    scores_by_date: dict[date, list[Any]] = field(default_factory=dict)
    sector_rows: list[Any] = field(default_factory=list)
    flow_rows: list[Any] = field(default_factory=list)
    leader_rows: list[Any] = field(default_factory=list)

    def reset(self, td: date) -> None:
        self.trade_date = td
        self.market_env = None
        self.sectors_by_code.clear()
        self.flows_by_code.clear()
        self.stocks.clear()
        self.leaders_by_code.clear()
        self.scores_by_date.clear()
        self.sector_rows.clear()
        self.flow_rows.clear()
        self.leader_rows.clear()


@dataclass
class VolatileDashboardSnapshot:
    trade_date: date
    env: Any | None
    scores: list[Any]
    leader_map: dict[str, Any]
    scan_trade_days: list[date] = field(default_factory=list)
    sector_dailies: dict[str, dict] = field(default_factory=dict)
    sector_flows: dict[str, dict] = field(default_factory=dict)


_lock = threading.Lock()
_today: Optional[VolatileTodayBuffer] = None
_last_dashboard: Optional[VolatileDashboardSnapshot] = None


def prepare_today_buffer(trade_date: date, *, append: bool = False) -> None:
    """append=True 时保留已写入的成分股等多日数据（多日扫描）。"""
    global _today
    with _lock:
        if append and _today is not None:
            _today.trade_date = trade_date
            return
        buf = VolatileTodayBuffer(trade_date=trade_date)
        buf.reset(trade_date)
        _today = buf


def get_today_buffer() -> Optional[VolatileTodayBuffer]:
    with _lock:
        return _today


def set_dashboard_snapshot(snapshot: VolatileDashboardSnapshot) -> None:
    global _last_dashboard
    with _lock:
        _last_dashboard = snapshot


def get_dashboard_snapshot() -> Optional[VolatileDashboardSnapshot]:
    with _lock:
        return _last_dashboard


def clear_volatile_snapshots() -> None:
    """清空内存快照。"""
    global _today, _last_dashboard
    with _lock:
        _today = None
        _last_dashboard = None
