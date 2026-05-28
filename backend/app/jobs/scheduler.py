import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def daily_scan_job() -> None:
    from app.services.ingestion import IngestionService
    from app.services.latest_scan_store import LatestScanStore
    from app.services.scan_service import ScanService
    from app.services.storage_mode import uses_file_scan_storage
    from app.services.trade_calendar import resolve_scan_date

    trade_date = resolve_scan_date()
    logger.info("Starting daily scan for %s", trade_date)
    try:
        ingestion = IngestionService()
        await ingestion.ingest_day(trade_date)
        scanner = ScanService()
        scores = await scanner.run_scan(trade_date)

        from app.services.volatile_scan import (
            VolatileDashboardSnapshot,
            get_today_buffer,
            set_dashboard_snapshot,
        )

        buf = get_today_buffer()
        lm = dict(buf.leaders_by_code) if buf else {}
        snap = VolatileDashboardSnapshot(
            trade_date=trade_date,
            env=(buf.market_env if buf else None),
            scores=list(scores),
            leader_map=lm,
            scan_trade_days=[trade_date],
        )
        set_dashboard_snapshot(snap)
        if uses_file_scan_storage():
            LatestScanStore.save(
                trade_date=trade_date,
                scores=list(scores),
                market_env=snap.env,
                leader_map=lm,
                scan_trade_days=[trade_date],
            )
        logger.info("Daily scan completed for %s", trade_date)
    except Exception:
        logger.exception("Daily scan failed")


def start_scheduler() -> None:
    scheduler.add_job(
        daily_scan_job,
        "cron",
        hour=settings.scan_hour,
        minute=settings.scan_minute,
        id="daily_scan",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started: scan at %02d:%02d", settings.scan_hour, settings.scan_minute)
