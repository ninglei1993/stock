---
name: themeradar-trading
description: >-
  ThemeRadar（主线雷达）买卖策略、五维评分、四阶段状态机、预警规则与回测逻辑。
  在修改 theme_engine、alert_service、backtest_engine、risk 模块或讨论
  「鱼身策略」「萌芽/发酵/高潮/衰退」「主线选股」时使用。
---

# ThemeRadar 交易策略 Skill

## 产品定位

A 股**概念板块主线**工具：收盘后扫描 → 五维评分 → 四阶段 → 预警 diff → 仓位建议 → 可选回测。

口诀：**盘面先热，消息后吹；资金先进，散户后跟。** 只吃**鱼身**（发酵段），回避鱼尾（高潮/衰退）。

## 代码映射

| 能力 | 文件 |
|------|------|
| 五维评分 + 阶段 | `backend/app/services/theme_engine.py` |
| 预警 diff | `backend/app/services/alert_service.py` |
| 大盘环境 | `backend/app/services/risk.py` |
| 收盘扫描 | `backend/app/services/scan_service.py` |
| 回测买卖 | `backend/app/services/backtest_engine.py` |
| 演示数据 | `backend/app/adapters/demo_adapter.py` |

更细的公式、已知缺陷与半导体案例见 [strategy-analysis.md](strategy-analysis.md)。

---

## 一、五维评分（权重固定）

| 维度 | 权重 | 要点 |
|------|------|------|
| persistence 持续性 | 25% | 近 3 日强势天数 + 当日涨幅分位；昨日大跌今日大涨 → 持续性仅 10 分（防一日游） |
| capital 资金 | 30% | `inflow_days×20`（上限 60）+ `net_inflow/1e5`（上限 40） |
| breadth 广度 | 25% | 涨停×8 + 大阳线×4 + 上涨占比×20（各项有上限） |
| leader 龙头 | 15% | 连板×15 + 龙头 5 日涨幅 + 成交额占比 |
| relative 相对强度 | 5% | 板块涨幅 − 沪深300，每 1% 超额约 +10 分 |

**假主线过滤**（`total_score × 0.5`）：
- 一日游：今日涨 >2% 且昨日跌 <-0.5%，且前两日偏弱
- 资金脉冲：涨停 <2 且资金连续流入 ≤1 日

**排名**：过滤后仍 ≥50 分的板块参与排序；扫描结果写入 `sector_score_daily`（仪表盘仅展示 Top5）。

---

## 二、四阶段状态机

判定顺序（`ThemeEngine._determine_stage`）：

1. **decay 衰退**：近 3 日资金净流出且 3 日累计跌幅 <-3%；或炸板率 >40% 且总分 ≥70；或前日为发酵/高潮且总分 <50
2. **climax 高潮**：总分 ≥85 且（炸板率 >30% 或涨停 ≥8）
3. **ferment 发酵**：总分 ≥70 且（涨停 ≥5 或大阳线 ≥8）
4. **sprout 萌芽**：总分 ≥55 且资金连续流入 ≥2 日，且涨停 1–5（或仅满足分数+流入）
5. **dormant 沉寂**：其余

**仓位建议**（可被大盘环境覆盖）：

| 阶段 | position_hint | 含义 |
|------|---------------|------|
| sprout | light_position | 轻仓观察 |
| ferment | hold | 持有鱼身 |
| climax | reduce | 减仓 |
| decay | exit | 清仓 |
| dormant | observe | 观望 |

大盘 `env_score < 40` 或 `can_long=false` 时，萌芽/持有建议降为 **observe**。

---

## 三、大盘环境（禁多闸门）

`RiskModule.compute_env`：
- 基础分 50 + 涨停家数×0.5 + (涨跌比−0.5)×40 + 指数涨跌幅×3，截断 [0,100]
- 涨停 <20 或涨跌比 <0.4 → 分数上限 45
- **≥60**：can_long，结论「可做多」
- **40–60**：谨慎，仍可 can_long
- **<40**：observe，**can_long=false**（回测非 fixed_hold 策略禁止开新仓）

回测 **fish_body** 额外要求：`env_score >= 60` 才响应买入信号。

---

## 四、预警规则（日频 diff）

比较**今日 vs 昨日**评分（`AlertService.diff_alerts`）：

| alert_code | 触发条件 | 交易含义 |
|------------|----------|----------|
| NEW_SPROUT | 今日 sprout 且昨日 dormant，总分 ≥55 | 新晋萌芽，可观察 |
| STAGE_UP | 今日 ferment 且昨日 sprout | **鱼身策略默认买点** |
| STRENGTH_SURGE | 总分较昨日 +≥15 且今日 ≥55 | 强度跃升（鱼身**不买**） |
| EXIT_CLIMAX | 今日 climax 且昨日 ferment/sprout | **默认卖点** |
| EXIT_DECAY | 今日 decay 且昨日 climax/ferment/sprout | **默认卖点** |
| ENV_BAD | 环境分 <40 且较昨日骤降 ≥20 | 禁多提示 |

---

## 五、回测策略（`BacktestEngine`）

共用参数（默认）：`max_positions=3`，`position_size=0.1`（每笔盈亏只影响 10% 净值 → 曲线波动观感与单笔放大有关）。

成本：佣金万 2.5×2 + 印花税 0.1% + 滑点 0.1%×2。

**成交假设**：信号日 T 收盘产生 → **T+1 开盘价**买入/卖出（龙头价，无龙头则用成分股或 10 元占位）。

### 5.1 fish_body（鱼身策略）— 默认

- **买**：`STAGE_UP` 且 `env_score >= 60`，且 `can_long`，持仓 < max_positions
- **卖**：`EXIT_CLIMAX` 或 `EXIT_DECAY`
- **设计意图**：只吃 sprout→ferment 升级，高潮前离场
- **已知弱点**：错过已在发酵/高潮的强势板块；环境分 60 门槛过滤大量交易日；卖点偏早/偏晚取决于阶段判定

### 5.2 sprout_probe（萌芽试探）

- **买**：`NEW_SPROUT` 且总分 ≥55
- **卖**：同 fish_body
- **弱点**：萌芽假突破多，胜率通常低于 fish_body

### 5.3 top5_rotation

- **买**：`rank <= 5` 且阶段 ferment 或 climax（**高潮仍买**— 与口诀冲突）
- **卖**：EXIT 类
- **弱点**：高潮买入易接鱼尾

### 5.4 fixed_hold（基准）

- **买**：`NEW_SPROUT`；**不卖**（持有至回测结束按入场价平仓，收益记 0）
- 用于对比信号质量，非实盘逻辑

---

## 六、修改策略时的检查清单

1. 阶段阈值是否与 `theme_engine._determine_stage` 一致
2. 预警是否与 `alert_service` 同步（买卖点依赖 alert_code）
3. fish_body 是否仍满足「发酵买、高潮卖」产品定义
4. 回测是否仍用 T+1 开盘、无未来函数
5. DEMO_MODE 下结论不可直接等同于实盘（见 analysis 文档）

---

## 七、何时用 Skill vs Rule

- **本 Skill**：领域知识、参数含义、改引擎/回测前的完整上下文（推荐）
- **`.cursor/rules/*.md`**：仅适合 1–2 行的仓库约定（如「改评分必须补 test_theme_engine」），不适合承载整套交易逻辑
