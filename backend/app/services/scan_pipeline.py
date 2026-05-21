"""收盘扫描流程说明、分步耗时统计（日志）。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# 扫描开始前打印的整体步骤（通俗说明）
SCAN_PLAN_LINES: list[tuple[str, str]] = [
    ("1", "拉取同花顺概念板块列表，并按仪表盘勾选/关键词筛选要扫描的板块"),
    ("2", "获取沪深300指数近几日走势，用于计算大盘环境得分"),
    (
        "3",
        "获取全市场约5000只股票的当日涨跌家数、涨停家数（复用已缓存的日线，不再重复请求）",
    ),
    (
        "4",
        "【预取·全市场公有数据】按交易日批量拉取：全市场日线、涨跌停价、主力资金流"
        "（各日只请求一次，后续各概念板块共用，避免重复调接口）",
    ),
    ("5", "按板块逐个处理：拉该概念成分股列表（每板块一次 ths_member）"),
    ("6", "可选：按成交额/涨停优先只保留 Top N 只成分股"),
    ("7", "从已缓存的全市场资金流表中，筛出本板块成分股的多日主力净流入"),
    ("8", "从已缓存的全市场日线+涨跌停表中，计算成分股多日行情与连板"),
    ("9", "聚合板块涨幅/涨停数/资金等，写入数据库或内存快照"),
    ("10", "A策略主线规则评估、预警对比（主要读库+内存，不再调行情接口）"),
]


@dataclass
class PhaseRecord:
    key: str
    title: str
    plain: str
    elapsed: float = 0.0
    extra: str = ""


@dataclass
class ScanPipelineTracker:
    """一次扫描任务的流程与耗时。"""

    trade_date: str
    adapter: str
    concept_count: int = 0
    _phases: list[PhaseRecord] = field(default_factory=list)
    _t0: float = field(default_factory=time.monotonic)
    _market_env_logged: bool = False
    _prefetch_logged: bool = False

    def log_plan(self) -> None:
        logger.info(
            "[流程] 收盘扫描开始 交易日=%s 数据源=%s 板块数=%s",
            self.trade_date,
            self.adapter,
            self.concept_count or "待计算",
        )
        if logger.isEnabledFor(logging.DEBUG):
            for num, desc in SCAN_PLAN_LINES:
                logger.debug("[流程]   步骤%s：%s", num, desc)

    def start_phase(self, key: str, title: str, plain: str) -> float:
        logger.debug("[流程] ▶ 开始【%s】— %s", title, plain)
        return time.monotonic()

    def end_phase(
        self,
        key: str,
        title: str,
        plain: str,
        started: float,
        extra: str = "",
        *,
        log_level: int = logging.INFO,
    ) -> None:
        elapsed = time.monotonic() - started
        suffix = f" ({extra})" if extra else ""
        if key == "market_env" and self._market_env_logged:
            log_level = logging.DEBUG
        elif key == "prefetch" and self._prefetch_logged:
            log_level = logging.DEBUG
        if key == "market_env":
            self._market_env_logged = True
        elif key == "prefetch":
            self._prefetch_logged = True
        logger.log(
            log_level,
            "[流程] ✓ 完成【%s】耗时=%.2fs — %s%s",
            title,
            elapsed,
            plain,
            suffix,
        )
        self._phases.append(
            PhaseRecord(key=key, title=title, plain=plain, elapsed=elapsed, extra=extra)
        )

    def record_phase(
        self, key: str, title: str, plain: str, elapsed: float, extra: str = ""
    ) -> None:
        suffix = f" ({extra})" if extra else ""
        logger.info(
            "[流程] ✓ 完成【%s】耗时=%.2fs — %s%s",
            title,
            elapsed,
            plain,
            suffix,
        )
        self._phases.append(
            PhaseRecord(key=key, title=title, plain=plain, elapsed=elapsed, extra=extra)
        )

    def log_summary(self) -> None:
        total = time.monotonic() - self._t0
        logger.info("[流程] ========== 扫描阶段耗时汇总（交易日=%s）==========", self.trade_date)
        if not self._phases:
            logger.info("[流程] （无分步记录）总耗时=%.2fs", total)
            return
        sorted_phases = sorted(self._phases, key=lambda p: p.elapsed, reverse=True)
        for i, p in enumerate(sorted_phases, 1):
            pct = (p.elapsed / total * 100) if total > 0 else 0
            logger.info(
                "[流程]   排名%d  %.2fs (%4.1f%%)  【%s】%s",
                i,
                p.elapsed,
                pct,
                p.title,
                f" — {p.plain}" if p.plain else "",
            )
        slowest = sorted_phases[0]
        logger.info(
            "[流程] ★ 当前耗时最高：【%s】%.2fs — %s",
            slowest.title,
            slowest.elapsed,
            slowest.plain,
        )
        logger.info("[流程] 扫描相关阶段合计=%.2fs", sum(p.elapsed for p in self._phases))
        logger.info("[流程] 任务总耗时（含未单独计时的间隙）=%.2fs", total)
        logger.info("[流程] ========================================")


_tracker: Optional[ScanPipelineTracker] = None


def set_tracker(tracker: Optional[ScanPipelineTracker]) -> None:
    global _tracker
    _tracker = tracker


def get_tracker() -> Optional[ScanPipelineTracker]:
    return _tracker
