from datetime import date
from typing import Optional

from app.models.tables import SectorScoreDaily
from app.services.theme_engine import ScoreResult


ALERT_NAMES = {
    "NEW_SPROUT": "新晋萌芽",
    "STAGE_UP": "阶段升级",
    "STRENGTH_SURGE": "强度跃升",
    "EXIT_CLIMAX": "高潮撤退",
    "EXIT_DECAY": "衰退清仓",
    "ENV_BAD": "环境恶化",
}


class AlertService:
    def diff_alerts(
        self,
        trade_date: date,
        today_scores: dict[str, ScoreResult],
        yesterday_scores: dict[str, ScoreResult],
        env_bad: bool = False,
    ) -> list[dict]:
        alerts: list[dict] = []

        if env_bad:
            alerts.append(
                {
                    "trade_date": trade_date,
                    "sector_code": "MARKET",
                    "sector_name": "大盘环境",
                    "alert_code": "ENV_BAD",
                    "human_reason": "大盘环境分恶化，系统禁多，仅观察",
                }
            )

        for code, today in today_scores.items():
            prev = yesterday_scores.get(code)
            prev_stage = prev.stage if prev else "dormant"
            prev_score = prev.total_score if prev else 0

            if today.stage == "sprout" and prev_stage in ("dormant",) and today.total_score >= 55:
                alerts.append(self._make(trade_date, today, "NEW_SPROUT", prev_stage))

            if today.stage == "ferment" and prev_stage == "sprout":
                alerts.append(self._make(trade_date, today, "STAGE_UP", prev_stage))

            if today.total_score - prev_score >= 15 and today.total_score >= 55:
                if not any(a["sector_code"] == code and a["alert_code"] == "STRENGTH_SURGE" for a in alerts):
                    alerts.append(self._make(trade_date, today, "STRENGTH_SURGE", prev_stage))

            if today.stage == "climax" and prev_stage in ("ferment", "sprout"):
                alerts.append(self._make(trade_date, today, "EXIT_CLIMAX", prev_stage))

            if today.stage == "decay" and prev_stage in ("climax", "ferment", "sprout"):
                alerts.append(self._make(trade_date, today, "EXIT_DECAY", prev_stage))

        return alerts

    def _make(
        self, trade_date: date, score: ScoreResult, code: str, prev_stage: str
    ) -> dict:
        reason = (
            f"{score.sector_name}：强度{score.total_score:.0f}分，"
            f"阶段{prev_stage}→{score.stage}，"
            f"资金分{score.capital_score:.0f}广度分{score.breadth_score:.0f} → "
            f"{ALERT_NAMES.get(code, code)}"
        )
        return {
            "trade_date": trade_date,
            "sector_code": score.sector_code,
            "sector_name": score.sector_name,
            "alert_code": code,
            "human_reason": reason,
        }
