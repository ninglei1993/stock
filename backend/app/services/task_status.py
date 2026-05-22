"""后台任务状态（收盘扫描等），供前端轮询展示。"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class TaskState:
    task_type: str
    status: str  # idle | running | done | failed
    message: str = ""
    trade_date: Optional[str] = None
    scan_start_date: Optional[str] = None
    scan_end_date: Optional[str] = None
    trade_days: list[str] = field(default_factory=list)
    progress: int = 0
    total: int = 0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "status": self.status,
            "message": self.message,
            "trade_date": self.trade_date,
            "scan_start_date": self.scan_start_date,
            "scan_end_date": self.scan_end_date,
            "trade_days": self.trade_days,
            "progress": self.progress,
            "total": self.total,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }


_lock = threading.Lock()
_scan_task = TaskState(task_type="scan", status="idle")
_cancel_requested = False


def get_scan_task() -> TaskState:
    with _lock:
        return TaskState(
            task_type=_scan_task.task_type,
            status=_scan_task.status,
            message=_scan_task.message,
            trade_date=_scan_task.trade_date,
            scan_start_date=_scan_task.scan_start_date,
            scan_end_date=_scan_task.scan_end_date,
            trade_days=list(_scan_task.trade_days),
            progress=_scan_task.progress,
            total=_scan_task.total,
            started_at=_scan_task.started_at,
            finished_at=_scan_task.finished_at,
            error=_scan_task.error,
        )


def start_scan(
    trade_date: str,
    message: str = "收盘扫描进行中…",
    *,
    total: int = 0,
    scan_start_date: Optional[str] = None,
    scan_end_date: Optional[str] = None,
    trade_days: Optional[list[str]] = None,
) -> None:
    with _lock:
        _scan_task.status = "running"
        _scan_task.message = message
        _scan_task.trade_date = trade_date
        _scan_task.scan_start_date = scan_start_date
        _scan_task.scan_end_date = scan_end_date
        _scan_task.trade_days = list(trade_days or [])
        _scan_task.progress = 0
        _scan_task.total = max(0, total)
        _scan_task.started_at = datetime.utcnow().isoformat() + "Z"
        _scan_task.finished_at = None
        _scan_task.error = None


def update_scan_progress(
    progress: int,
    total: int,
    message: Optional[str] = None,
    *,
    current_trade_date: Optional[str] = None,
) -> None:
    with _lock:
        _scan_task.progress = progress
        _scan_task.total = total
        if message:
            _scan_task.message = message
        if current_trade_date:
            _scan_task.trade_date = current_trade_date


def finish_scan(sectors_scored: int, trade_date: str) -> None:
    with _lock:
        _scan_task.status = "done"
        _scan_task.message = f"扫描完成，已评分 {sectors_scored} 个板块"
        _scan_task.trade_date = trade_date
        if _scan_task.total > 0:
            _scan_task.progress = _scan_task.total
        _scan_task.finished_at = datetime.utcnow().isoformat() + "Z"


def fail_scan(error: str) -> None:
    with _lock:
        _scan_task.status = "failed"
        _scan_task.message = "扫描失败"
        _scan_task.error = error
        _scan_task.finished_at = datetime.utcnow().isoformat() + "Z"


def request_cancel_scan() -> bool:
    global _cancel_requested
    with _lock:
        if _scan_task.status != "running":
            return False
        _cancel_requested = True
        _scan_task.message = "正在停止扫描…"
        return True


def is_cancel_requested() -> bool:
    with _lock:
        return _cancel_requested


def clear_cancel_flag() -> None:
    global _cancel_requested
    with _lock:
        _cancel_requested = False


def cancel_scan() -> None:
    global _cancel_requested
    with _lock:
        _scan_task.status = "failed"
        _scan_task.message = "扫描已被用户停止"
        _scan_task.error = "用户手动停止"
        _scan_task.finished_at = datetime.utcnow().isoformat() + "Z"
        _cancel_requested = False
