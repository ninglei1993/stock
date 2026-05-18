"""用户选择的数据源（首页切换），持久化到项目根目录。"""

import json
import logging
from pathlib import Path
from typing import Literal, Optional

from app.config import _PROJECT_ROOT

logger = logging.getLogger(__name__)

DataSourceId = Literal["auto", "jqdata", "tushare"]
VALID_SOURCES = frozenset({"auto", "jqdata", "tushare"})

_OVERRIDE_FILE = _PROJECT_ROOT / "data_source.override.json"


def read_override() -> Optional[DataSourceId]:
    if not _OVERRIDE_FILE.exists():
        return None
    try:
        raw = json.loads(_OVERRIDE_FILE.read_text(encoding="utf-8"))
        src = str(raw.get("source", "")).lower().strip()
        if src == "demo":
            return None
        if src in VALID_SOURCES:
            return src  # type: ignore[return-value]
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("Invalid data_source.override.json: %s", exc)
    return None


def write_override(source: DataSourceId) -> None:
    if source not in VALID_SOURCES:
        raise ValueError(f"Invalid data source: {source}")
    _OVERRIDE_FILE.write_text(
        json.dumps({"source": source}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clear_override() -> None:
    if _OVERRIDE_FILE.exists():
        _OVERRIDE_FILE.unlink()
