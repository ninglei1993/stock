"""策略与业务字段中文映射（内部代码仍用英文枚举）。"""

ALERT_LABELS: dict[str, str] = {
    "NEW_SPROUT": "新晋萌芽",
    "STAGE_UP": "阶段升级",
    "STRENGTH_SURGE": "强度跃升",
    "EXIT_CLIMAX": "高潮撤退",
    "EXIT_DECAY": "衰退清仓",
    "ENV_BAD": "环境恶化",
    "MAIN_LINE_BUY": "主线买入",
    "MAIN_LINE_ROTATE": "主线换仓",
    "A_STRATEGY_BUY": "A策略买入",
    "A_STRATEGY_EXIT": "A策略退出",
    "A_STRATEGY_STOP_LOSS": "A策略止损",
}

STRATEGY_LABELS: dict[str, str] = {
    "main_line_rotation": "主线轮动（单仓龙头）",
    "fish_body": "鱼身策略（发酵买/高潮卖）",
    "sprout_probe": "萌芽试探",
    "fixed_hold": "固定持有（基准）",
    "top5_rotation": "前五轮动",
    "a_strategy_strict": "A策略严格回测",
}

RUN_STATUS_LABELS: dict[str, str] = {
    "pending": "待执行",
    "running": "运行中",
    "done": "已完成",
    "failed": "失败",
}

STAGE_LABELS: dict[str, str] = {
    "sprout": "萌芽",
    "ferment": "发酵",
    "climax": "高潮",
    "decay": "衰退",
    "dormant": "沉寂",
}

POSITION_LABELS: dict[str, str] = {
    "light_position": "轻仓试探",
    "hold": "持有鱼身",
    "reduce": "建议减仓",
    "exit": "建议清仓",
    "observe": "观望",
}

ENV_CONCLUSION_LABELS: dict[str, str] = {
    "can_long": "可做多",
    "caution": "谨慎",
    "observe": "观望",
}

TRADE_MODE_LEADER_STOCK = "板块龙头个股"

BACKTEST_TRADE_NOTE = (
    "回测标的为各概念板块的龙头个股（非板块ETF、非指数基金）。"
    "信号在收盘后产生，买入价为信号日下一交易日开盘价；"
    "卖出价为卖出信号日下一交易日开盘价。"
)
