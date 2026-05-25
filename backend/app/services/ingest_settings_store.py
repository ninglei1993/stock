"""扫描入库参数（仪表盘可覆盖），持久化到项目根目录。"""

import json
import logging
from pathlib import Path
from typing import Optional

from app.config import _PROJECT_ROOT, settings

logger = logging.getLogger(__name__)

_OVERRIDE_FILE = _PROJECT_ROOT / "ingest_settings.override.json"


def read_max_stocks_override() -> Optional[int]:
    if not _OVERRIDE_FILE.exists():
        return None
    try:
        raw = json.loads(_OVERRIDE_FILE.read_text(encoding="utf-8"))
        if "max_stocks_per_concept" not in raw:
            return None
        return max(0, int(raw["max_stocks_per_concept"]))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("Invalid ingest_settings.override.json: %s", exc)
    return None


def write_max_stocks_override(max_stocks: int) -> None:
    if max_stocks < 0:
        raise ValueError("max_stocks_per_concept must be >= 0")
    data: dict = {}
    if _OVERRIDE_FILE.exists():
        try:
            data = json.loads(_OVERRIDE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    data["max_stocks_per_concept"] = max_stocks
    _OVERRIDE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def effective_max_stocks_per_concept() -> int:
    """0 表示不限制，分析概念板块全部成分股。"""
    override = read_max_stocks_override()
    if override is not None:
        return override
    # 默认始终走“全成分股”；只有用户显式在仪表盘设置后才按覆盖值限制。
    return 0


def _read_override_blob() -> dict:
    if not _OVERRIDE_FILE.exists():
        return {}
    try:
        raw = json.loads(_OVERRIDE_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Invalid ingest_settings.override.json: %s", exc)
        return {}


def _write_override_blob(data: dict) -> None:
    _OVERRIDE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_scan_sectors_selection() -> tuple[bool, list[str]]:
    """返回 (是否使用仪表盘勾选, 已选板块代码列表)。"""
    raw = _read_override_blob()
    use_explicit = bool(raw.get("use_explicit_sector_selection", False))
    codes = raw.get("selected_sector_codes")
    if not isinstance(codes, list):
        return use_explicit, []
    selected = [str(c).strip() for c in codes if str(c).strip()]
    return use_explicit, selected


def write_scan_sectors_selection(
    *,
    use_explicit_selection: bool,
    selected_codes: list[str],
) -> None:
    data = _read_override_blob()
    data["use_explicit_sector_selection"] = use_explicit_selection
    data["selected_sector_codes"] = [str(c).strip() for c in selected_codes if str(c).strip()]
    _write_override_blob(data)


def read_scan_history() -> list[dict]:
    """读取历史勾选记录列表，每条记录包含 label, codes, saved_at。"""
    raw = _read_override_blob()
    history = raw.get("scan_history")
    if not isinstance(history, list):
        return []
    return [h for h in history if isinstance(h, dict)]


def append_scan_history(label: str, codes: list[str]) -> None:
    """追加一条勾选历史（最多保留10条）。"""
    from datetime import datetime, timezone

    data = _read_override_blob()
    history = data.get("scan_history")
    if not isinstance(history, list):
        history = []
    entry = {
        "label": label,
        "codes": [str(c).strip() for c in codes if str(c).strip()],
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    history.append(entry)
    if len(history) > 10:
        history = history[-10:]
    data["scan_history"] = history
    _write_override_blob(data)
