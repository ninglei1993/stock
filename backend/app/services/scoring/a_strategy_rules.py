from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.theme_engine import SectorMetrics


@dataclass(frozen=True)
class RuleEval:
    key: str
    label: str
    passed: bool
    threshold: str
    current: Any
    source: str = "auto"

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "passed": self.passed,
            "threshold": self.threshold,
            "current": self.current,
            "source": self.source,
        }


def _manual_bool(manual: dict[str, Any], key: str) -> bool | None:
    val = manual.get(key)
    if val is None:
        return None
    return bool(val)


def _manual_number(manual: dict[str, Any], key: str) -> float | None:
    val = manual.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def evaluate_main_line_rules(metrics: SectorMetrics) -> list[RuleEval]:
    manual = metrics.manual_flags or {}
    source_auto = "auto"
    source_manual = "manual"

    trend_ok = bool(metrics.close_history) and bool(metrics.ma20) and (
        metrics.close_history[-1] > metrics.ma20 and metrics.ma20_slope_up
    )
    r1 = RuleEval(
        key="trend_ma20_up",
        label="趋势条件（站上MA20且MA20向上）",
        passed=trend_ok,
        threshold="close > MA20 and MA20 > MA20_prev",
        current={
            "close": metrics.close_history[-1] if metrics.close_history else 0.0,
            "ma20": round(metrics.ma20, 4),
            "ma20_prev": round(metrics.ma20_prev, 4),
        },
        source=source_auto,
    )

    tier = "rotation"
    if metrics.pct_20d >= 18:
        tier = "top"
    elif metrics.pct_20d >= 10:
        tier = "secondary"
    r2 = RuleEval(
        key="pct_20d_tier",
        label="20日涨幅分级",
        passed=tier != "rotation",
        threshold=">=10%（>=18%为顶级主线）",
        current={"pct_20d": round(metrics.pct_20d, 4), "tier": tier},
        source=source_auto,
    )

    volume_ok = metrics.vol_ratio_5d >= 1.6 and metrics.market_share_8d_ok
    r3 = RuleEval(
        key="volume_heat",
        label="量能持续性",
        passed=volume_ok,
        threshold="vol_ratio_5d>=1.6 and share8d>=4.5%",
        current={
            "vol_ratio_5d": round(metrics.vol_ratio_5d, 4),
            "share_8d_ok": metrics.market_share_8d_ok,
            "share_history": [round(v, 4) for v in metrics.market_money_share_history[-8:]],
          "vol_ratio_debug": {
            "vol_last": (metrics.vol_ratio_debug.get("vol_last") if metrics.vol_ratio_debug else None),
            "vol_ma5": (metrics.vol_ratio_debug.get("vol_ma5") if metrics.vol_ratio_debug else None),
            "vol_values_last6": metrics.vol_ratio_debug.get("vol_values_last6")
              if metrics.vol_ratio_debug else None,
          },
          "share_8d_debug": metrics.market_share_8d_debug,
        },
        source=source_auto,
    )

    northbound_5d = _manual_number(manual, "northbound_5d_yi")
    northbound_ok = True if northbound_5d is None else northbound_5d >= 2.0
    r4 = RuleEval(
        key="capital_inflow",
        label="资金连续流入",
        passed=metrics.inflow_streak_days >= 6 and northbound_ok,
        threshold="主力连续6日净流入 and 北向5日净流入>=2亿",
        current={
            "main_inflow_streak_days": metrics.inflow_streak_days,
            "northbound_5d_yi": northbound_5d,
          # 用于核算“连续流入”的原始判定序列（从近端截取，避免过长）
          "net_inflow_history_tail": [round(v, 6) for v in metrics.net_inflow_history[-12:]],
        },
        source=source_manual if northbound_5d is not None else source_auto,
    )

    r5 = RuleEval(
        key="money_effect",
        label="板块赚钱效应",
        passed=(
            metrics.up_ratio >= 0.65
            and metrics.max_limit_up_streak >= 3
            and metrics.limit_up_count >= 5
        ),
        threshold="up_ratio>=65%, max连板>=3, 涨停>=5",
        current={
            "up_ratio": round(metrics.up_ratio, 4),
            "max_limit_up_streak": metrics.max_limit_up_streak,
            "limit_up_count": metrics.limit_up_count,
        },
        source=source_auto,
    )

    manual_negative = _manual_bool(manual, "negative_news")
    if manual_negative is None:
        manual_negative = False
    auction_passed = _manual_bool(manual, "auction_passed")
    if auction_passed is None:
        auction_passed = True
    r6 = RuleEval(
        key="no_negative_news",
        label="竞价与基本面无压制",
        passed=(not manual_negative) and auction_passed,
        threshold="竞价门槛通过且无监管利空/集体减持/政策降温",
        current={"negative_news": manual_negative, "auction_passed": auction_passed},
        source=source_manual,
    )

    return [r1, r2, r3, r4, r5, r6]


def evaluate_confirm_exit_signals(metrics: SectorMetrics, rules: list[RuleEval]) -> tuple[str, str]:
    rule_pass_count = sum(1 for r in rules if r.passed)
    confirm_signals = 0
    if rule_pass_count == 6:
        confirm_signals += 1
    if metrics.ma20_slope_up:
        confirm_signals += 1
    if metrics.max_limit_up_streak >= 5:
        confirm_signals += 1
    if metrics.inflow_streak_days >= 10:
        confirm_signals += 1

    exit_hits = 0
    if metrics.pct_20d <= -12:
        exit_hits += 1
    if not metrics.ma20_slope_up:
        exit_hits += 1
    outflow_streak = 0
    for v in reversed(metrics.net_inflow_history):
        if v < 0:
            outflow_streak += 1
        else:
            break
    if outflow_streak >= 3:
        exit_hits += 1
    if metrics.max_limit_up_streak < 2:
        exit_hits += 1
    if len(metrics.close_history) >= 2 and metrics.limit_up_count < 2:
        exit_hits += 1

    confirm_state = "confirmed" if confirm_signals >= 4 else "pending"
    exit_state = "exit" if exit_hits >= 2 else "normal"
    return confirm_state, exit_state
