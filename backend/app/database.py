from collections.abc import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

sync_engine = create_engine(settings.database_url_sync, echo=False)
SyncSessionLocal = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    from sqlalchemy import text

    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 升级旧库：同股可属多概念，唯一键改为 (trade_date, stock_code, sector_code)
        await conn.execute(
            text("ALTER TABLE stock_daily DROP CONSTRAINT IF EXISTS uq_stock_daily")
        )
        await conn.execute(
            text(
                """
                DO $$ BEGIN
                  ALTER TABLE stock_daily ADD CONSTRAINT uq_stock_daily
                    UNIQUE (trade_date, stock_code, sector_code);
                EXCEPTION
                  WHEN duplicate_table THEN NULL;
                  WHEN duplicate_object THEN NULL;
                END $$;
                """
            )
        )
        for col, col_type in [
            ("signal_date", "DATE"),
            ("sell_stock_code", "VARCHAR(32)"),
            ("holding_days", "INTEGER"),
            ("trade_mode", "VARCHAR(32) DEFAULT '板块龙头个股'"),
        ]:
            await conn.execute(
                text(
                    f"ALTER TABLE backtest_trades ADD COLUMN IF NOT EXISTS {col} {col_type}"
                )
            )
