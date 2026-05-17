"""概念板块全集缓存，避免每次 HTTP 请求调用聚宽。"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.adapters.base import ConceptInfo

logger = logging.getLogger(__name__)

_CACHE_TTL_SEC = 3600 * 6  # 6 小时


@dataclass
class _CacheEntry:
    concepts: list[ConceptInfo]
    loaded_at: float
    source: str


_lock = threading.Lock()
_entry: Optional[_CacheEntry] = None


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
            from app.config import settings

            if settings.jq_configured():
                from app.adapters.factory import get_adapter

                adapter = get_adapter()
                if adapter.__class__.__name__ != "JQDataAdapter":
                    logger.warning("Skip concept cache warm: not on JQData yet")
                    return
            get_cached_concepts(force_refresh=True)
        except Exception as exc:
            logger.warning("Concept cache warm-up failed: %s", exc)

    threading.Thread(target=_run, daemon=True).start()
