from dataclasses import dataclass

from app.models.tables import MarketEnvDaily


@dataclass
class EnvResult:
    env_score: float
    limit_up_count: int
    up_down_ratio: float
    index_pct: float
    conclusion: str
    can_long: bool


class RiskModule:
    def compute_env(
        self,
        limit_up_count: int,
        up_down_ratio: float,
        index_pct: float,
    ) -> EnvResult:
        score = 50.0
        score += min(25, limit_up_count * 0.5)
        score += (up_down_ratio - 0.5) * 40
        score += index_pct * 3
        score = max(0, min(100, score))

        if limit_up_count < 20 or up_down_ratio < 0.4:
            score = min(score, 45)

        if score >= 60:
            conclusion = "can_long"
            can_long = True
        elif score >= 40:
            conclusion = "caution"
            can_long = True
        else:
            conclusion = "observe"
            can_long = False

        return EnvResult(
            env_score=round(score, 2),
            limit_up_count=limit_up_count,
            up_down_ratio=round(up_down_ratio, 4),
            index_pct=round(index_pct, 2),
            conclusion=conclusion,
            can_long=can_long,
        )

    def adjust_position_hint(self, hint: str, env: EnvResult) -> str:
        if not env.can_long and hint in ("light_position", "hold"):
            return "observe"
        if env.env_score < 60 and hint == "light_position":
            return "observe"
        return hint

    def env_from_model(self, row: MarketEnvDaily) -> EnvResult:
        return EnvResult(
            env_score=row.env_score,
            limit_up_count=row.limit_up_count,
            up_down_ratio=row.up_down_ratio,
            index_pct=row.index_pct,
            conclusion=row.conclusion,
            can_long=row.can_long,
        )
