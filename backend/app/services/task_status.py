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
            "progress": self.progress,
            "total": self.total,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }


_lock = threading.Lock()
_scan_task = TaskState(task_type="scan", status="idle")


def get_scan_task() -> TaskState:
    with _lock:
        return TaskState(
            task_type=_scan_task.task_type,
            status=_scan_task.status,
            message=_scan_task.message,
            trade_date=_scan_task.trade_date,
            progress=_scan_task.progress,
            total=_scan_task.total,
            started_at=_scan_task.started_at,
            finished_at=_scan_task.finished_at,
            error=_scan_task.error,
        )


def start_scan(trade_date: str, message: str = "收盘扫描进行中…") -> None:
    with _lock:
        _scan_task.status = "running"
        _scan_task.message = message
        _scan_task.trade_date = trade_date
        _scan_task.progress = 0
        _scan_task.total = 0
        _scan_task.started_at = datetime.utcnow().isoformat() + "Z"
        _scan_task.finished_at = None
        _scan_task.error = None


def update_scan_progress(progress: int, total: int, message: Optional[str] = None) -> None:
    with _lock:
        _scan_task.progress = progress
        _scan_task.total = total
        if message:
            _scan_task.message = message


def finish_scan(sectors_scored: int, trade_date: str) -> None:
    with _lock:
        _scan_task.status = "done"
        _scan_task.message = f"扫描完成，已评分 {sectors_scored} 个板块"
        _scan_task.trade_date = trade_date
        _scan_task.finished_at = datetime.utcnow().isoformat() + "Z"


def fail_scan(error: str) -> None:
    with _lock:
        _scan_task.status = "failed"
        _scan_task.message = "扫描失败"
        _scan_task.error = error
        _scan_task.finished_at = datetime.utcnow().isoformat() + "Z"
