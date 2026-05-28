import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import settings
from app.jobs.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").disabled = True
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logging.getLogger("app.adapters.tushare_adapter").setLevel(logging.ERROR)
logging.getLogger("app.services.ingestion").setLevel(logging.WARNING)
logging.getLogger("app.services.market_cache").setLevel(logging.WARNING)
logging.getLogger("app.utils.timing_log").setLevel(logging.WARNING)
logging.getLogger("app.services.volatile_scan").setLevel(logging.WARNING)
logging.getLogger("app.services.volatile_merge").setLevel(logging.WARNING)
logging.getLogger("app.services.concept_cache").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.adapters.factory import reset_adapter
    from app.services.concept_cache import clear_concept_cache, warm_cache_background

    logger.info(
        "Config loaded | tushare_configured=%s | market_cache_enabled=%s",
        settings.tushare_configured(),
        settings.market_cache_enabled,
    )

    reset_adapter()
    clear_concept_cache()
    logger.info("Startup skip sync Tushare probe; adapter will initialize on first request.")

    warm_cache_background()
    from app.services.latest_scan_store import LatestScanStore

    LatestScanStore.hydrate_dashboard_snapshot()
    logger.info("Application initialized")
    start_scheduler()
    yield


app = FastAPI(
    title="ThemeRadar API",
    description="主线预警系统 — 盘面先热，消息后吹",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
