from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Alert, SectorDaily, SectorFlowDaily, SectorScoreDaily, ThemeLeaderDaily
from app.services.alert_service import AlertService
from app.services.risk import RiskModule
from app.services.theme_engine import ThemeEngine


class ScanService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.engine = ThemeEngine()
        self.risk = RiskModule()
        self.alerts = AlertService()

    async def run_scan(self, trade_date: date) -> list[SectorScoreDaily]:
        lookback_start = trade_date - timedelta(days=15)
        daily_all = (
            await self.session.execute(
                select(SectorDaily).where(
                    SectorDaily.trade_date >= lookback_start,
                    SectorDaily.trade_date <= trade_date,
                )
            )
        ).scalars().all()

        flow_all = (
            await self.session.execute(
                select(SectorFlowDaily).where(
                    SectorFlowDaily.trade_date >= lookback_start,
                    SectorFlowDaily.trade_date <= trade_date,
                )
            )
        ).scalars().all()

        leaders = (
            await self.session.execute(
                select(ThemeLeaderDaily).where(ThemeLeaderDaily.trade_date == trade_date)
            )
        ).scalars().all()
        leader_map = {l.sector_code: l for l in leaders}

        from app.models.tables import MarketEnvDaily

        env_row = await self.session.get(MarketEnvDaily, trade_date)
        index_pct = env_row.index_pct if env_row else 0.0

        sectors_today = {r.sector_code for r in daily_all if r.trade_date == trade_date}
        pct_sorted = sorted(
            [r.pct_change for r in daily_all if r.trade_date == trade_date],
            reverse=True,
        )

        yesterday = trade_date - timedelta(days=1)
        prev_scores_rows = (
            await self.session.execute(
                select(SectorScoreDaily).where(SectorScoreDaily.trade_date == yesterday)
            )
        ).scalars().all()
        from app.services.theme_engine import ScoreResult

        prev_score_map: dict[str, ScoreResult] = {}
        for r in prev_scores_rows:
            prev_score_map[r.sector_code] = ScoreResult(
                sector_code=r.sector_code,
                sector_name=r.sector_name,
                total_score=r.total_score,
                persistence_score=r.persistence_score,
                capital_score=r.capital_score,
                breadth_score=r.breadth_score,
                leader_score=r.leader_score,
                relative_score=r.relative_score,
                stage=r.stage,
                is_filtered=r.is_filtered,
                filter_reason=r.filter_reason,
                position_hint=r.position_hint,
            )

        results: list[ScoreResult] = []
        for code in sectors_today:
            d_rows = sorted(
                [r for r in daily_all if r.sector_code == code], key=lambda x: x.trade_date
            )
            f_rows = sorted(
                [r for r in flow_all if r.sector_code == code], key=lambda x: x.trade_date
            )
            if not d_rows:
                continue
            name = d_rows[-1].sector_name
            leader = leader_map.get(code)
            streak = leader.limit_up_streak if leader else 0
            pct5 = sum(r.pct_change for r in d_rows[-5:]) if d_rows else 0
            total_money = d_rows[-1].money or 1
            leader_share = (leader.money / total_money) if leader and total_money else 0

            metrics = self.engine.build_metrics_from_db(
                code, name, d_rows, f_rows, streak, pct5, leader_share, index_pct
            )
            try:
                rank_pct = pct_sorted.index(d_rows[-1].pct_change) / len(pct_sorted)
            except ValueError:
                rank_pct = 0.5
            prev_stage = prev_score_map.get(code).stage if code in prev_score_map else "dormant"
            sr = self.engine.score_sector(metrics, rank_pct, prev_stage)
            if env_row and not env_row.can_long:
                sr.position_hint = self.risk.adjust_position_hint(sr.position_hint, self.risk.env_from_model(env_row))
            results.append(sr)

        ranked = self.engine.rank_sectors(results)
        await self.session.execute(
            delete(SectorScoreDaily).where(SectorScoreDaily.trade_date == trade_date)
        )

        today_map = {r.sector_code: r for r in ranked}
        saved: list[SectorScoreDaily] = []
        for i, sr in enumerate(ranked):
            row = SectorScoreDaily(
                trade_date=trade_date,
                sector_code=sr.sector_code,
                sector_name=sr.sector_name,
                total_score=sr.total_score,
                persistence_score=sr.persistence_score,
                capital_score=sr.capital_score,
                breadth_score=sr.breadth_score,
                leader_score=sr.leader_score,
                relative_score=sr.relative_score,
                stage=sr.stage,
                rank=i + 1,
                is_filtered=sr.is_filtered,
                filter_reason=sr.filter_reason,
                position_hint=sr.position_hint,
            )
            self.session.add(row)
            saved.append(row)

        env_bad = False
        if env_row:
            prev_env = await self.session.get(MarketEnvDaily, yesterday)
            if prev_env and env_row.env_score < 40 and env_row.env_score < prev_env.env_score - 20:
                env_bad = True

        alert_items = self.alerts.diff_alerts(
            trade_date, today_map, prev_score_map, env_bad=env_bad
        )
        await self.session.execute(delete(Alert).where(Alert.trade_date == trade_date))
        for a in alert_items:
            self.session.add(Alert(**a))

        await self.session.flush()
        return saved
