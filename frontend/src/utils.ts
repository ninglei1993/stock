/** A股习惯：涨红跌绿 */
export function pctClass(v: number): string {
  if (v > 0) return "text-up";
  if (v < 0) return "text-down";
  return "text-flat";
}

export function formatPct(v: number, digits = 2): string {
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

export const STAGE_LABEL: Record<string, string> = {
  sprout: "萌芽",
  ferment: "发酵",
  climax: "高潮",
  decay: "衰退",
  dormant: "沉寂",
};

export const POSITION_LABEL: Record<string, string> = {
  light_position: "轻仓试探",
  hold: "持有鱼身",
  reduce: "建议减仓",
  exit: "建议清仓",
  observe: "观望",
};

export const SCORE_DIM_LABEL: Record<string, string> = {
  persistence: "持续性",
  capital: "资金",
  breadth: "广度",
  leader: "龙头",
  relative: "相对强度",
};

export const ALERT_LABEL: Record<string, string> = {
  NEW_SPROUT: "新晋萌芽",
  STAGE_UP: "阶段升级",
  STRENGTH_SURGE: "强度跃升",
  EXIT_CLIMAX: "高潮撤退",
  EXIT_DECAY: "衰退清仓",
  ENV_BAD: "环境恶化",
};

export const STRATEGY_LABEL: Record<string, string> = {
  fish_body: "鱼身策略（发酵买/高潮卖）",
  sprout_probe: "萌芽试探",
  fixed_hold: "固定持有（基准）",
  top5_rotation: "前五轮动",
};

export const RUN_STATUS_LABEL: Record<string, string> = {
  pending: "待执行",
  running: "运行中",
  done: "已完成",
  failed: "失败",
};

export const ENV_CONCLUSION_LABEL: Record<string, string> = {
  can_long: "可做多",
  caution: "谨慎",
  observe: "观望",
};
