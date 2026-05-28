"""回测结果 JSON 文件存储。

每个 run 存储为 data/backtest/runs/{run_id}.json，包含 run 元信息、trades、metrics、equity。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from app.config import settings
from app.models.tables import (
    BacktestEquityDaily,
    BacktestMetric,
    BacktestRun,
    BacktestTrade,
)

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_next_run_id: int = 0


def _base_dir() -> Path:
    return Path(settings.data_dir) / "backtest" / "runs"


def _run_path(run_id: int) -> Path:
    return _base_dir() / f"{run_id}.json"


def _date_str(d: Any) -> Optional[str]:
    if d is None:
        return None
    if isinstance(d, (date, datetime)):
        return d.isoformat()
    return str(d)


def _parse_date(s: Any) -> Optional[date]:
    if s is None:
        return None
    if isinstance(s, date):
        return s
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def _parse_datetime(s: Any) -> Optional[datetime]:
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    try:
        return datetime.fromisoformat(str(s))
    except (ValueError, TypeError):
        return None


def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _load_json(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _init_next_id() -> None:
    global _next_run_id
    base = _base_dir()
    if not base.is_dir():
        _next_run_id = 1
        return
    max_id = 0
    for p in base.glob("*.json"):
        try:
            rid = int(p.stem)
            max_id = max(max_id, rid)
        except ValueError:
            continue
    _next_run_id = max_id + 1


def _ensure_init() -> None:
    global _next_run_id
    if _next_run_id == 0:
        _init_next_id()


def _run_from_dict(d: dict) -> BacktestRun:
    return BacktestRun(
        id=int(d.get("id", 0)),
        status=str(d.get("status", "pending")),
        strategy_id=str(d.get("strategy_id", "")),
        start_date=_parse_date(d.get("start_date")) or date(1970, 1, 1),
        end_date=_parse_date(d.get("end_date")) or date(1970, 1, 1),
        params=dict(d.get("params") or {}),
        progress=int(d.get("progress", 0)),
        total_days=int(d.get("total_days", 0)),
        error_message=d.get("error_message"),
        created_at=_parse_datetime(d.get("created_at")),
        finished_at=_parse_datetime(d.get("finished_at")),
    )


def _trade_from_dict(d: dict) -> BacktestTrade:
    return BacktestTrade(
        id=int(d.get("id", 0)),
        run_id=int(d.get("run_id", 0)),
        sector_code=str(d.get("sector_code", "")),
        sector_name=str(d.get("sector_name", "")),
        stock_code=str(d.get("stock_code", "")),
        stock_name=d.get("stock_name"),
        sell_stock_code=d.get("sell_stock_code"),
        sell_stock_name=d.get("sell_stock_name"),
        alert_code=str(d.get("alert_code", "")),
        signal_date=_parse_date(d.get("signal_date")),
        entry_date=_parse_date(d.get("entry_date")) or date(1970, 1, 1),
        exit_date=_parse_date(d.get("exit_date")),
        entry_price=float(d.get("entry_price", 0)),
        exit_price=float(d["exit_price"]) if d.get("exit_price") is not None else None,
        return_pct=float(d["return_pct"]) if d.get("return_pct") is not None else None,
        holding_days=int(d["holding_days"]) if d.get("holding_days") is not None else None,
        trade_mode=str(d.get("trade_mode", "板块龙头个股")),
        human_reason=str(d.get("human_reason", "")),
        entry_scores=d.get("entry_scores"),
        exit_scores=d.get("exit_scores"),
    )


def _metric_from_dict(d: dict) -> BacktestMetric:
    return BacktestMetric(
        id=int(d.get("id", 0)),
        run_id=int(d.get("run_id", 0)),
        total_return=float(d.get("total_return", 0)),
        annual_return=float(d.get("annual_return", 0)),
        max_drawdown=float(d.get("max_drawdown", 0)),
        sharpe=float(d.get("sharpe", 0)),
        win_rate=float(d.get("win_rate", 0)),
        trade_count=int(d.get("trade_count", 0)),
        fish_body_capture=float(d.get("fish_body_capture", 0)),
        benchmark_return=float(d.get("benchmark_return", 0)),
        extra=dict(d.get("extra") or {}),
    )


def _equity_from_dict(d: dict) -> BacktestEquityDaily:
    return BacktestEquityDaily(
        id=int(d.get("id", 0)),
        run_id=int(d.get("run_id", 0)),
        trade_date=_parse_date(d.get("trade_date")) or date(1970, 1, 1),
        equity=float(d.get("equity", 0)),
        benchmark_equity=float(d.get("benchmark_equity", 1.0)),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_run(run: BacktestRun) -> BacktestRun:
    global _next_run_id
    with _lock:
        _ensure_init()
        run.id = _next_run_id
        _next_run_id += 1
        if run.created_at is None:
            run.created_at = datetime.utcnow()
        _save_run_file(run.id, run=run, trades=[], metrics=None, equity=[])
    return run


def get_run(run_id: int) -> Optional[BacktestRun]:
    data = _load_json(_run_path(run_id))
    if not data:
        return None
    return _run_from_dict(data.get("run", {}))


def list_runs(
    strategy_id: Optional[str] = None, limit: int = 20
) -> list[BacktestRun]:
    base = _base_dir()
    if not base.is_dir():
        return []
    files = sorted(base.glob("*.json"), key=lambda p: _file_id(p), reverse=True)
    result: list[BacktestRun] = []
    for f in files:
        data = _load_json(f)
        if not data:
            continue
        run = _run_from_dict(data.get("run", {}))
        if strategy_id and run.strategy_id != strategy_id:
            continue
        result.append(run)
        if len(result) >= limit:
            break
    return result


def update_run(run: BacktestRun) -> None:
    with _lock:
        data = _load_json(_run_path(run.id)) or {}
        trades = [_trade_from_dict(t) for t in data.get("trades", [])]
        metrics_raw = data.get("metrics")
        metrics = _metric_from_dict(metrics_raw) if metrics_raw else None
        equity = [_equity_from_dict(e) for e in data.get("equity", [])]
        existing_near_miss = data.get("near_miss")
        _save_run_file(run.id, run=run, trades=trades, metrics=metrics, equity=equity, near_miss=existing_near_miss)


def delete_run(run_id: int) -> bool:
    path = _run_path(run_id)
    if path.is_file():
        path.unlink()
        return True
    return False


def get_trades(run_id: int, offset: int = 0, limit: int = 200) -> list[BacktestTrade]:
    data = _load_json(_run_path(run_id))
    if not data:
        return []
    all_trades = [_trade_from_dict(t) for t in data.get("trades", [])]
    return all_trades[offset: offset + limit]


def get_metrics(run_id: int) -> Optional[BacktestMetric]:
    data = _load_json(_run_path(run_id))
    if not data or not data.get("metrics"):
        return None
    return _metric_from_dict(data["metrics"])


def get_equity(run_id: int) -> list[BacktestEquityDaily]:
    data = _load_json(_run_path(run_id))
    if not data:
        return []
    return [_equity_from_dict(e) for e in data.get("equity", [])]


def save_backtest_results(
    run: BacktestRun,
    trades: list[BacktestTrade],
    metrics: Optional[BacktestMetric],
    equity: list[BacktestEquityDaily],
    near_miss: Optional[list[dict]] = None,
) -> None:
    with _lock:
        _assign_trade_ids(trades)
        _save_run_file(run.id, run=run, trades=trades, metrics=metrics, equity=equity, near_miss=near_miss)


def append_equity(run_id: int, eq: BacktestEquityDaily) -> None:
    with _lock:
        data = _load_json(_run_path(run_id)) or {}
        equity_list = data.get("equity", [])
        equity_list.append(asdict(eq))
        data["equity"] = equity_list
        _atomic_write(_run_path(run_id), data)


def update_equity_value(run_id: int, trade_date: date, equity: float) -> None:
    with _lock:
        data = _load_json(_run_path(run_id)) or {}
        for e in data.get("equity", []):
            ed = _parse_date(e.get("trade_date"))
            if ed == trade_date:
                e["equity"] = equity
                break
        _atomic_write(_run_path(run_id), data)


def get_near_miss(run_id: int) -> list[dict]:
    data = _load_json(_run_path(run_id))
    if not data:
        return []
    return data.get("near_miss") or []


def flush_run(run: BacktestRun) -> None:
    """Persist current run state (progress etc.) without touching trades/metrics."""
    with _lock:
        data = _load_json(_run_path(run.id)) or {}
        data["run"] = _serialize_obj(run)
        _atomic_write(_run_path(run.id), data)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _file_id(p: Path) -> int:
    try:
        return int(p.stem)
    except ValueError:
        return 0


def _assign_trade_ids(trades: list[BacktestTrade]) -> None:
    for i, t in enumerate(trades, 1):
        t.id = i


def _serialize_obj(obj: Any) -> dict:
    d = asdict(obj)
    for k, v in d.items():
        if isinstance(v, (date, datetime)):
            d[k] = v.isoformat()
    return d


def _save_run_file(
    run_id: int,
    *,
    run: BacktestRun,
    trades: list[BacktestTrade],
    metrics: Optional[BacktestMetric],
    equity: list[BacktestEquityDaily],
    near_miss: Optional[list[dict]] = None,
) -> None:
    data = {
        "run": _serialize_obj(run),
        "trades": [_serialize_obj(t) for t in trades],
        "metrics": _serialize_obj(metrics) if metrics else None,
        "equity": [_serialize_obj(e) for e in equity],
    }
    if near_miss:
        data["near_miss"] = near_miss
    _atomic_write(_run_path(run_id), data)
