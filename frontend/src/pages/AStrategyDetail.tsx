import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, SectorScore } from "../api";

const RULES = [
  {
    key: "trend_ma20_up",
    title: "趋势条件（站上MA20且MA20向上）",
    threshold: "close > MA20 且 MA20 > MA20_prev",
    desc: "板块指数收盘价必须站在20日均线之上，且20日均线本身处于向上趋势。",
    example: {
      inputs: {
        close: 1250.30,
        ma20: 1200.50,
        ma20_prev: 1198.20,
      },
      steps: [
        "收盘价 1250.30 > MA20 1200.50 → 满足",
        "MA20 1200.50 > MA20_prev 1198.20 → 满足",
      ],
      result: "通过",
      passed: true,
    },
  },
  {
    key: "pct_20d_tier",
    title: "20日涨幅分级",
    threshold: "20日涨幅 >= 10%（>= 18% 为顶级主线）",
    desc: "衡量板块近20个交易日的累计涨幅，判断其是否具备主线级别的持续性强度。",
    example: {
      inputs: {
        close_today: 1380.00,
        close_20d_ago: 1198.26,
      },
      steps: [
        "pct_20d = (1380.00 / 1198.26 - 1) × 100 = 15.16%",
        "15.16% >= 10% 且 < 18% → 次级主线",
      ],
      result: "通过（次级主线）",
      passed: true,
    },
  },
  {
    key: "volume_heat",
    title: "量能持续性",
    threshold: "vol_ratio_5d >= 1.6 且 8日市场占比 >= 4.5%",
    desc: "近5日成交量相对前5日均值的比率需大于1.6，且近8日板块成交额占全市场比例均值不低于4.5%。",
    example: {
      inputs: {
        vol_last5_avg: 8500,
        vol_prev5_avg: 4500,
        share_8d_avg: 5.2,
      },
      steps: [
        "vol_ratio_5d = 8500 / 4500 = 1.89 >= 1.6 → 满足",
        "share_8d_avg = 5.2% >= 4.5% → 满足",
      ],
      result: "通过",
      passed: true,
    },
  },
  {
    key: "capital_inflow",
    title: "资金连续流入",
    threshold: "主力连续6日净流入 且 北向5日净流入 >= 2亿",
    desc: "主力资金需连续6个交易日净流入；北向资金近5日净流入不低于2亿元（可人工录入修正）。",
    example: {
      inputs: {
        main_inflow_streak: 7,
        northbound_5d_yi: 3.5,
      },
      steps: [
        "主力连续净流入 7 日 >= 6 日 → 满足",
        "北向 5 日净流入 3.5 亿 >= 2 亿 → 满足",
      ],
      result: "通过",
      passed: true,
    },
  },
  {
    key: "money_effect",
    title: "板块赚钱效应",
    threshold: "上涨占比 >= 65%、最高连板 >= 3、涨停家数 >= 5",
    desc: "成分股中上涨比例需达到65%以上，且板块内存在至少3连板的龙头股，涨停家数不少于5家。",
    example: {
      inputs: {
        up_ratio: 0.72,
        max_limit_up_streak: 4,
        limit_up_count: 8,
      },
      steps: [
        "上涨占比 72% >= 65% → 满足",
        "最高连板 4 天 >= 3 天 → 满足",
        "涨停家数 8 家 >= 5 家 → 满足",
      ],
      result: "通过",
      passed: true,
    },
  },
  {
    key: "no_negative_news",
    title: "竞价与基本面无压制",
    threshold: "竞价门槛通过 且 无监管利空/集体减持/政策降温",
    desc: "开盘集合竞价未出现明显压制信号，且无监管问询、大规模减持预告、政策降温等负面消息（可人工录入修正）。",
    example: {
      inputs: {
        auction_passed: true,
        negative_news: false,
      },
      steps: [
        "auction_passed = true → 满足",
        "negative_news = false → 满足",
      ],
      result: "通过",
      passed: true,
    },
  },
];

const CONFIRM_EXIT = {
  confirm: [
    "6条主线规则全部通过（+1）",
    "MA20 处于向上趋势（+1）",
    "板块最高连板 >= 5 天（+1）",
    "主力连续净流入 >= 10 天（+1）",
    "累计确认信号 >= 4 → 状态：已确立（confirmed）",
  ],
  exit: [
    "20日涨幅 <= -12%（+1）",
    "MA20 不再向上（+1）",
    "主力连续净流出 >= 3 天（+1）",
    "最高连板 < 2 天（+1）",
    "涨停家数 < 2 家（+1）",
    "累计退出信号 >= 2 → 状态：失效（exit）",
  ],
};

function tierLabel(tier?: string): string {
  if (tier === "top") return "顶级主线";
  if (tier === "secondary") return "次级主线";
  return "轮动观察";
}

export default function AStrategyDetail() {
  const [rows, setRows] = useState<SectorScore[]>([]);
  const [tradeDate, setTradeDate] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const [list, status] = await Promise.all([
        api.aStrategyMainLines(undefined, true),
        api.systemStatus(),
      ]);
      setRows(list.sectors || []);
      setTradeDate((list.trade_date || status.default_scan_date || "") as string);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const mainLines = rows.filter((s) => s.is_main_line);

  return (
    <>
      <h2 className="page-title">A策略 · 主线筛选</h2>
      {tradeDate && (
        <p className="page-subtitle">
          交易日：{tradeDate} · 主线板块 {mainLines.length} 个
        </p>
      )}
      {error && <p className="error">{error}</p>}

      {/* 策略概述 */}
      <div className="card-glass" style={{ marginBottom: "1rem" }}>
        <h3 style={{ fontSize: "1rem", marginBottom: "0.6rem" }}>策略概述</h3>
        <p style={{ fontSize: "0.88rem", color: "var(--muted)", lineHeight: 1.7 }}>
          A策略采用<strong>硬性规则通过/不通过</strong>机制，而非传统打分制。板块必须同时满足以下6大条件，方可被认定为<strong>正式主线</strong>。
          任何一条未通过即被过滤为轮动观察。该策略强调<strong>趋势、量能、资金、赚钱效应与基本面安全</strong>五位一体。
        </p>
        <div style={{ marginTop: "0.75rem", display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <span className="hint-pill">硬性规则：6条全过 = 主线</span>
          <span className="hint-pill">通过数 ≥ 4 = 萌芽（sprout）</span>
          <span className="hint-pill">20日涨幅 ≥ 18% = 顶级主线</span>
          <span className="hint-pill">20日涨幅 ≥ 10% = 次级主线</span>
        </div>
      </div>

      {/* 六大规则 */}
      <div style={{ marginBottom: "1rem" }}>
        <h3 className="section-title">六大主线规则</h3>
        <div style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
          {RULES.map((rule, idx) => (
            <div key={rule.key} className="card-glass" style={{ padding: "1rem 1.1rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", marginBottom: "0.5rem" }}>
                <div
                  style={{
                    width: "28px",
                    height: "28px",
                    borderRadius: "8px",
                    background: "linear-gradient(135deg, #3b82f6, #1d4ed8)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: "0.8rem",
                    fontWeight: 700,
                    flexShrink: 0,
                  }}
                >
                  {idx + 1}
                </div>
                <div style={{ fontWeight: 600, fontSize: "0.95rem" }}>{rule.title}</div>
              </div>
              <div style={{ fontSize: "0.82rem", color: "var(--muted)", marginBottom: "0.6rem", lineHeight: 1.6 }}>
                {rule.desc}
              </div>
              <div
                style={{
                  background: "rgba(0,0,0,0.2)",
                  borderRadius: "10px",
                  padding: "0.75rem 1rem",
                  border: "1px solid var(--border)",
                  marginBottom: "0.6rem",
                }}
              >
                <div style={{ fontSize: "0.78rem", color: "var(--muted)", marginBottom: "0.35rem" }}>阈值</div>
                <div style={{ fontSize: "0.85rem", fontWeight: 500 }}>{rule.threshold}</div>
              </div>
              <div
                style={{
                  background: "rgba(0,0,0,0.15)",
                  borderRadius: "10px",
                  padding: "0.75rem 1rem",
                  border: "1px solid var(--border)",
                }}
              >
                <div style={{ fontSize: "0.78rem", color: "var(--muted)", marginBottom: "0.35rem" }}>计算示例</div>
                <div style={{ fontSize: "0.82rem", lineHeight: 1.7, color: "var(--text)" }}>
                  {Object.entries(rule.example.inputs).map(([k, v]) => (
                    <div key={k}>
                      {k} = <span style={{ fontFamily: "JetBrains Mono, monospace" }}>{String(v)}</span>
                    </div>
                  ))}
                  <div style={{ marginTop: "0.35rem", color: "var(--muted)" }}>
                    {rule.example.steps.map((s, i) => (
                      <div key={i}>· {s}</div>
                    ))}
                  </div>
                  <div style={{ marginTop: "0.35rem", fontWeight: 600, color: rule.example.passed ? "var(--down)" : "var(--up)" }}>
                    结果：{rule.example.result}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 确认与退出信号 */}
      <div className="card-glass" style={{ marginBottom: "1rem" }}>
        <h3 style={{ fontSize: "1rem", marginBottom: "0.6rem" }}>确认与退出信号</h3>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
          <div>
            <div style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--down)", marginBottom: "0.4rem" }}>确立信号（confirmed）</div>
            <ul style={{ fontSize: "0.82rem", color: "var(--muted)", lineHeight: 1.7, paddingLeft: "1.1rem" }}>
              {CONFIRM_EXIT.confirm.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ul>
          </div>
          <div>
            <div style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--up)", marginBottom: "0.4rem" }}>退出信号（exit）</div>
            <ul style={{ fontSize: "0.82rem", color: "var(--muted)", lineHeight: 1.7, paddingLeft: "1.1rem" }}>
              {CONFIRM_EXIT.exit.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      {/* 阶段判断逻辑 */}
      <div className="card-glass" style={{ marginBottom: "1rem" }}>
        <h3 style={{ fontSize: "1rem", marginBottom: "0.6rem" }}>阶段判断逻辑（状态机）</h3>
        <p style={{ fontSize: "0.88rem", color: "var(--muted)", lineHeight: 1.7, marginBottom: "0.75rem" }}>
          A策略通过六大规则通过数量与退出信号，自动确定每个板块当前所处的阶段。判断优先级如下：
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
          {[
            { condition: "退出信号 ≥ 2 → exit_state = exit", stage: "decay", label: "衰退", desc: "触发退出机制，该板块主线行情已结束，建议清仓" },
            { condition: "6条规则全部通过 + 20日涨幅 ≥ 18%", stage: "climax", label: "高潮", desc: "顶级主线确立，处于高潮阶段，需警惕见顶风险" },
            { condition: "6条规则全部通过 + 20日涨幅 10%~18%", stage: "ferment", label: "发酵", desc: "次级主线确立，正处于发酵上升期，是鱼身阶段" },
            { condition: "通过数 ≥ 4（但未全部通过）", stage: "sprout", label: "萌芽", desc: "初步具备主线特征但尚未完全确立，可轻仓试探" },
            { condition: "通过数 < 4", stage: "dormant", label: "沉寂", desc: "不具备主线特征，建议观望不参与" },
          ].map((item) => (
            <div
              key={item.stage}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: "0.75rem",
                padding: "0.65rem 0.85rem",
                background: "rgba(0,0,0,0.15)",
                borderRadius: "10px",
                border: "1px solid var(--border)",
              }}
            >
              <span className={`stage-badge stage-${item.stage}`} style={{ flexShrink: 0, marginTop: "0.15rem" }}>
                {item.label}
              </span>
              <div>
                <div style={{ fontSize: "0.85rem", fontWeight: 600 }}>{item.condition}</div>
                <div style={{ fontSize: "0.78rem", color: "var(--muted)", marginTop: "0.2rem" }}>{item.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 当前主线列表 */}
      {mainLines.length > 0 && (
        <>
          <h3 className="section-title">当前主线</h3>
          <div className="card-glass" style={{ padding: "0.75rem 1rem" }}>
            <table>
              <thead>
                <tr>
                  <th>板块</th>
                  <th>分级</th>
                  <th>状态</th>
                  <th>确认/失效</th>
                </tr>
              </thead>
              <tbody>
                {mainLines.map((r) => (
                  <tr key={r.sector_code}>
                    <td>
                      <Link to={`/sectors/${encodeURIComponent(r.sector_code)}?trade_date=${tradeDate}`}>
                        {r.sector_name}
                      </Link>
                    </td>
                    <td>{tierLabel(r.main_line_tier)}</td>
                    <td>
                      <span className="text-down">通过</span>
                    </td>
                    <td>
                      {(r.confirm_state || "pending") === "confirmed" ? "已确立" : "待确认"} /{" "}
                      {(r.exit_state || "normal") === "exit" ? "失效" : "正常"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {loading && rows.length === 0 && <div className="loading">加载中…</div>}
    </>
  );
}
