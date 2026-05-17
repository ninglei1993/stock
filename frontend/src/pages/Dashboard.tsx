import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Dashboard as DashboardData } from "../api";
import { pctClass, formatPct, STAGE_LABEL, ENV_CONCLUSION_LABEL } from "../utils";

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState("");

  const load = () => {
    setLoading(true);
    api
      .dashboard()
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const runScan = async () => {
    setScanning(true);
    try {
      await api.scanLatest();
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "扫描失败");
    } finally {
      setScanning(false);
    }
  };

  if (loading) return <div className="loading">加载中…</div>;
  if (error && !data?.top_sectors?.length) return <div className="error">{error}</div>;

  const env = data?.market_env;

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h2 className="page-title" style={{ marginBottom: 0 }}>
          仪表盘
          {data?.trade_date && (
            <span style={{ fontSize: "0.9rem", color: "var(--muted)", fontWeight: 400, marginLeft: "0.75rem" }}>
              {data.trade_date}
            </span>
          )}
        </h2>
        <button className="btn btn-primary" onClick={runScan} disabled={scanning}>
          {scanning ? "扫描中…" : "执行收盘扫描"}
        </button>
      </div>

      {env && (
        <div className="card-glass env-bar">
          <div>
            <div style={{ fontSize: "0.8rem", color: "var(--muted)" }}>大盘环境</div>
            <div className="env-score">{env.env_score.toFixed(0)}</div>
          </div>
          <span className={`env-conclusion ${env.conclusion}`}>
            {ENV_CONCLUSION_LABEL[env.conclusion] || env.conclusion}
          </span>
          <div>
            <div style={{ color: "var(--muted)", fontSize: "0.85rem" }}>涨停家数</div>
            <div style={{ fontFamily: "JetBrains Mono" }}>{env.limit_up_count}</div>
          </div>
          <div>
            <div style={{ color: "var(--muted)", fontSize: "0.85rem" }}>涨跌比</div>
            <div style={{ fontFamily: "JetBrains Mono" }}>{(env.up_down_ratio * 100).toFixed(0)}%</div>
          </div>
          <div>
            <div style={{ color: "var(--muted)", fontSize: "0.85rem" }}>沪深300</div>
            <div className={pctClass(env.index_pct)} style={{ fontFamily: "JetBrains Mono" }}>
              {formatPct(env.index_pct)}
            </div>
          </div>
        </div>
      )}

      <h3 style={{ marginBottom: "1rem", fontSize: "1rem", color: "var(--muted)" }}>Top 5 主线</h3>
      {!data?.top_sectors?.length ? (
        <div className="card-glass">
          <p style={{ color: "var(--muted)" }}>暂无数据，请点击「执行收盘扫描」</p>
        </div>
      ) : (
        <div className="sector-grid">
          {data.top_sectors.map((s) => (
            <Link key={s.sector_code} to={`/sectors/${s.sector_code}`} style={{ textDecoration: "none", color: "inherit" }}>
              <div className="sector-card">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div>
                    <div style={{ fontWeight: 600 }}>{s.sector_name}</div>
                    <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>{s.sector_code}</div>
                  </div>
                  <span className={`stage-badge stage-${s.stage}`}>{STAGE_LABEL[s.stage] || s.stage}</span>
                </div>
                <div className="score-big" style={{ margin: "0.75rem 0" }}>
                  {s.total_score.toFixed(0)}
                  <span style={{ fontSize: "0.85rem", color: "var(--muted)", fontWeight: 400 }}> 分</span>
                </div>
                <div style={{ fontSize: "0.8rem", color: "var(--muted)", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.25rem" }}>
                  <span>持续 {s.persistence_score.toFixed(0)}</span>
                  <span>资金 {s.capital_score.toFixed(0)}</span>
                  <span>广度 {s.breadth_score.toFixed(0)}</span>
                  <span>龙头 {s.leader_score.toFixed(0)}</span>
                </div>
                {s.leader_stock && (
                  <div style={{ marginTop: "0.5rem", fontSize: "0.75rem", fontFamily: "JetBrains Mono" }}>
                    龙头 {s.leader_stock}
                    {s.leader_streak ? ` ${s.leader_streak}连板` : ""}
                  </div>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
