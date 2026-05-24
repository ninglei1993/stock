import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Dashboard as DashboardData } from "../api";
import { pctClass, formatPct, STAGE_LABEL, ENV_CONCLUSION_LABEL } from "../utils";

function formatWanYi(v: number): string {
  if (!Number.isFinite(v)) return "0.00";
  const yi = v / 10000;
  if (Math.abs(yi) >= 1) return `${yi.toFixed(2)}万亿`;
  return `${v.toFixed(0)}亿`;
}

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    api
      .dashboard()
      .then((d) => setData(d))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !data) {
    return <div className="loading">加载中…</div>;
  }

  const env = data?.market_env;
  const marketOverview = data?.market_overview;
  const displayDate = data?.trade_date;
  const indices = data?.indices || [];
  const hasMarketData = indices.length > 0 || !!marketOverview;

  const dist = marketOverview?.distribution;

  const alignedBars = dist
    ? [
        { label: "跌停", count: dist.down_limit, color: "#22c55e" },
        { label: "<-7%", count: dist.neg_7_plus, color: "#22c55e" },
        { label: "-7~-5%", count: dist.neg_7_5, color: "#22c55e" },
        { label: "-5~-3%", count: dist.neg_5_3, color: "#22c55e" },
        { label: "-3~0%", count: dist.neg_3_0, color: "#22c55e" },
        { label: "平", count: dist.flat, color: "#94a3b8" },
        { label: "0~3%", count: dist.pos_0_3, color: "#ef4444" },
        { label: "3~5%", count: dist.pos_3_5, color: "#ef4444" },
        { label: "5~7%", count: dist.pos_5_7, color: "#ef4444" },
        { label: "≥7%", count: dist.pos_7_plus, color: "#ef4444" },
        { label: "涨停", count: dist.up_limit, color: "#ef4444" },
      ]
    : [];

  const maxCount = alignedBars.length ? Math.max(...alignedBars.map((b) => b.count)) : 1;

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h2 className="page-title" style={{ marginBottom: 0 }}>
          仪表盘
          {displayDate && (
            <span style={{ fontSize: "0.9rem", color: "var(--muted)", fontWeight: 400, marginLeft: "0.75rem" }}>
              {displayDate}
            </span>
          )}
        </h2>
        {env && (
          <span className={`env-conclusion ${env.conclusion}`}>
            {ENV_CONCLUSION_LABEL[env.conclusion] || env.conclusion}
          </span>
        )}
      </div>

      {error && <p className="error" style={{ marginBottom: "1rem" }}>{error}</p>}

      {!hasMarketData && !env && !error && (
        <div className="card-glass" style={{ padding: "2rem", textAlign: "center" }}>
          <p style={{ color: "var(--muted)", fontSize: "1rem" }}>
            暂无可展示的大盘数据，请稍后刷新重试
          </p>
        </div>
      )}

      {/* 指数卡片 */}
      {indices.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "0.75rem", marginBottom: "1rem" }}>
          {indices.map((idx) => (
            <div
              key={idx.code}
              className="card-glass"
              style={{
                padding: "1rem 1.1rem",
                textAlign: "center",
                borderRadius: "12px",
                background: "linear-gradient(180deg, #fff7f7 0%, #fff1f1 100%)",
                border: "1px solid #ffdcdc",
                boxShadow: "0 8px 20px rgba(239,68,68,0.08)",
              }}
            >
              <div style={{ fontSize: "1.35rem", color: "#111827", fontWeight: 700, marginBottom: "0.35rem" }}>{idx.name}</div>
              <div
                style={{
                  fontSize: "3rem",
                  fontWeight: 700,
                  lineHeight: 1.2,
                  color: idx.pct_change > 0 ? "#ef4444" : idx.pct_change < 0 ? "#16a34a" : "#111827",
                }}
              >
                {idx.close.toFixed(2)}
              </div>
              <div
                style={{
                  fontSize: "1.35rem",
                  marginTop: "0.3rem",
                  color: idx.pct_change > 0 ? "#ef4444" : idx.pct_change < 0 ? "#16a34a" : "#374151",
                  fontWeight: 600,
                }}
              >
                {idx.pct_change > 0 ? "+" : ""}
                {idx.point_change.toFixed(2)} {formatPct(idx.pct_change)}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 市场总览 */}
      {(env || marketOverview) && (
        <div
          className="card-glass"
          style={{
            padding: "1rem 1.1rem",
            marginBottom: "1rem",
            background: "linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)",
            border: "1px solid #e2e8f0",
          }}
        >
          <div style={{ display: "flex", alignItems: "baseline", gap: "0.9rem", marginBottom: "0.9rem", flexWrap: "wrap" }}>
            <span style={{ fontSize: "2rem", fontWeight: 700, color: "#111827" }}>市场总览</span>
            {marketOverview && (
              <>
                <span style={{ fontSize: "1.6rem", color: "#374151", fontWeight: 500 }}>
                  总成交额
                  <span style={{ marginLeft: "0.25rem", color: "#111827", fontWeight: 700 }}>
                    {formatWanYi(marketOverview.total_turnover_yi || 0)}
                  </span>
                </span>
                <span style={{ fontSize: "1.6rem", color: "#374151", fontWeight: 500 }}>
                  较昨日此时
                  <span
                    style={{
                      color: (marketOverview.turnover_delta_yi || 0) > 0 ? "#ef4444" : (marketOverview.turnover_delta_yi || 0) < 0 ? "#16a34a" : "#6b7280",
                      fontWeight: 700,
                      marginLeft: "0.25rem",
                    }}
                  >
                    {(marketOverview.turnover_delta_yi || 0) > 0 ? "+" : ""}
                    {formatWanYi(marketOverview.turnover_delta_yi || 0)}
                  </span>
                </span>
              </>
            )}
          </div>

          {/* 涨跌分布柱状图 */}
          {dist && (
            <div style={{ marginBottom: "0.75rem" }}>
              <div style={{ display: "flex", alignItems: "flex-end", gap: "0.35rem", height: "110px", paddingBottom: "0.5rem" }}>
                {alignedBars.map((bar) => {
                  const h = maxCount > 0 ? Math.max((bar.count / maxCount) * 80, 4) : 4;
                  return (
                    <div key={bar.label} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: "0.25rem" }}>
                      <span style={{ fontSize: "0.65rem", color: bar.color, fontWeight: 600 }}>{bar.count > 0 ? bar.count : ""}</span>
                      <div
                        style={{
                          width: "100%",
                          height: `${h}px`,
                          background: bar.color,
                          borderRadius: "2px 2px 0 0",
                          opacity: 0.9,
                          minHeight: bar.count > 0 ? "4px" : "1px",
                        }}
                      />
                      <span style={{ fontSize: "0.65rem", color: "var(--muted)", whiteSpace: "nowrap" }}>{bar.label}</span>
                    </div>
                  );
                })}
              </div>
              {/* 分割线 */}
              <div style={{ height: "1px", background: "var(--line)", margin: "0.5rem 0" }} />
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.85rem" }}>
                <span style={{ color: "var(--down)" }}>
                  下跌 {marketOverview?.down_count ?? 0} 家
                </span>
                <span style={{ color: "var(--up)" }}>
                  上涨 {marketOverview?.up_count ?? 0} 家
                </span>
              </div>
            </div>
          )}

          {/* 环境分一行 */}
          {env && (
            <div style={{ marginTop: "0.55rem", fontSize: "0.78rem", color: "var(--muted)" }}>
              涨停 {env.limit_up_count} 家 · 涨跌比 {(env.up_down_ratio * 100).toFixed(0)}% · 沪深300{" "}
              <span className={pctClass(env.index_pct)}>{formatPct(env.index_pct)}</span> · 环境分{" "}
              <span style={{ fontFamily: "JetBrains Mono" }}>{env.env_score.toFixed(0)}</span>
            </div>
          )}
        </div>
      )}

      {/* Top 板块 */}
      {data && data.top_sectors && data.top_sectors.length > 0 && (
        <>
          <h3 className="section-title">主线板块</h3>
          <div className="sector-grid">
            {data.top_sectors.map((s) => (
              <Link
                key={s.sector_code}
                to={`/sectors/${encodeURIComponent(s.sector_code)}${displayDate ? `?trade_date=${displayDate}` : ""}`}
                style={{ textDecoration: "none", color: "inherit" }}
              >
                <div className="sector-card">
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "0.5rem" }}>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: "0.95rem" }}>{s.sector_name}</div>
                      <div style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "0.15rem" }}>
                        {s.leader_stock_name || s.leader_stock || "—"}
                        {s.leader_streak ? ` ${s.leader_streak}板` : ""}
                      </div>
                    </div>
                    <span className={`stage-badge stage-${s.stage}`}>{STAGE_LABEL[s.stage] || s.stage}</span>
                  </div>
                  <div style={{ display: "flex", gap: "1rem", alignItems: "baseline" }}>
                    <span className="score-big">{s.total_score.toFixed(1)}</span>
                    {s.pct_change !== undefined && s.pct_change !== null && (
                      <span className={pctClass(s.pct_change)} style={{ fontSize: "0.9rem", fontWeight: 600 }}>
                        {formatPct(s.pct_change)}
                      </span>
                    )}
                  </div>
                </div>
              </Link>
            ))}
          </div>
        </>
      )}
    </>
  );
}
