from datetime import date
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 支持从项目根目录或 backend 目录读取 .env（Docker / 本地 PyCharm 均可）
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent

_PLACEHOLDER_USERS = frozenset({"", "your_phone_or_email", "your_password"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            _PROJECT_ROOT / ".env",
            _BACKEND_DIR / ".env",
            ".env",
            "../.env",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://themeradar:themeradar@localhost:5432/themeradar"
    database_url_sync: str = "postgresql://themeradar:themeradar@localhost:5432/themeradar"
    redis_url: str = "redis://localhost:6379/0"
    jqdata_username: str = ""
    jqdata_password: str = ""
    demo_mode: bool = True
    # 0=全部概念（耗聚宽日配额极大）；免费账号建议 30~80
    ingest_max_concepts: int = 50
    scan_hour: int = 15
    scan_minute: int = 10
    jqdata_rate_limit: float = 25.0
    # 聚宽账号数据权限区间（按运营说明默认值，可在 .env 覆盖）
    jqdata_data_start: date = date(2025, 2, 6)
    jqdata_data_end: date = date(2026, 2, 13)

    def jq_configured(self) -> bool:
        return (
            self.jqdata_username not in _PLACEHOLDER_USERS
            and self.jqdata_password not in _PLACEHOLDER_USERS
        )

    def use_demo_data(self) -> bool:
        """已配置聚宽账号时强制使用 JQData，不再走演示数据。"""
        if self.jq_configured():
            return False
        return self.demo_mode


settings = Settings()
