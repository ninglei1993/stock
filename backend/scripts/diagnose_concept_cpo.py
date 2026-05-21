"""
诊断脚本：以“CPO”概念板块为例，回放数据链路并输出：

1) 实际调用的 Tushare Pro 接口（接口名+关键入参）
2) 每日板块聚合结果（涨幅/涨停/炸板率/成交额等）
3) A 策略 6 条硬规则逐条校验（阈值、当前值、是否满足）

运行示例：
  python3 backend/scripts/diagnose_concept_cpo.py --start 2026-05-06 --end 2026-05-20 --max-stocks 200

前置：
  - .env 配置 TUSHARE_TOKEN（必要）
  - 可选：TUSHARE_API_URL（默认 http://teajoin.com）
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# 允许直接用 `python3 backend/scripts/xxx.py` 运行（无需手动 PYTHONPATH）
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

try:
    # app.config 依赖 pydantic-settings；若环境没装依赖，会在 import app.* 时失败
    import pydantic_settings  # noqa: F401
except ModuleNotFoundError:
    print(
        "\n缺少依赖：pydantic-settings。\n"
        "你当前的 python 环境还没安装后端 requirements。\n\n"
        "建议在项目根目录执行（macOS/zsh）：\n"
        "  python3 -m venv .venv\n"
        "  source .venv/bin/activate\n"
        "  pip install -r backend/requirements.txt\n\n"
        "然后再运行：\n"
        "  python3 backend/scripts/diagnose_concept_cpo.py --start 2026-05-06 --end 2026-05-20\n"
    )
    raise SystemExit(2)

from app.adapters.factory import get_adapter  # noqa: E402
from app.adapters.tushare_adapter import TushareAdapter  # noqa: E402
from app.services.scan_context import clear_scan_context, set_scan_bounds  # noqa: E402
from app.services.scoring.a_strategy_rules import evaluate_main_line_rules  # noqa: E402
from app.services.sector_aggregator import SectorAggregator  # noqa: E402
from app.services.theme_engine import ThemeEngine  # noqa: E402
from app.services.trade_calendar import latest_completed_trade_day  # noqa: E402


logger = logging.getLogger(__name__)


def _d(s: str) -> date:
    return date.fromisoformat(s)


@dataclass(frozen=True)
class _DailyRow:
    trade_date: date
    sector_code: str
    sector_name: str
    pct_change: float
    close: float
    money: float
    limit_up_count: int
    big_yang_count: int
    up_count: int
    total_count: int
    blow_up_rate: float


@dataclass(frozen=True)
class _FlowRow:
    trade_date: date
    sector_code: str
    net_inflow_main: float
    inflow_days: int


def _pick_cpo_concept(adapter: TushareAdapter) -> tuple[str, str]:
    concepts = adapter.list_concepts()  # ths_index
    cands = [c for c in concepts if "cpo" in (c.name or "").lower()]
    if not cands:
        # 兜底：有些库里名称可能是“光模块/CPO/共封装光学”等
        cands = [c for c in concepts if "共封装" in (c.name or "") or "光学" in (c.name or "")]
    if not cands:
        raise RuntimeError("未在 ths_index 概念列表中找到包含 CPO 的概念名称")
    # 多个候选时优先名称最短（更像标准概念名），然后按代码稳定排序
    cands.sort(key=lambda x: (len(x.name or ""), x.code))
    chosen = cands[0]
    return chosen.code, chosen.name


def _dump(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(obj)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="", help="开始日期 YYYY-MM-DD（不传则默认近30天）")
    parser.add_argument("--end", default="", help="结束日期 YYYY-MM-DD（不传则默认最近已收盘交易日）")
    parser.add_argument("--max-stocks", type=int, default=200, help="每个交易日用于聚合的成分股上限（0=全量）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    adapter = get_adapter()
    if adapter.__class__.__name__ != "TushareAdapter":
        raise RuntimeError(f"当前适配器不是 TushareAdapter（got={adapter.__class__.__name__}）")

    ts: TushareAdapter = adapter  # type: ignore[assignment]

    # 明确列出本项目会用到的接口（脚本执行过程中也会由 adapter 日志输出实际请求）
    print("\n=== 本项目（Tushare 模式）会调用的接口清单（按链路顺序） ===")
    print("1) trade_cal(exchange='SSE', start_date, end_date, is_open='1')  # 交易日历")
    print("2) ths_index(exchange='A', type='N')                            # 同花顺概念板块列表")
    print("3) ths_member(ts_code=概念ts_code)                              # 概念成分股列表")
    print("4) index_daily(ts_code='000300.SH', start_date, end_date)       # 沪深300（日线）")
    print("5) daily(trade_date=YYYYMMDD)                                   # 全市场日线（成交额/开高低收）")
    print("6) stk_limit(trade_date=YYYYMMDD)                               # 全市场涨跌停价表（用于涨停/炸板识别）")
    print("7) moneyflow_dc(trade_date=YYYYMMDD)                             # 全市场主力资金流")
    print("   ↳ 若 moneyflow_dc 返回空：fallback moneyflow(trade_date=YYYYMMDD)")
    print("8) limit_list_d(trade_date=YYYYMMDD, limit_type='U')             # 全市场涨停家数（用于大盘环境）")
    print("9) stock_basic(fields='ts_code,name')                            # 股票中文名（用于展示）")

    end = _d(args.end) if args.end else latest_completed_trade_day()
    start = _d(args.start) if args.start else (end - timedelta(days=30))
    days = ts.get_trade_days(start, end)  # trade_cal
    if not days:
        raise RuntimeError(f"区间 {start}~{end} 无交易日")
    set_scan_bounds(days, calendar_start=start, calendar_end=end)

    try:
        concept_code, concept_name = _pick_cpo_concept(ts)  # ths_index
        print(f"\n=== 选定概念：{concept_name} ({concept_code}) ===")

        # 预取全市场三表：daily/stk_limit/moneyflow_dc（写入 data/market）
        ts.prefetch_shared_market_data(days[-1], flow_lookback=6, price_lookback=21)

        agg = SectorAggregator(ts)
        eng = ThemeEngine()

        daily_rows: list[_DailyRow] = []
        flow_rows: list[_FlowRow] = []
        market_money_by_day: dict[date, float] = {}

        for td in days:
            # 1) 成分股：ths_member
            members = ts.get_concept_stocks(concept_code, td)
            if args.max_stocks and args.max_stocks > 0 and len(members) > args.max_stocks:
                members = members[: args.max_stocks]

            # 2) 资金流：从全市场 moneyflow 表筛选，不再对每只股票打接口
            flows = ts.get_capital_flows(members, td, lookback=6)
            net, inflow_days = agg.aggregate_flow_from_flows(flows)

            # 3) 行情：从全市场 daily/stk_limit 表筛选
            quotes = ts.get_stock_quotes(members, td, concept_code, price_lookback_days=21, capital_flows=flows)

            # 4) 板块聚合：涨幅/涨停/炸板/成交额等
            sector_q = agg.aggregate_sector_from_quotes(concept_code, concept_name, quotes)

            dr = _DailyRow(
                trade_date=td,
                sector_code=concept_code,
                sector_name=concept_name,
                pct_change=float(sector_q.pct_change or 0.0),
                close=float(sector_q.close or 0.0),
                money=float(sector_q.money or 0.0),
                limit_up_count=int(sector_q.limit_up_count or 0),
                big_yang_count=int(sector_q.big_yang_count or 0),
                up_count=int(sector_q.up_count or 0),
                total_count=int(sector_q.total_count or 0),
                blow_up_rate=float(sector_q.blow_up_rate or 0.0),
            )
            fr = _FlowRow(
                trade_date=td,
                sector_code=concept_code,
                net_inflow_main=float(net or 0.0),
                inflow_days=int(inflow_days or 0),
            )
            daily_rows.append(dr)
            flow_rows.append(fr)

            # market turnover（用于 A 策略量能占比规则）
            daily_df = ts._daily_market(td)  # noqa: SLF001
            mk_money = float(daily_df["amount"].astype(float).sum()) if not daily_df.empty and "amount" in daily_df.columns else 0.0
            market_money_by_day[td] = mk_money

            # 5) A 策略规则评估（逐日“回放”）
            metrics = eng.build_metrics_from_db(
                sector_code=concept_code,
                sector_name=concept_name,
                daily_rows=daily_rows[-25:],
                flow_rows=flow_rows[-25:],
                leader_streak=0,
                leader_pct_5d=0.0,
                leader_money_share=0.0,
                index_pct=0.0,
                market_money_by_day=market_money_by_day,
                max_limit_up_streak=0,
            )
            rules = evaluate_main_line_rules(metrics)
            pass_cnt = sum(1 for r in rules if r.passed)

            print(f"\n--- {td} | 成分股={len(members)} | 板块pct={dr.pct_change:.2f}% | 涨停={dr.limit_up_count} | 炸板率={dr.blow_up_rate:.2%} | 主力净流入(原始单位)={fr.net_inflow_main:.2f} ---")
            print(f"规则通过 {pass_cnt}/6： " + ("主线通过" if pass_cnt == 6 else "未通过"))
            for r in rules:
                status = "满足" if r.passed else "不满足"
                print(f"- {status} | {r.label} | threshold={r.threshold} | current={_dump(r.current)} | source={r.source}")

        print("\n=== 诊断完成 ===")
        return 0
    finally:
        clear_scan_context()


if __name__ == "__main__":
    raise SystemExit(main())

