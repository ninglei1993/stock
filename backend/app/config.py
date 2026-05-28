from datetime import date
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 支持从项目根目录或 backend 目录读取 .env（Docker / 本地 PyCharm 均可）
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent

_PLACEHOLDER_TOKENS = frozenset({"", "your_tushare_token"})


def _read_tushare_token_fallback() -> str:
    """
    本地兜底读取 token（仅当环境变量未设置时生效）。
    支持项目根目录 tk.csv：
      token
      <actual_token>
    """
    p = _PROJECT_ROOT / "tk.csv"
    if not p.is_file():
        return ""
    try:
        lines = [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()]
    except OSError:
        return ""
    for ln in lines:
        if not ln or ln.lower() == "token":
            continue
        return ln
    return ""


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
    tushare_token: str = _read_tushare_token_fallback()
    # 第三方 Tushare 代理地址（留空则用官方 api.waditu.com）
    tushare_api_url: str = ""
    # Tushare 单次请求超时（秒）
    tushare_timeout_seconds: int = 120
    tushare_rate_limit: float = 170.0
    scan_volatile_storage: bool = False
    # 本地数据目录：全市场行情 JSON + scan/latest.json
    data_dir: Path = _PROJECT_ROOT / "data"
    # 按交易日缓存全市场 daily / stk_limit / moneyflow_dc（默认开启）
    market_cache_enabled: bool = True

    def tushare_configured(self) -> bool:
        return self.tushare_token not in _PLACEHOLDER_TOKENS

    def effective_scoring_mode(self) -> str:
        """系统仅保留 A 策略主线规则。"""
        return "a_strategy"


settings = Settings()
