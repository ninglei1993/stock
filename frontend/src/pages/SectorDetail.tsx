import { useEffect, useState } from "react";
import { useParams, Link, useSearchParams } from "react-router-dom";
import { api, SectorDetail as SectorDetailType } from "../api";
import { STAGE_LABEL, POSITION_LABEL, SCORE_DIM_LABEL, pctClass, formatPct } from "../utils";

export default function SectorDetail() {
  const { code } = useParams<{ code: string }>();
  const [searchParams] = useSearchParams();
  const tradeDate = searchParams.get("trade_date") || undefined;
  const [detail, setDetail] = useState<SectorDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!code) return;
    setLoading(true);
    api
      .sector(code, tradeDate)
      .then(setDetail)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [code, tradeDate]);

  if (loading) return <div className="loading">加载中…</div>;
  if (error) return <div className="error">{error}</div>;
  if (!detail) return null;

  const dims = detail.score_dimensions?.length
    ? detail.score_dimensions
    : Object.entries(detail.scores).map(([key, score]) => ({
        key,
        label: SCORE_DIM_LABEL[key] || key,
        weight_pct: 20,
        score,
        description: "",
      }));

  return (
    <div className="detail-page">
      <div className="detail-header">
        <Link to="/" className="back-link">
          ← 返回仪表盘
        </Link>
        <div className="detail-title-row">
          <h2 className="page-title" style={{ marginBottom: 0 }}>
            {detail.sector_name}
          </h2>
          <span className={`stage-badge stage-${detail.stage}`}>
            {STAGE_LABEL[detail.stage]}
          </span>
          <span className="hint-pill">
            {POSITION_LABEL[detail.position_hint] || detail.position_hint}
          </span>
        </div>
        <p className="detail-meta">
          {detail.sector_code} · {detail.trade_date} · 综合强度{" "}
          <strong>{detail.total_score.toFixed(0)}</strong> 分
          {detail.inflow_days > 0 && ` · 资金连续流入 ${detail.inflow_days} 日`}
        </p>
      </div>

      <div className="metric-grid">
        <div className="metric-card">
          <div className="metric-label">涨停家数</div>
          <div className="metric-value">{detail.limit_up_count}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">大阳线 (&gt;7%)</div>
          <div className="metric-value">{detail.big_yang_count}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">主力净流入</div>
          <div className={`metric-value ${detail.net_inflow_yi >= 0 ? "text-up" : "text-down"}`}>
            {detail.net_inflow_yi >= 0 ? "+" : ""}
            {detail.net_inflow_yi.toFixed(2)} 亿
          </div>
          <div style={{ fontSize: "0.72rem", color: "var(--muted)", marginTop: "0.25rem" }}>
            约 {detail.net_inflow_main.toFixed(0)} 万元
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">上涨占比</div>
          <div className="metric-value">
            {detail.up_count}/{detail.total_count}
            <span style={{ fontSize: "0.85rem", color: "var(--muted)", marginLeft: "0.35rem" }}>
              ({(detail.up_ratio * 100).toFixed(0)}%)
            </span>
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">炸板率</div>
          <div className={`metric-value ${detail.blow_up_rate > 0.3 ? "text-up" : ""}`}>
            {(detail.blow_up_rate * 100).toFixed(1)}%
          </div>
        </div>
      </div>

      {detail.leader && (
        <div className="leader-card card-glass">
          <div>
            <div className="metric-label">板块龙头</div>
            <div style={{ fontFamily: "JetBrains Mono", fontSize: "1.1rem", fontWeight: 600, marginTop: "0.35rem" }}>
              {detail.leader.stock_code}
            </div>
            {(detail.leader as { stock_name?: string }).stock_name && (
              <div style={{ fontSize: "0.9rem", marginTop: "0.25rem" }}>
                {(detail.leader as { stock_name?: string }).stock_name}
              </div>
            )}
          </div>
          <div style={{ textAlign: "right" }}>
            <div className="metric-label">连板 / 涨幅</div>
            <div style={{ marginTop: "0.35rem" }}>
              <span style={{ marginRight: "1rem" }}>{detail.leader.streak} 连板</span>
              <span className={pctClass(detail.leader.pct_change)}>
                {formatPct(detail.leader.pct_change)}
              </span>
            </div>
          </div>
        </div>
      )}

      <div className="card-glass score-ring-wrap">
        <div className="score-ring" style={{ "--pct": detail.total_score } as React.CSSProperties}>
          <div className="score-ring-inner">
            <div className="score-ring-num">{detail.total_score.toFixed(0)}</div>
            <div className="score-ring-label">综合分</div>
          </div>
        </div>
        <div className="dim-bars">
          <h3 style={{ fontSize: "0.95rem", marginBottom: "1rem" }}>五维评分详解</h3>
          {dims.map((d) => (
            <div key={d.key} className="dim-row">
              <div className="dim-row-header">
                <span>
                  {d.label} <span style={{ color: "var(--muted)" }}>({d.weight_pct}%)</span>
                </span>
                <span className={d.score >= 70 ? "text-up" : d.score >= 50 ? "" : "text-down"}>
                  {d.score.toFixed(0)} 分
                </span>
              </div>
              <div className="dim-row-bar">
                <div className="dim-row-fill" style={{ width: `${Math.min(100, d.score)}%` }} />
              </div>
              {d.description && <div className="dim-row-desc">{d.description}</div>}
            </div>
          ))}
        </div>
      </div>

      {detail.flow_history && detail.flow_history.length > 0 && (
        <div className="card-glass" style={{ marginBottom: "1rem" }}>
          <h3 style={{ fontSize: "0.95rem", marginBottom: "0.75rem" }}>主力资金净流入（按日）</h3>
          <p style={{ fontSize: "0.8rem", color: "var(--muted)", marginBottom: "0.75rem" }}>
            板块成分股主力净流入合计，单位：万元 / 亿元（正为流入，负为流出）
          </p>
          <table>
            <thead>
              <tr>
                <th>日期</th>
                <th>净流入（万元）</th>
                <th>净流入（亿元）</th>
              </tr>
            </thead>
            <tbody>
              {detail.flow_history.map((f) => (
                <tr key={f.trade_date}>
                  <td>{f.trade_date}</td>
                  <td className={f.net_inflow_wan >= 0 ? "text-up" : "text-down"}>
                    {f.net_inflow_wan >= 0 ? "+" : ""}
                    {f.net_inflow_wan.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </td>
                  <td className={f.net_inflow_yi >= 0 ? "text-up" : "text-down"}>
                    {f.net_inflow_yi >= 0 ? "+" : ""}
                    {f.net_inflow_yi.toFixed(4)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {detail.history.length > 0 && (
        <div className="card-glass" style={{ marginBottom: "1rem" }}>
          <h3 style={{ fontSize: "0.95rem", marginBottom: "0.75rem" }}>近阶段变化</h3>
          <table>
            <thead>
              <tr>
                <th>日期</th>
                <th>强度</th>
                <th>阶段</th>
              </tr>
            </thead>
            <tbody>
              {detail.history.map((h) => (
                <tr key={h.trade_date}>
                  <td>{h.trade_date}</td>
                  <td>{h.total_score.toFixed(0)}</td>
                  <td>
                    <span className={`stage-badge stage-${h.stage}`}>
                      {STAGE_LABEL[h.stage] || h.stage}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="card-glass">
        <h3 style={{ fontSize: "0.95rem", marginBottom: "0.35rem" }}>
          成分股（按 {detail.trade_date} 涨跌幅排序）
        </h3>
        {(detail.pct_display_days?.length ?? 0) > 1 && (
          <p style={{ fontSize: "0.78rem", color: "var(--muted)", marginBottom: "0.75rem" }}>
            涨跌幅列为扫描区间内最近 {detail.pct_display_days!.length} 个交易日（
            {detail.pct_display_days![0]} ~{" "}
            {detail.pct_display_days![detail.pct_display_days!.length - 1]}）
          </p>
        )}
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>代码</th>
                <th>名称</th>
                {(detail.pct_display_days?.length
                  ? detail.pct_display_days
                  : [detail.trade_date]
                ).map((d) => (
                  <th key={d} title={`${d} 涨跌幅`}>
                    {d.slice(5)}
                  </th>
                ))}
                <th>涨停 ({detail.trade_date.slice(5)})</th>
                <th>连板</th>
                <th>成交额 ({detail.trade_date.slice(5)})</th>
              </tr>
            </thead>
            <tbody>
              {detail.stocks.map((s) => {
                const histMap = new Map(
                  (s.pct_history ?? []).map((h) => [h.trade_date, h.pct_change])
                );
                const cols = detail.pct_display_days?.length
                  ? detail.pct_display_days
                  : [detail.trade_date];
                return (
                  <tr key={s.stock_code}>
                    <td style={{ fontFamily: "JetBrains Mono" }}>{s.stock_code}</td>
                    <td>{s.stock_name || "—"}</td>
                    {cols.map((d) => {
                      const pct = histMap.get(d);
                      return (
                        <td key={d} className={pct != null ? pctClass(pct) : ""}>
                          {pct != null ? formatPct(pct) : "—"}
                        </td>
                      );
                    })}
                    <td>{s.is_limit_up ? <span className="text-up">涨停</span> : "—"}</td>
                    <td>{s.limit_up_streak > 0 ? `${s.limit_up_streak}板` : "—"}</td>
                    <td>{(s.money / 1e8).toFixed(2)} 亿</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
