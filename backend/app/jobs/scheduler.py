import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def daily_scan_job() -> None:
    from app.services.ingestion import IngestionService
    from app.services.scan_service import ScanService

    trade_date = datetime.now().date()
    logger.info("Starting daily scan for %s", trade_date)
    async with AsyncSessionLocal() as session:
        try:
            ingestion = IngestionService(session)
            await ingestion.ingest_day(trade_date)
            scanner = ScanService(session)
            await scanner.run_scan(trade_date)
            await session.commit()
            logger.info("Daily scan completed for %s", trade_date)
        except Exception:
            logger.exception("Daily scan failed")
            await session.rollback()


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
