import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Dashboard as DashboardData, TaskStatus } from "../api";
import DataSourceBadge from "../components/DataSourceBadge";
import DataSourceSelector from "../components/DataSourceSelector";
import { pctClass, formatPct, STAGE_LABEL, ENV_CONCLUSION_LABEL } from "../utils";

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanTask, setScanTask] = useState<TaskStatus | null>(null);
  const [error, setError] = useState("");
  const [scanDate, setScanDate] = useState("");
  const [jqRangeLabel, setJqRangeLabel] = useState("");
  const [jqMin, setJqMin] = useState("");
  const [jqMax, setJqMax] = useState("");

  const load = () => {
    setLoading(true);
    api
      .dashboard()
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  const refreshScanMeta = () => {
    api.systemStatus().then((s) => {
      if (s.default_scan_date) setScanDate(s.default_scan_date);
      if (s.jq_data_range) {
        setJqRangeLabel(s.jq_data_range.label);
        setJqMin(s.jq_data_range.start);
        setJqMax(s.jq_data_range.end);
      } else {
        setJqRangeLabel("");
        setJqMin("");
        setJqMax("");
      }
    });
  };

  useEffect(() => {
    load();
    refreshScanMeta();
    const onDs = () => {
      refreshScanMeta();
      load();
    };
    window.addEventListener("themeradar:data-source-changed", onDs);
    const poll = () => api.scanTaskStatus().then(setScanTask).catch(() => {});
    poll();
    const t = setInterval(poll, 2000);
    return () => {
      clearInterval(t);
      window.removeEventListener("themeradar:data-source-changed", onDs);
    };
  }, []);

  const scanRunning = scanTask?.status === "running";

  const runScan = async () => {
    setError("");
    try {
      await api.scanLatest(scanDate || undefined);
      api.scanTaskStatus().then(setScanTask);
    } catch (e) {
      setError(e instanceof Error ? e.message : "扫描失败");
    }
  };

  if (loading) return <div className="loading">加载中…</div>;
  if (error && !data?.top_sectors?.length) return <div className="error">{error}</div>;

  const env = data?.market_env;

  return (
    <>
      <DataSourceSelector />
      <DataSourceBadge />

      <div className="card-glass" style={{ marginBottom: "1rem", padding: "0.85rem 1.1rem" }}>
        <div className="form-row" style={{ alignItems: "flex-end", marginBottom: 0 }}>
          <div className="form-group">
            <label>扫描交易日</label>
            <input
              type="date"
              value={scanDate}
              min={jqMin || undefined}
              max={jqMax || undefined}
              onChange={(e) => setScanDate(e.target.value)}
              disabled={scanRunning}
            />
          </div>
          {jqRangeLabel && (
            <span style={{ fontSize: "0.8rem", color: "var(--muted)", paddingBottom: "0.5rem" }}>
              聚宽权限：{jqRangeLabel}
            </span>
          )}
        </div>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h2 className="page-title" style={{ marginBottom: 0 }}>
          仪表盘
          {data?.trade_date && (
            <span style={{ fontSize: "0.9rem", color: "var(--muted)", fontWeight: 400, marginLeft: "0.75rem" }}>
              {data.trade_date}
            </span>
          )}
        </h2>
        <button className="btn btn-primary" onClick={runScan} disabled={scanRunning || !scanDate}>
          {scanRunning ? "后台扫描中…" : "执行收盘扫描"}
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
          <p style={{ color: "var(--muted)" }}>
            暂无数据，请选择权限内交易日并点击「执行收盘扫描」
          </p>
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
