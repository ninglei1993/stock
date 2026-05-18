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
    # 仅入库名称包含该关键词的概念（如 CPO）；留空表示按 ingest_max_concepts 取列表前 N 个
    ingest_concept_filter: str = ""
    # 每个概念板块最多分析的成分股数；0=全部（CPO 等大盘概念较慢）
    ingest_max_stocks_per_concept: int = 0
    ingest_price_lookback_days: int = 8
    ingest_flow_lookback_days: int = 3
    scan_hour: int = 15
    scan_minute: int = 10
    jqdata_rate_limit: float = 25.0
    # 聚宽账号数据权限区间（按运营说明默认值，可在 .env 覆盖）
    jqdata_data_start: date = date(2025, 2, 6)
    jqdata_data_end: date = date(2026, 2, 13)
    # 数据源：auto | jqdata | tushare | demo（首页可覆盖 data_source.override.json）
    data_source: str = "auto"
    tushare_token: str = ""
    # 第三方 Tushare 代理地址（留空则用官方 api.waditu.com）
    tushare_api_url: str = "http://teajoin.com"
    tushare_rate_limit: float = 170.0
    # True=收盘扫描不落库 PostgreSQL（仅内存快照供仪表盘）；历史回看仍读库。重启/多 worker 不适用
    scan_volatile_storage: bool = False

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
        """演示数据已下线；未配置实盘源时由 get_adapter 报错。"""
        return False

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
