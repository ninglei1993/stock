from __future__ import annotations

from app.services.scoring.a_strategy_rules import (
    evaluate_confirm_exit_signals,
    evaluate_main_line_rules,
)
from app.services.scoring.base import ScoreDimensionDef
from app.services.theme_engine import ScoreResult, SectorMetrics, ThemeEngine


class AStrategyScoringAdapter(ThemeEngine):
    mode = "a_strategy"

    def score_sector(
        self,
        metrics: SectorMetrics,
        rank_pct: float,
        prev_stage: str = "dormant",
    ) -> ScoreResult:
        del rank_pct
        del prev_stage
        rules = evaluate_main_line_rules(metrics)
        passed = [r for r in rules if r.passed]
        failed = [r for r in rules if not r.passed]
        pass_count = len(passed)
        is_main_line = pass_count == len(rules)
        tier = "rotation"
        for r in rules:
            if r.key == "pct_20d_tier":
                tier = str((r.current or {}).get("tier", "rotation"))
                break

        # A 策略为“硬性规则通过/不通过”，不是打分制。
        # total_score 仅用于排序/持久化，不作为 UI 分数展示。
        total = float(round(pass_count / max(len(rules), 1) * 100.0, 2))

        confirm_state, exit_state = evaluate_confirm_exit_signals(metrics, rules)
        if exit_state == "exit":
            stage = "decay"
        elif is_main_line:
            stage = "ferment" if tier == "secondary" else "climax"
        elif pass_count >= 4:
            stage = "sprout"
        else:
            stage = "dormant"
        hint = "exit" if exit_state == "exit" else ("hold" if is_main_line else "observe")

        source_tag = "manual" if any(r.source == "manual" for r in rules) else "auto"
        reason = "；".join(r.label for r in failed) if failed else None

        return ScoreResult(
            sector_code=metrics.sector_code,
            sector_name=metrics.sector_name,
            total_score=total,
            persistence_score=0.0,
            capital_score=0.0,
            breadth_score=0.0,
            leader_score=0.0,
            relative_score=0.0,
            stage=stage,
            is_filtered=not is_main_line,
            filter_reason=reason,
            position_hint=hint,
            is_main_line=is_main_line,
            main_line_tier=tier,
            confirm_state=confirm_state,
            exit_state=exit_state,
            rules=[r.as_dict() for r in rules],
            rule_fail_reasons=[r.label for r in failed],
            source_tag=source_tag,
        )

    def dimension_defs(self) -> list[ScoreDimensionDef]:
        return []

    def rank_sectors(
        self, scores: list[ScoreResult], *, keep_all: bool = False
    ) -> list[ScoreResult]:
        tier_order = {"top": 0, "secondary": 1, "rotation": 2}
        active = list(scores) if keep_all else [s for s in scores if s.is_main_line]
        active.sort(
            key=lambda s: (
                0 if s.is_main_line else 1,
                tier_order.get(s.main_line_tier, 9),
                -float(getattr(s, "persistence_score", 0.0) or 0.0),
                -float(getattr(s, "capital_score", 0.0) or 0.0),
                s.sector_code,
            )
        )
        return active
