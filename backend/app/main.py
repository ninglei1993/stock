import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.adapters.factory import adapter_info
from app.config import settings
from app.database import init_db
from app.jobs.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    from app.adapters.factory import get_adapter, reset_adapter
    from app.services.concept_cache import clear_concept_cache, warm_cache_background

    masked_user = (
        f"{settings.jqdata_username[:3]}***" if settings.jqdata_username else "(empty)"
    )
    logger.info(
        "Config loaded | jq_configured=%s | user=%s | demo_mode=%s | use_demo=%s",
        settings.jq_configured(),
        masked_user,
        settings.demo_mode,
        settings.use_demo_data(),
    )

    reset_adapter()
    clear_concept_cache()
    try:
        get_adapter()
    except RuntimeError as exc:
        logger.error("Startup adapter failed: %s", exc)

    warm_cache_background()
    info = adapter_info()
    logger.info(
        "Database initialized | data_source=%s | concepts=%s | jq_configured=%s",
        info.get("adapter"),
        info.get("universe_total"),
        info.get("jq_configured"),
    )
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
