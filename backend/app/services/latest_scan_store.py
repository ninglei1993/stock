"""扫盘最新结果 scan/latest.json（每次覆盖）。"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)

SNAPSHOT_VERSION = 1


@dataclass
class LoadedScore:
    trade_date: date
    sector_code: str
    sector_name: str
    total_score: float
    persistence_score: float
    capital_score: float
    breadth_score: float
    leader_score: float
    relative_score: float
    stage: str
    rank: int
    is_filtered: bool = False
    filter_reason: Optional[str] = None
    position_hint: str = "observe"
    is_main_line: bool = False
    main_line_tier: str = "rotation"
    confirm_state: str = "pending"
    exit_state: str = "normal"
    rules_json: Optional[list[dict[str, Any]]] = None
    rule_fail_reasons: Optional[list[str]] = None
    source_tag: str = "auto"


@dataclass
class LoadedLeader:
    trade_date: date
    sector_code: str
    stock_code: str
    stock_name: Optional[str] = None
    limit_up_streak: int = 0
    pct_change: float = 0.0
    money: float = 0.0


@dataclass
class LoadedMarketEnv:
    trade_date: date
    env_score: float
    limit_up_count: int
    up_down_ratio: float
    index_pct: float
    conclusion: str
    can_long: bool


@dataclass
class LoadedLatestScan:
    trade_date: date
    scan_start_date: Optional[date]
    scan_end_date: Optional[date]
    trade_days: list[date]
    market_env: LoadedMarketEnv | None
    scores: list[LoadedScore]
    leader_map: dict[str, LoadedLeader]
    saved_at: Optional[str] = None
    sector_dailies: dict[str, dict] = field(default_factory=dict)
    sector_flows: dict[str, dict] = field(default_factory=dict)


def scan_latest_path() -> Path:
    return Path(settings.data_dir) / "scan" / "latest.json"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    data = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _score_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    return {
        "trade_date": getattr(row, "trade_date", None),
        "sector_code": row.sector_code,
        "sector_name": row.sector_name,
        "total_score": row.total_score,
        "persistence_score": row.persistence_score,
        "capital_score": row.capital_score,
        "breadth_score": row.breadth_score,
        "leader_score": row.leader_score,
        "relative_score": row.relative_score,
        "stage": row.stage,
        "rank": row.rank,
        "is_filtered": getattr(row, "is_filtered", False),
        "filter_reason": getattr(row, "filter_reason", None),
        "position_hint": row.position_hint,
        "is_main_line": getattr(row, "is_main_line", False),
        "main_line_tier": getattr(row, "main_line_tier", "rotation"),
        "confirm_state": getattr(row, "confirm_state", "pending"),
        "exit_state": getattr(row, "exit_state", "normal"),
        "rules_json": getattr(row, "rules_json", None) or getattr(row, "rules", None),
        "rule_fail_reasons": getattr(row, "rule_fail_reasons", None),
        "source_tag": getattr(row, "source_tag", "auto"),
    }


def _leader_to_dict(leader: Any) -> dict[str, Any]:
    if leader is None:
        return {}
    if isinstance(leader, dict):
        return leader
    return {
        "trade_date": getattr(leader, "trade_date", None),
        "sector_code": leader.sector_code,
        "stock_code": leader.stock_code,
        "stock_name": getattr(leader, "stock_name", None),
        "limit_up_streak": leader.limit_up_streak,
        "pct_change": getattr(leader, "pct_change", None),
        "money": getattr(leader, "money", None),
    }


def _env_to_dict(env: Any) -> Optional[dict[str, Any]]:
    if env is None:
        return None
    if isinstance(env, dict):
        return env
    return {
        "trade_date": env.trade_date,
        "env_score": env.env_score,
        "limit_up_count": env.limit_up_count,
        "up_down_ratio": env.up_down_ratio,
        "index_pct": env.index_pct,
        "conclusion": env.conclusion,
        "can_long": env.can_long,
    }


def _sector_daily_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    return {
        "pct_change": float(getattr(row, "pct_change", 0) or 0),
        "limit_up_count": int(getattr(row, "limit_up_count", 0) or 0),
        "big_yang_count": int(getattr(row, "big_yang_count", 0) or 0),
        "up_count": int(getattr(row, "up_count", 0) or 0),
        "total_count": int(getattr(row, "total_count", 0) or 0),
        "blow_up_rate": float(getattr(row, "blow_up_rate", 0) or 0),
        "money": float(getattr(row, "money", 0) or 0),
        "close": float(getattr(row, "close", 0) or 0),
    }


def _sector_flow_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    return {
        "net_inflow_main": float(getattr(row, "net_inflow_main", 0) or 0),
        "inflow_days": int(getattr(row, "inflow_days", 0) or 0),
    }


def _parse_date(v: Any) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


class LatestScanStore:
    @staticmethod
    def save(
        *,
        trade_date: date,
        scores: list[Any],
        market_env: Any | None,
        leader_map: dict[str, Any],
        scan_trade_days: list[date],
        scan_start_date: Optional[date] = None,
        scan_end_date: Optional[date] = None,
        market_cache_stats: Optional[dict[str, int]] = None,
        sector_dailies: dict[str, Any] | None = None,
        sector_flows: dict[str, Any] | None = None,
    ) -> Path:
        leaders_ser = {code: _leader_to_dict(l) for code, l in leader_map.items()}
        payload: dict[str, Any] = {
            "version": SNAPSHOT_VERSION,
            "trade_date": trade_date.isoformat(),
            "scan_start_date": (scan_start_date or (scan_trade_days[0] if scan_trade_days else trade_date)).isoformat(),
            "scan_end_date": (scan_end_date or trade_date).isoformat(),
            "trade_days": [d.isoformat() for d in scan_trade_days],
            "market_env": _env_to_dict(market_env),
            "scores": [_score_to_dict(s) for s in scores],
            "leaders": leaders_ser,
            "sector_dailies": {code: _sector_daily_to_dict(d) for code, d in (sector_dailies or {}).items()},
            "sector_flows": {code: _sector_flow_to_dict(f) for code, f in (sector_flows or {}).items()},
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        if market_cache_stats:
            payload["market_cache_stats"] = market_cache_stats
        path = scan_latest_path()
        _atomic_write_json(path, payload)
        logger.info(
            "[latest_scan] 已写入 %s trade_date=%s scores=%d",
            path,
            trade_date,
            len(scores),
        )
        return path

    @staticmethod
    def load() -> Optional[LoadedLatestScan]:
        path = scan_latest_path()
        if not path.is_file():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[latest_scan] 读取失败: %s", exc)
            return None

        td = _parse_date(raw.get("trade_date"))
        if not td:
            return None

        trade_days = [_parse_date(x) for x in raw.get("trade_days") or []]
        trade_days = [d for d in trade_days if d]

        env_dict = raw.get("market_env")
        env_row: LoadedMarketEnv | None = None
        if env_dict:
            env_row = LoadedMarketEnv(
                trade_date=_parse_date(env_dict.get("trade_date")) or td,
                env_score=float(env_dict.get("env_score", 0)),
                limit_up_count=int(env_dict.get("limit_up_count", 0)),
                up_down_ratio=float(env_dict.get("up_down_ratio", 0)),
                index_pct=float(env_dict.get("index_pct", 0)),
                conclusion=str(env_dict.get("conclusion", "")),
                can_long=bool(env_dict.get("can_long", True)),
            )

        scores: list[LoadedScore] = []
        for s in raw.get("scores") or []:
            scores.append(
                LoadedScore(
                    trade_date=_parse_date(s.get("trade_date")) or td,
                    sector_code=s["sector_code"],
                    sector_name=s.get("sector_name", s["sector_code"]),
                    total_score=float(s.get("total_score", 0)),
                    persistence_score=float(s.get("persistence_score", 0)),
                    capital_score=float(s.get("capital_score", 0)),
                    breadth_score=float(s.get("breadth_score", 0)),
                    leader_score=float(s.get("leader_score", 0)),
                    relative_score=float(s.get("relative_score", 0)),
                    stage=s.get("stage", "dormant"),
                    rank=int(s.get("rank", 0)),
                    is_filtered=bool(s.get("is_filtered", False)),
                    filter_reason=s.get("filter_reason"),
                    position_hint=s.get("position_hint", "observe"),
                    is_main_line=bool(s.get("is_main_line", False)),
                    main_line_tier=str(s.get("main_line_tier", "rotation") or "rotation"),
                    confirm_state=str(s.get("confirm_state", "pending") or "pending"),
                    exit_state=str(s.get("exit_state", "normal") or "normal"),
                    rules_json=s.get("rules_json") or [],
                    rule_fail_reasons=s.get("rule_fail_reasons") or [],
                    source_tag=str(s.get("source_tag", "auto") or "auto"),
                )
            )

        leader_map: dict[str, LoadedLeader] = {}
        for code, l in (raw.get("leaders") or {}).items():
            if not l:
                continue
            leader_map[code] = LoadedLeader(
                trade_date=_parse_date(l.get("trade_date")) or td,
                sector_code=l.get("sector_code", code),
                stock_code=l.get("stock_code", ""),
                stock_name=l.get("stock_name"),
                limit_up_streak=int(l.get("limit_up_streak", 0)),
                pct_change=float(l.get("pct_change", 0) or 0),
                money=float(l.get("money", 0) or 0),
            )

        sector_dailies = {}
        for code, d in (raw.get("sector_dailies") or {}).items():
            if isinstance(d, dict):
                sector_dailies[code] = d

        sector_flows = {}
        for code, f in (raw.get("sector_flows") or {}).items():
            if isinstance(f, dict):
                sector_flows[code] = f

        return LoadedLatestScan(
            trade_date=td,
            scan_start_date=_parse_date(raw.get("scan_start_date")),
            scan_end_date=_parse_date(raw.get("scan_end_date")),
            trade_days=trade_days or [td],
            market_env=env_row,
            scores=scores,
            leader_map=leader_map,
            saved_at=raw.get("saved_at"),
            sector_dailies=sector_dailies,
            sector_flows=sector_flows,
        )

    @staticmethod
    def clear() -> None:
        path = scan_latest_path()
        if path.is_file():
            path.unlink()
        logger.info("[latest_scan] 已删除 %s", path)

    @staticmethod
    def hydrate_dashboard_snapshot() -> None:
        """启动时将磁盘 latest 载入内存仪表盘快照。"""
        from app.services.storage_mode import uses_file_scan_storage
        from app.services.volatile_scan import (
            VolatileDashboardSnapshot,
            get_dashboard_snapshot,
            set_dashboard_snapshot,
        )

        if not uses_file_scan_storage():
            return
        if get_dashboard_snapshot() is not None:
            return
        loaded = LatestScanStore.load()
        if not loaded:
            return
        set_dashboard_snapshot(
            VolatileDashboardSnapshot(
                trade_date=loaded.trade_date,
                env=loaded.market_env,
                scores=loaded.scores,
                leader_map=loaded.leader_map,
                scan_trade_days=loaded.trade_days,
                sector_dailies=loaded.sector_dailies,
                sector_flows=loaded.sector_flows,
            )
        )
        logger.info("[latest_scan] 已从磁盘恢复仪表盘 trade_date=%s", loaded.trade_date)
