"""全市场日线 / 涨跌停价 / 主力资金流按交易日 JSON 缓存。"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from app.config import settings

logger = logging.getLogger(__name__)

MANIFEST_VERSION = 1


class MarketTable(str, Enum):
    DAILY = "daily"
    LIMIT = "limit"
    MONEYFLOW = "moneyflow"


_ALL_TABLES = (MarketTable.DAILY, MarketTable.LIMIT, MarketTable.MONEYFLOW)


def _fmt(d: date) -> str:
    return d.strftime("%Y%m%d")


def _parse_day(key: str) -> date:
    return date(int(key[:4]), int(key[4:6]), int(key[6:8]))


def market_root() -> Path:
    return Path(settings.data_dir) / "market"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _row_to_jsonable(row: pd.Series) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if pd.isna(v):
            continue
        if hasattr(v, "item"):
            v = v.item()
        out[str(k)] = v
    return out


def dataframe_to_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    return [_row_to_jsonable(row) for _, row in df.iterrows()]


def rows_to_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


class MarketCacheStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or market_root()

    def _path(self, table: MarketTable, trade_date: date) -> Path:
        return self.root / table.value / f"{_fmt(trade_date)}.json"

    def has_day(self, trade_date: date) -> bool:
        return all(self._path(t, trade_date).is_file() for t in _ALL_TABLES)

    def has_table(self, table: MarketTable, trade_date: date) -> bool:
        return self._path(table, trade_date).is_file()

    def load(self, table: MarketTable, trade_date: date) -> Optional[pd.DataFrame]:
        path = self._path(table, trade_date)
        if not path.is_file():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
            rows = payload.get("rows") or []
            return rows_to_dataframe(rows)
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("[market_cache] 读取失败 %s: %s", path, exc)
            return None

    def save(self, table: MarketTable, trade_date: date, df: pd.DataFrame) -> None:
        payload = {
            "version": 1,
            "trade_date": trade_date.isoformat(),
            "rows": dataframe_to_rows(df),
        }
        _atomic_write_json(self._path(table, trade_date), payload)

    def save_day(self, trade_date: date, daily: pd.DataFrame, limit: pd.DataFrame, moneyflow: pd.DataFrame) -> None:
        self.save(MarketTable.DAILY, trade_date, daily)
        self.save(MarketTable.LIMIT, trade_date, limit)
        self.save(MarketTable.MONEYFLOW, trade_date, moneyflow)
        self._register_day(trade_date)

    def list_trade_days(self) -> list[date]:
        manifest = self._read_manifest()
        days: list[date] = []
        for s in manifest.get("trade_days") or []:
            try:
                days.append(date.fromisoformat(s))
            except ValueError:
                continue
        return sorted(days)

    def _read_manifest(self) -> dict[str, Any]:
        path = self.root / "manifest.json"
        if not path.is_file():
            return {"version": MANIFEST_VERSION, "trade_days": []}
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[market_cache] manifest 损坏: %s", exc)
            return {"version": MANIFEST_VERSION, "trade_days": []}

    def _register_day(self, trade_date: date) -> None:
        manifest = self._read_manifest()
        iso = trade_date.isoformat()
        days = list(manifest.get("trade_days") or [])
        if iso not in days:
            days.append(iso)
        days.sort()
        manifest["version"] = MANIFEST_VERSION
        manifest["trade_days"] = days
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_write_json(self.root / "manifest.json", manifest)

    def clear_all(self) -> None:
        import shutil

        if self.root.is_dir():
            shutil.rmtree(self.root)
        logger.info("[market_cache] 已清空 %s", self.root)

    def ensure_days(
        self,
        adapter: Any,
        trade_days: list[date],
        *,
        force_refresh: bool = False,
    ) -> dict[str, int]:
        """
        确保交易日三表均在磁盘与 adapter 内存缓存中。
        返回 skipped / fetched / api_calls 统计。
        """
        from app.adapters.tushare_adapter import TushareAdapter

        if not settings.market_cache_enabled:
            return {"skipped": 0, "fetched": 0, "api_calls": 0}

        skipped = 0
        fetched = 0
        api_calls = 0
        store = self

        for td in trade_days:
            key = _fmt(td)
            if not force_refresh and store.has_day(td):
                need_refetch = False
                for table, cache in (
                    (MarketTable.DAILY, TushareAdapter._daily_cache),
                    (MarketTable.LIMIT, TushareAdapter._limit_cache),
                    (MarketTable.MONEYFLOW, TushareAdapter._moneyflow_cache),
                ):
                    if key not in cache:
                        df = store.load(table, td)
                        if df is not None and not df.empty:
                            cache[key] = df
                        elif table == MarketTable.DAILY:
                            # daily 为空时，后续板块成分行情会全空；不能当作有效缓存。
                            need_refetch = True
                            logger.warning(
                                "[market_cache] %s daily 缓存为空，改为实时重拉",
                                key,
                            )
                    elif table == MarketTable.DAILY and cache[key].empty:
                        need_refetch = True
                        logger.warning(
                            "[market_cache] %s daily 内存缓存为空，改为实时重拉",
                            key,
                        )
                if not need_refetch:
                    logger.info("[数据] %s 三张表=daily/limit/moneyflow 均已命中缓存", key)
                    skipped += 1
                    continue

            before = (
                key not in TushareAdapter._daily_cache,
                key not in TushareAdapter._limit_cache,
                key not in TushareAdapter._moneyflow_cache,
            )
            daily_df = adapter._daily_market(td)
            limit_df = adapter._limit_table(td)
            money_df = adapter._moneyflow_market(td)
            logger.info(
                "[数据] %s 三张表已加载 daily=%d limit=%d moneyflow=%d%s",
                key,
                len(daily_df),
                len(limit_df),
                len(money_df),
                "（含API拉取）" if any(before) else "（内存/磁盘）",
            )
            fetched += 1
            if any(before):
                api_calls += sum(before)

        logger.info(
            "[market_cache] ensure_days 共 %d 日 跳过 %d 新拉 %d API约 %d 次",
            len(trade_days),
            skipped,
            fetched,
            api_calls,
        )
        return {"skipped": skipped, "fetched": fetched, "api_calls": api_calls, "total": len(trade_days)}


_store: MarketCacheStore | None = None


def get_market_cache() -> MarketCacheStore:
    global _store
    if _store is None:
        _store = MarketCacheStore()
    return _store
