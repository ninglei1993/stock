from datetime import date

from app.adapters.base import MarketDataAdapter, SectorQuote


class SectorAggregator:
    def __init__(self, adapter: MarketDataAdapter):
        self.adapter = adapter

    def aggregate_sector(
        self, sector_code: str, sector_name: str, trade_date: date
    ) -> SectorQuote:
        stocks = self.adapter.get_concept_stocks(sector_code, trade_date)
        if not stocks:
            return SectorQuote(sector_code=sector_code, sector_name=sector_name)

        quotes = self.adapter.get_stock_quotes(stocks, trade_date, sector_code)
        if not quotes:
            return SectorQuote(sector_code=sector_code, sector_name=sector_name)

        pcts = [q.pct_change for q in quotes]
        avg_pct = sum(pcts) / len(pcts)
        total_money = sum(q.money for q in quotes)
        limit_up = sum(1 for q in quotes if q.is_limit_up)
        big_yang = sum(1 for q in quotes if q.is_big_yang)
        up_count = sum(1 for q in quotes if q.pct_change > 0)
        blow_ups = sum(1 for q in quotes if q.is_blow_up)
        touched_limit = sum(
            1 for q in quotes if q.high_limit and q.high and q.high >= q.high_limit * 0.998
        )
        blow_rate = blow_ups / touched_limit if touched_limit else 0.0

        return SectorQuote(
            sector_code=sector_code,
            sector_name=sector_name,
            pct_change=round(avg_pct, 2),
            close=100 + avg_pct,
            money=total_money,
            limit_up_count=limit_up,
            big_yang_count=big_yang,
            up_count=up_count,
            total_count=len(quotes),
            blow_up_rate=round(blow_rate, 4),
        )

    def aggregate_flow(self, sector_code: str, trade_date: date) -> tuple[float, int]:
        stocks = self.adapter.get_concept_stocks(sector_code, trade_date)
        if not stocks:
            return 0.0, 0
        flows = self.adapter.get_capital_flows(stocks, trade_date, lookback=5)
        total = sum(f[-1] if f else 0 for f in flows.values())
        inflow_days = 0
        if flows:
            sample = next(iter(flows.values()))
            for i in range(len(sample)):
                day_sum = sum(f[i] for f in flows.values() if len(f) > i)
                if day_sum > 0:
                    inflow_days += 1
        return total, inflow_days
