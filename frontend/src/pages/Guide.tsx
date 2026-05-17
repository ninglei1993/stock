import { Link } from "react-router-dom";

const STEPS = [
  {
    n: 1,
    title: "执行收盘扫描",
    where: "仪表盘",
    desc: "每个交易日收盘后（约 15:10 后），点击「执行收盘扫描」。系统拉取板块行情与资金流，计算五维评分与四阶段。",
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
    desc: "按强度分排序。萌芽=可观察埋伏；发酵=鱼身持有；高潮/衰退=考虑撤退。板块列表可查看全部已评分板块，点击详情进入五维拆解。",
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
  "数据默认演示模式（DEMO）；配置聚宽 JQData 后可接实盘数据。",
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

      <h3 className="section-title">五维评分说明</h3>
      <div className="dim-grid">
        {[
          { w: "25%", name: "持续性", d: "近3日涨幅分位、抗跌" },
          { w: "30%", name: "资金", d: "主力连续净流入" },
          { w: "25%", name: "广度", d: "涨停/大阳/上涨家数" },
          { w: "15%", name: "龙头", d: "连板高度与龙头强度" },
          { w: "5%", name: "相对强度", d: "相对沪深300超额" },
        ].map((d) => (
          <div key={d.name} className="dim-card card-glass">
            <div className="dim-weight">{d.w}</div>
            <div className="dim-name">{d.name}</div>
            <div className="dim-desc">{d.d}</div>
          </div>
        ))}
      </div>

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
