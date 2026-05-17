from datetime import date
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 支持从项目根目录或 backend 目录读取 .env（Docker / 本地 PyCharm 均可）
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent

_PLACEHOLDER_USERS = frozenset({"", "your_phone_or_email", "your_password"})
_PLACEHOLDER_TOKENS = frozenset({"", "your_tushare_token"})


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
    # 数据源：auto | jqdata | tushare | demo（首页可覆盖 data_source.override.json）
    data_source: str = "auto"
    tushare_token: str = ""
    tushare_rate_limit: float = 170.0

    def jq_configured(self) -> bool:
        return (
            self.jqdata_username not in _PLACEHOLDER_USERS
            and self.jqdata_password not in _PLACEHOLDER_USERS
        )

    def tushare_configured(self) -> bool:
        return self.tushare_token not in _PLACEHOLDER_TOKENS

    def effective_data_source(self) -> str:
        from app.services.data_source_store import read_override

        override = read_override()
        if override:
            return override
        return (self.data_source or "auto").lower().strip()

    def use_demo_data(self) -> bool:
        ds = self.effective_data_source()
        if ds == "demo":
            return True
        if ds in ("jqdata", "tushare"):
            return False
        # auto：未配置任何实盘源时用演示
        return self.demo_mode and not self.jq_configured() and not self.tushare_configured()

    def resolved_live_provider(self) -> str | None:
        """返回 jqdata / tushare，或 None（走演示）。"""
        ds = self.effective_data_source()
        if ds == "jqdata":
            return "jqdata"
        if ds == "tushare":
            return "tushare"
        if ds == "auto":
            if self.jq_configured():
                return "jqdata"
            if self.tushare_configured():
                return "tushare"
        return None


settings = Settings()
