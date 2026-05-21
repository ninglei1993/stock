"""A策略人工输入存储（hybrid_manual）。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from app.config import settings


@dataclass(frozen=True)
class ManualInputItem:
    trade_date: date
    sector_code: str
    values: dict[str, Any]


def _store_path() -> Path:
    return Path(settings.data_dir) / "a_strategy" / "manual_inputs.json"


def _read_all() -> dict[str, dict[str, dict[str, Any]]]:
    path = _store_path()
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return raw


def _atomic_write(data: dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def upsert_manual_input(trade_date: date, sector_code: str, values: dict[str, Any]) -> None:
    data = _read_all()
    key = trade_date.isoformat()
    day = data.setdefault(key, {})
    base = day.get(sector_code, {})
    if not isinstance(base, dict):
        base = {}
    merged = {**base, **values}
    day[sector_code] = merged
    _atomic_write(data)


def get_manual_inputs_for_day(trade_date: date) -> dict[str, dict[str, Any]]:
    data = _read_all()
    day = data.get(trade_date.isoformat(), {})
    return day if isinstance(day, dict) else {}


def get_manual_input(trade_date: date, sector_code: str) -> ManualInputItem | None:
    day = get_manual_inputs_for_day(trade_date)
    vals = day.get(sector_code)
    if vals is None:
        return None
    return ManualInputItem(trade_date=trade_date, sector_code=sector_code, values=dict(vals))


def delete_manual_input(trade_date: date, sector_code: str) -> bool:
    data = _read_all()
    key = trade_date.isoformat()
    day = data.get(key)
    if not isinstance(day, dict) or sector_code not in day:
        return False
    day.pop(sector_code, None)
    if not day:
        data.pop(key, None)
    _atomic_write(data)
    return True
