"""扫盘与行情持久化模式（文件 / 内存）。

扫盘数据始终走内存缓冲 + 文件快照，不再写入 PostgreSQL 扫盘表。
"""

from __future__ import annotations

from app.config import settings


def uses_file_scan_storage() -> bool:
    """全市场行情 JSON + latest.json 落盘。"""
    return bool(settings.market_cache_enabled)


def uses_scan_memory_buffer() -> bool:
    """扫盘中间态仅存进程内存（不写 PG 扫盘表）。"""
    return True


def persist_scan_to_postgres() -> bool:
    """是否将扫盘结果写入 PostgreSQL（已禁用）。"""
    return False
