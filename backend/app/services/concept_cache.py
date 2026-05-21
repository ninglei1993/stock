"""概念板块全集缓存，避免每次 HTTP 请求调用聚宽。"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from pathlib import Path

from app.adapters.base import ConceptInfo
from app.config import settings

logger = logging.getLogger(__name__)

_CACHE_TTL_SEC = 3600 * 6  # 6 小时
_DISK_CACHE_FILE = Path(settings.data_dir) / "concepts_universe.json"


@dataclass
class _CacheEntry:
    concepts: list[ConceptInfo]
    loaded_at: float
    source: str


_lock = threading.Lock()
_entry: Optional[_CacheEntry] = None


def _load_concepts_from_disk() -> list[ConceptInfo]:
    path = _DISK_CACHE_FILE
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("Concept disk cache read failed: %s", exc)
        return []
    if not isinstance(raw, dict):
        return []
    rows = raw.get("concepts")
    if not isinstance(rows, list):
        return []
    concepts: list[ConceptInfo] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code", "")).strip()
        name = str(item.get("name", code)).strip()
        if code:
            concepts.append(ConceptInfo(code=code, name=name or code))
    return concepts


def _save_concepts_to_disk(concepts: list[ConceptInfo], *, source: str) -> None:
    if not concepts:
        return
    payload = {
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "source": source,
        "count": len(concepts),
        "concepts": [{"code": c.code, "name": c.name} for c in concepts],
    }
    try:
        _DISK_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DISK_CACHE_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("Concept disk cache write failed: %s", exc)


def get_cached_concepts(force_refresh: bool = False) -> tuple[list[ConceptInfo], str]:
    global _entry
    now = time.time()
    with _lock:
        if (
            not force_refresh
            and _entry is not None
            and now - _entry.loaded_at < _CACHE_TTL_SEC
        ):
            return _entry.concepts, _entry.source

    from app.adapters.factory import get_adapter

    adapter = get_adapter()
    source = adapter.__class__.__name__
    logger.info("Loading concept universe from %s ...", source)
    concepts = adapter.list_concepts()
    if not concepts:
        disk = _load_concepts_from_disk()
        if disk:
            logger.warning(
                "Concept universe empty from %s; fallback to disk cache count=%d (%s)",
                source,
                len(disk),
                _DISK_CACHE_FILE,
            )
            concepts = disk
            source = "disk_cache"
        else:
            logger.warning("Concept universe empty from %s and no disk cache found", source)
    else:
        _save_concepts_to_disk(concepts, source=source)
    with _lock:
        _entry = _CacheEntry(concepts=concepts, loaded_at=now, source=source)
    logger.info("Concept universe cached: %d from %s", len(concepts), source)
    return concepts, source


def cache_meta() -> dict:
    with _lock:
        if _entry is None:
            return {"cached": False, "count": 0, "source": None}
        return {
            "cached": True,
            "count": len(_entry.concepts),
            "source": _entry.source,
            "loaded_at": datetime.utcfromtimestamp(_entry.loaded_at).isoformat() + "Z",
        }


def clear_concept_cache() -> None:
    global _entry
    with _lock:
        _entry = None


def warm_cache_background() -> None:
    def _run() -> None:
        try:
            get_cached_concepts(force_refresh=True)
        except Exception as exc:
            logger.warning("Concept cache warm-up failed: %s", exc)

    threading.Thread(target=_run, daemon=True).start()
