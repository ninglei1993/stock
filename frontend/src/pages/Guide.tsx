import { Link } from "react-router-dom";

const STEPS = [
  {
    n: 1,
    title: "执行收盘扫描",
    where: "仪表盘",
    desc: "每个交易日收盘后（约 15:10 后），点击「执行收盘扫描」。系统拉取板块行情与资金流，按 A 策略主线 6 条硬规则评估，并给出每条指标是否满足与当前值。",
  },
  {
    n: 2,
    title: "看大盘环境",
    where: "仪表盘 · 环境条",
    desc: "环境分 ≥60 可做多，40–60 谨慎，<40 系统禁多。结合涨停家数、涨跌比、沪深300涨跌综合判断。",
  },
  {
    n: 3,
    title: "锁定 Top5 主线",
    where: "仪表盘 · 主线卡片 / 板块列表",
    desc: "板块卡片会标注「主线通过 / 未通过」。点击详情可查看满足/不满足的具体指标，以及每项指标的阈值与当前值。",
  },
  {
    n: 4,
    title: "处理预警",
    where: "预警中心",
    desc: "新晋萌芽、阶段升级（萌芽→发酵）可关注；高潮撤退、衰退清仓需重视。每条预警附带中文理由。",
  },
  {
    n: 5,
    title: "复盘与回测",
    where: "复盘日历 / 回测中心",
    desc: "复盘：查看历史某日 Top 主线及随后涨跌。回测：验证「鱼身策略」在历史区间的表现。",
  },
];

const RULES = [
  "盘面先热，消息后吹；资金先进，散户后跟。",
  "只吃鱼身：萌芽/发酵关注，高潮/衰退撤退。",
  "一日游、资金脉冲型假主线会被降权或标记观察。",
];

export default function Guide() {
  return (
    <div className="guide-page">
      <h2 className="page-title">使用指南</h2>
      <p className="page-subtitle">
        主线雷达帮你把「每天 5 分钟看盘」变成可重复流程。口诀：
        <strong> 盘面先热，消息后吹；资金先进，散户后跟。</strong>
      </p>

      <div className="guide-hero card-glass">
        <div className="guide-hero-inner">
          <span className="guide-hero-label">推荐每日流程</span>
          <div className="guide-flow">
            {["收盘扫描", "看环境", "看 Top5", "处理预警", "择机操作"].map((s, i) => (
              <span key={s} className="guide-flow-item">
                {i > 0 && <span className="guide-flow-arrow">→</span>}
                {s}
              </span>
            ))}
          </div>
        </div>
      </div>

      <h3 className="section-title">五步操作</h3>
      <div className="steps-grid">
        {STEPS.map((s) => (
          <div key={s.n} className="step-card card-glass">
            <div className="step-num">{s.n}</div>
            <div>
              <div className="step-title">{s.title}</div>
              <div className="step-where">{s.where}</div>
              <p className="step-desc">{s.desc}</p>
            </div>
          </div>
        ))}
      </div>

      <h3 className="section-title">四阶段含义</h3>
      <div className="stage-table card-glass">
        <table>
          <thead>
            <tr>
              <th>阶段</th>
              <th>含义</th>
              <th>建议</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><span className="stage-badge stage-sprout">萌芽</span></td>
              <td>连续强势、资金流入、少量涨停</td>
              <td>轻仓观察，等待发酵</td>
            </tr>
            <tr>
              <td><span className="stage-badge stage-ferment">发酵</span></td>
              <td>批量涨停、广度扩散</td>
              <td>持有鱼身，移动止盈</td>
            </tr>
            <tr>
              <td><span className="stage-badge stage-climax">高潮</span></td>
              <td>全民讨论、高位放量、炸板增多</td>
              <td>减仓，不碰鱼尾</td>
            </tr>
            <tr>
              <td><span className="stage-badge stage-decay">衰退</span></td>
              <td>资金流出、板块走弱</td>
              <td>清仓观望</td>
            </tr>
          </tbody>
        </table>
      </div>

      <h3 className="section-title">A策略主线硬指标（6条全满足=主线）</h3>
      <ul className="rules-list card-glass">
        {[
          "趋势条件：收盘价站上 MA20 且 MA20 向上。",
          "20日涨幅：≥10%（≥18% 为顶级主线）。",
          "量能持续性：放量（≥1.6×5日均量）且成交额占比满足门槛。",
          "资金连续流入：主力连续净流入（北向 5 日净流入可人工补录）。",
          "赚钱效应：上涨占比、涨停家数、最高连板高度达标。",
          "竞价与基本面无压制：竞价门槛与利空项可人工补录。",
        ].map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>

      <h3 className="section-title">原则与免责</h3>
      <ul className="rules-list card-glass">
        {RULES.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>

      <div className="guide-actions">
        <Link to="/" className="btn btn-primary">
          前往仪表盘
        </Link>
        <Link to="/backtest" className="btn btn-secondary">
          打开回测中心
        </Link>
      </div>
    </div>
  );
}
