"""Demo adapter with synthetic data when JQData credentials are unavailable."""
import hashlib
import math
import random
from datetime import date, timedelta

from app.adapters.base import (
    ConceptInfo,
    IndexBar,
    MarketBreadth,
    MarketDataAdapter,
    SectorQuote,
    StockQuote,
)


DEMO_CONCEPTS = [
    ("GN759", "航空航天"),
    ("GN034", "环保概念"),
    ("GN198", "证金概念"),
    ("GN240", "MSCI概念"),
    ("GN701", "阿里巴巴概念"),
    ("GN1004", "腾讯概念"),
    ("GN1021", "独角兽概念"),
    ("GN185", "高送转概念"),
    ("GN111", "文化传媒概念"),
    ("GN256", "360概念"),
    ("GN880", "半导体概念"),
    ("GN890", "芯片概念"),
    ("GN920", "新能源车"),
    ("GN950", "人工智能"),
    ("GN960", "储能概念"),
    ("GN970", "商业航天"),
    ("GN981", "算力概念"),
    ("GN982", "CPO概念"),
    ("GN983", "光模块概念"),
    ("GN984", "华为算力"),
]

# 演示模式下模拟 2026 年起算力/半导体主线（仅 DEMO，非真实行情）
_DEMO_THEME_LEAD_CODES = frozenset(
    {"GN880", "GN890", "GN950", "GN981", "GN982", "GN983", "GN984"}
)


def _seeded_rng(key: str, trade_date: date) -> random.Random:
    h = hashlib.md5(f"{key}:{trade_date}".encode()).hexdigest()
    return random.Random(int(h[:8], 16))


class DemoAdapter(MarketDataAdapter):
    def get_trade_days(self, start_date: date, end_date: date) -> list[date]:
        days: list[date] = []
        d = start_date
        while d <= end_date:
            if d.weekday() < 5:
                days.append(d)
            d += timedelta(days=1)
        return days

    def list_concepts(self) -> list[ConceptInfo]:
        return [ConceptInfo(code=c, name=n) for c, n in DEMO_CONCEPTS]

    def get_concept_stocks(self, concept_code: str, trade_date: date) -> list[str]:
        rng = _seeded_rng(concept_code, trade_date)
        n = rng.randint(8, 25)
        codes: set[str] = set()
        while len(codes) < n:
            codes.add(f"{600000 + rng.randint(0, 9999)}.XSHG")
        return list(codes)

    def get_sector_quotes(self, trade_date: date, concept_codes: list[str]) -> list[SectorQuote]:
        results: list[SectorQuote] = []
        names = {c: n for c, n in DEMO_CONCEPTS}
        for i, code in enumerate(concept_codes):
            rng = _seeded_rng(code, trade_date)
            phase = (trade_date.toordinal() + i * 7) % 30
            # 2026 年起半导体/算力相关概念在演示数据中更强（便于回测验证主线逻辑）
            theme_lead = (
                code in _DEMO_THEME_LEAD_CODES
                and trade_date >= date(2026, 1, 1)
            )
            if theme_lead:
                pct = rng.uniform(1.5, 5.5)
                limit_up = rng.randint(3, 10)
            elif phase < 8:
                pct = rng.uniform(0.5, 3.5)
                limit_up = rng.randint(1, 3)
            elif phase < 18:
                pct = rng.uniform(2.0, 6.0)
                limit_up = rng.randint(4, 12)
            else:
                pct = rng.uniform(-2.0, 1.5)
                limit_up = rng.randint(0, 2)
            total = rng.randint(12, 30)
            up = int(total * rng.uniform(0.4, 0.9))
            results.append(
                SectorQuote(
                    sector_code=code,
                    sector_name=names.get(code, code),
                    pct_change=round(pct, 2),
                    close=100 + pct,
                    money=rng.uniform(5e8, 5e9),
                    limit_up_count=limit_up,
                    big_yang_count=rng.randint(2, 10),
                    up_count=up,
                    total_count=total,
                    blow_up_rate=rng.uniform(0, 0.5) if phase > 15 else rng.uniform(0, 0.15),
                )
            )
        return results

    def get_stock_quotes(
        self, stock_codes: list[str], trade_date: date, sector_code: str = ""
    ) -> list[StockQuote]:
        results: list[StockQuote] = []
        for code in stock_codes:
            rng = _seeded_rng(f"{sector_code}:{code}", trade_date)
            pct = rng.uniform(-5, 10)
            hl = 10.0
            close = 10 * (1 + pct / 100)
            high_limit = close * (1 + hl / 100) / (1 + pct / 100) if pct else close * 1.1
            is_lu = pct >= 9.5
            is_blow = rng.random() < 0.1 and pct < 9.5 and pct > 5
            results.append(
                StockQuote(
                    stock_code=code,
                    sector_code=sector_code,
                    pct_change=round(pct, 2),
                    close=close,
                    high=close * 1.02,
                    high_limit=high_limit,
                    money=rng.uniform(1e7, 5e8),
                    is_limit_up=is_lu,
                    is_big_yang=pct >= 7,
                    is_blow_up=is_blow,
                    limit_up_streak=rng.randint(0, 4) if is_lu else 0,
                    net_inflow_main=rng.uniform(-5000, 15000),
                )
            )
        return results

    def get_capital_flows(
        self, stock_codes: list[str], trade_date: date, lookback: int = 5
    ) -> dict[str, list[float]]:
        flows: dict[str, list[float]] = {}
        for code in stock_codes:
            rng = _seeded_rng(f"flow:{code}", trade_date)
            flows[code] = [rng.uniform(-3000, 8000) for _ in range(lookback)]
        return flows

    def get_index_bars(self, code: str, start_date: date, end_date: date) -> list[IndexBar]:
        bars: list[IndexBar] = []
        price = 3800.0
        for d in self.get_trade_days(start_date, end_date):
            rng = _seeded_rng(code, d)
            pct = rng.uniform(-2, 2)
            price *= 1 + pct / 100
            bars.append(
                IndexBar(
                    code=code,
                    trade_date=d,
                    open=price * 0.99,
                    close=price,
                    high=price * 1.01,
                    low=price * 0.98,
                    pct_change=round(pct, 2),
                )
            )
        return bars

    def get_market_breadth(self, trade_date: date) -> MarketBreadth:
        rng = _seeded_rng("market", trade_date)
        up = rng.randint(1500, 3500)
        down = rng.randint(1000, 3000)
        return MarketBreadth(
            trade_date=trade_date,
            limit_up_count=rng.randint(30, 120),
            up_count=up,
            down_count=down,
            total_count=up + down,
        )
