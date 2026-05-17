from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://themeradar:themeradar@localhost:5432/themeradar"
    database_url_sync: str = "postgresql://themeradar:themeradar@localhost:5432/themeradar"
    redis_url: str = "redis://localhost:6379/0"
    jqdata_username: str = "15120092232"
    jqdata_password: str = "dA1234567"
    demo_mode: bool = True
    # 0 表示不限制，入库聚宽返回的全部概念板块
    ingest_max_concepts: int = 0
    scan_hour: int = 15
    scan_minute: int = 10
    jqdata_rate_limit: float = 25.0  # requests per second


settings = Settings()
