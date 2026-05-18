"""入库概念筛选（仪表盘勾选 / 名称关键词 / 数量上限）。"""

import logging

from app.adapters.base import ConceptInfo
from app.config import settings
from app.services.ingest_settings_store import read_scan_sectors_selection

logger = logging.getLogger(__name__)


def select_concepts_for_ingest(
    concepts: list[ConceptInfo],
    max_concepts: int | None = None,
) -> list[ConceptInfo]:
    use_explicit, selected_codes = read_scan_sectors_selection()
    universe = len(concepts)

    if use_explicit:
        selected_set = set(selected_codes)
        if not selected_set:
            logger.warning("[流程] 已启用「仅扫描勾选板块」，但未勾选任何板块")
            return []
        concepts = [c for c in concepts if c.code in selected_set]
        logger.info(
            "[流程] 使用仪表盘勾选板块：%d / %d 个（勾选列表 %d 项）",
            len(concepts),
            universe,
            len(selected_codes),
        )
        missing = selected_set - {c.code for c in concepts}
        if missing:
            logger.warning(
                "[流程] 以下勾选代码不在概念列表中，已忽略: %s",
                sorted(missing)[:10],
            )
    elif settings.ingest_concept_filter.strip():
        key = settings.ingest_concept_filter.strip().upper()
        matched = [c for c in concepts if key in c.name.upper()]
        logger.info(
            "[流程] 使用环境关键词 %r 筛选：%d / %d 个板块",
            settings.ingest_concept_filter,
            len(matched),
            universe,
        )
        concepts = matched

    if max_concepts is None:
        max_concepts = settings.ingest_max_concepts
    if max_concepts > 0 and not use_explicit:
        concepts = concepts[:max_concepts]
        logger.info("[流程] 环境上限 ingest_max_concepts=%d，保留前 %d 个", max_concepts, len(concepts))
    return concepts


def resolve_scan_scope_label() -> str:
    """仪表盘数据源条展示的扫描范围文案。"""
    use_explicit, codes = read_scan_sectors_selection()
    if use_explicit:
        if codes:
            return f"已勾选 {len(codes)} 个板块"
        return "勾选模式（未选板块）"
    key = settings.ingest_concept_filter.strip()
    if key:
        return f"关键词「{key}」"
    if settings.ingest_max_concepts > 0:
        return f"列表前 {settings.ingest_max_concepts} 个概念"
    return "全部概念"
