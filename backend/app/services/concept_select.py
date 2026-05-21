"""入库概念筛选（仪表盘勾选 / 名称关键词 / 数量上限）。"""

import logging

from app.adapters.base import ConceptInfo
from app.services.ingest_settings_store import read_scan_sectors_selection

logger = logging.getLogger(__name__)


def select_concepts_for_backtest(
    concepts: list[ConceptInfo],
    sector_codes: list[str],
) -> list[ConceptInfo]:
    if not sector_codes:
        return []
    selected_set = set(sector_codes)
    matched = [c for c in concepts if c.code in selected_set]
    logger.info(
        "[流程] 回测板块池：%d / %d 个（勾选 %d 项）",
        len(matched),
        len(concepts),
        len(sector_codes),
    )
    return matched


def select_concepts_for_ingest(
    concepts: list[ConceptInfo],
    max_concepts: int | None = None,
) -> list[ConceptInfo]:
    from app.services.backtest_context import get_backtest_sector_codes

    bt_codes = get_backtest_sector_codes()
    if bt_codes is not None:
        return select_concepts_for_backtest(concepts, bt_codes)

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
    # 扫盘范围以用户输入为准：
    # - 用户勾选开启时：只扫勾选项
    # - 未开启勾选时：默认全量概念（不再使用 INGEST_CONCEPT_FILTER/INGEST_MAX_CONCEPTS）
    if max_concepts is not None and max_concepts > 0 and not use_explicit:
        concepts = concepts[:max_concepts]
        logger.info("[流程] 临时上限 max_concepts=%d，保留前 %d 个", max_concepts, len(concepts))
    return concepts


def resolve_scan_scope_label() -> str:
    """仪表盘数据源条展示的扫描范围文案。"""
    use_explicit, codes = read_scan_sectors_selection()
    if use_explicit:
        if codes:
            return f"已勾选 {len(codes)} 个板块"
        return "勾选模式（未选板块）"
    return "全部概念（未启用仅勾选）"
