import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Dashboard as DashboardData, TaskStatus } from "../api";
import SectorScanPicker from "../components/SectorScanPicker";
import { pctClass, formatPct, STAGE_LABEL, ENV_CONCLUSION_LABEL } from "../utils";

function formatYi(v: number): string {
  if (!Number.isFinite(v)) return "0.0";
  return v.toLocaleString("zh-CN", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanTask, setScanTask] = useState<TaskStatus | null>(null);
  const [error, setError] = useState("");
  const [scanStart, setScanStart] = useState("");
  const [scanEnd, setScanEnd] = useState("");
  const [viewDate, setViewDate] = useState("");
  const [jqRangeLabel, setJqRangeLabel] = useState("");
  const [jqMin, setJqMin] = useState("");
  const [jqMax, setJqMax] = useState("");
  const [maxStocksPerConcept, setMaxStocksPerConcept] = useState(0);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [clearing, setClearing] = useState(false);

  const load = useCallback((tradeDate?: string) => {
    setLoading(true);
    const td = tradeDate || viewDate || undefined;
    api
      .dashboard(td)
      .then((d) => {
        setData(d);
        if (d.trade_date) setViewDate(d.trade_date);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [viewDate]);

  const refreshScanMeta = (onlyIfEmpty = false) => {
    api.systemStatus().then((s) => {
      if (s.default_scan_end) {
        setScanEnd((prev) => (onlyIfEmpty && prev ? prev : s.default_scan_end!));
      }
      if (s.default_scan_start) {
        setScanStart((prev) => (onlyIfEmpty && prev ? prev : s.default_scan_start!));
      }
      if (s.default_scan_date && !viewDate) setViewDate(s.default_scan_date);
      if (s.ingest_max_stocks_per_concept != null) {
        setMaxStocksPerConcept(s.ingest_max_stocks_per_concept);
      }
      // 仅保留 Tushare 数据源，无需展示聚宽权限区间
      setJqRangeLabel("");
      setJqMin("");
      setJqMax("");
    });
  };

  useEffect(() => {
    load();
    refreshScanMeta(true);
    const onTask = (e: Event) => {
      const t = (e as CustomEvent<TaskStatus>).detail;
      if (t) setScanTask(t);
    };
    const onComplete = (e: Event) => {
      const t = (e as CustomEvent<TaskStatus>).detail;
      if (t?.status === "done" && t.trade_date) {
        setViewDate(t.trade_date);
        load(t.trade_date);
      }
    };
    window.addEventListener("themeradar:scan-task", onTask);
    window.addEventListener("themeradar:scan-complete", onComplete);
    api.scanTaskStatus().then((t) => setScanTask(t.status === "idle" ? null : t)).catch(() => {});
    return () => {
      window.removeEventListener("themeradar:scan-task", onTask);
      window.removeEventListener("themeradar:scan-complete", onComplete);
    };
  }, [load]);

  const scanRunning = scanTask?.status === "running";

  useEffect(() => {
    if (scanTask?.status === "done" && scanTask.trade_date) {
      setViewDate(scanTask.trade_date);
      load(scanTask.trade_date);
    }
  }, [scanTask?.status, scanTask?.trade_date, load]);

  useEffect(() => {
    if (!scanRunning) return;
    const poll = () => {
      api
        .scanTaskStatus()
        .then((t) => {
          if (t.status === "idle") {
            setScanTask(null);
            return;
          }
          setScanTask(t);
          if (t.status === "done" && t.trade_date) {
            setViewDate(t.trade_date);
            load(t.trade_date);
          }
        })
        .catch(() => {});
    };
    poll();
    const id = setInterval(poll, 2000);
    return () => clearInterval(id);
  }, [scanRunning, load]);

  const saveMaxStocks = async (value: number) => {
    const n = Math.max(0, Math.min(500, Math.floor(value) || 0));
    setSettingsSaving(true);
    try {
      await api.setIngestSettings(n);
      setMaxStocksPerConcept(n);
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSettingsSaving(false);
    }
  };

  const onMaxStocksChange = (raw: string) => {
    const n = raw === "" ? 0 : parseInt(raw, 10);
    if (Number.isNaN(n)) return;
    setMaxStocksPerConcept(Math.max(0, Math.min(500, n)));
  };

  const onMaxStocksBlur = () => {
    void saveMaxStocks(maxStocksPerConcept);
  };

  const runScan = async () => {
    setError("");
    if (!scanStart || !scanEnd) {
      setError("请填写开始日期和结束日期");
      return;
    }
    if (scanStart > scanEnd) {
      setError("开始日期不能晚于结束日期");
      return;
    }
    try {
      await saveMaxStocks(maxStocksPerConcept);
      const started = await api.scanLatest({
        startDate: scanStart,
        endDate: scanEnd,
      });
      if (import.meta.env.DEV) {
        console.log("[ThemeRadar] POST /api/scan/latest", started);
      }
      setScanTask({
        task_type: "scan",
        status: "running",
        message:
          started.message ||
          `扫描已启动：${started.start_date || scanStart || "?"} ~ ${started.end_date || scanEnd || "?"}`,
        trade_date: started.trade_date,
        progress: 0,
        total: 1,
      });
      if (started.trade_date) {
        setViewDate(started.trade_date);
      }
      const t = await api.scanTaskStatus();
      setScanTask(t.status === "idle" ? null : t);
    } catch (e) {
      setError(e instanceof Error ? e.message : "扫描失败");
    }
  };

  const clearAllData = async () => {
    if (!window.confirm("将清空所有缓存、内存快照与库内扫描数据（含旧演示数据），确定继续？")) {
      return;
    }
    setClearing(true);
    setError("");
    try {
      await api.clearData();
      setData(null);
      setViewDate("");
      refreshScanMeta(false);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "清空失败");
    } finally {
      setClearing(false);
    }
  };

  if (loading && !data?.top_sectors?.length) {
    return <div className="loading">加载中…</div>;
  }

  const env = data?.market_env;
  const marketOverview = data?.market_overview;
  const sectors = data?.top_sectors ?? [];
  const displayDate = data?.trade_date || viewDate;
  const riseFallTotal = (marketOverview?.up_count || 0) + (marketOverview?.down_count || 0) + (marketOverview?.flat_count || 0);
  const risePct = riseFallTotal > 0 ? ((marketOverview?.up_count || 0) / riseFallTotal) * 100 : 0;
  const flatPct = riseFallTotal > 0 ? ((marketOverview?.flat_count || 0) / riseFallTotal) * 100 : 0;
  const fallPct = riseFallTotal > 0 ? ((marketOverview?.down_count || 0) / riseFallTotal) * 100 : 0;

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
        <button className="btn btn-primary" onClick={runScan} disabled={scanRunning}>
          {scanRunning ? "后台扫描中…" : "执行收盘扫描"}
        </button>
      </div>

      {error && <p className="error" style={{ marginBottom: "1rem" }}>{error}</p>}

      {(env || marketOverview) && (
        <div className="card-glass" style={{ marginBottom: "1rem", padding: "1rem 1.1rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.7rem" }}>
            <h3 style={{ margin: 0, fontSize: "1rem" }}>大盘分析</h3>
            {env && (
              <span className={`env-conclusion ${env.conclusion}`}>
                {ENV_CONCLUSION_LABEL[env.conclusion] || env.conclusion}
              </span>
            )}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr", gap: "0.7rem", marginBottom: "0.85rem" }}>
            <div style={{ border: "1px solid var(--line)", borderRadius: "10px", padding: "0.65rem 0.75rem" }}>
              <div style={{ color: "var(--muted)", fontSize: "0.8rem" }}>全市场成交额（板块聚合）</div>
              <div style={{ fontSize: "1.65rem", fontWeight: 700, lineHeight: 1.2 }}>
                {formatYi(marketOverview?.total_turnover_yi || 0)}
                <span style={{ fontSize: "0.95rem", color: "var(--muted)", marginLeft: "0.25rem" }}>亿</span>
              </div>
            </div>
            <div style={{ border: "1px solid var(--line)", borderRadius: "10px", padding: "0.65rem 0.75rem" }}>
              <div style={{ color: "var(--muted)", fontSize: "0.8rem" }}>上涨</div>
              <div className="text-up" style={{ fontSize: "1.2rem", fontWeight: 700 }}>{marketOverview?.up_count ?? 0}</div>
            </div>
            <div style={{ border: "1px solid var(--line)", borderRadius: "10px", padding: "0.65rem 0.75rem" }}>
              <div style={{ color: "var(--muted)", fontSize: "0.8rem" }}>平盘</div>
              <div style={{ fontSize: "1.2rem", fontWeight: 700 }}>{marketOverview?.flat_count ?? 0}</div>
            </div>
            <div style={{ border: "1px solid var(--line)", borderRadius: "10px", padding: "0.65rem 0.75rem" }}>
              <div style={{ color: "var(--muted)", fontSize: "0.8rem" }}>下跌</div>
              <div className="text-down" style={{ fontSize: "1.2rem", fontWeight: 700 }}>{marketOverview?.down_count ?? 0}</div>
            </div>
          </div>
          <div style={{ borderTop: "1px solid var(--line)", paddingTop: "0.75rem" }}>
            <div style={{ color: "var(--muted)", fontSize: "0.82rem", marginBottom: "0.5rem" }}>涨跌统计</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0.6rem", marginBottom: "0.5rem" }}>
              <div>
                <div style={{ fontSize: "0.76rem", color: "var(--muted)" }}>上涨占比</div>
                <div className="text-up" style={{ fontWeight: 700 }}>{risePct.toFixed(1)}%</div>
              </div>
              <div>
                <div style={{ fontSize: "0.76rem", color: "var(--muted)" }}>平盘占比</div>
                <div style={{ fontWeight: 700 }}>{flatPct.toFixed(1)}%</div>
              </div>
              <div>
                <div style={{ fontSize: "0.76rem", color: "var(--muted)" }}>下跌占比</div>
                <div className="text-down" style={{ fontWeight: 700 }}>{fallPct.toFixed(1)}%</div>
              </div>
            </div>
            <div style={{ width: "100%", height: "10px", display: "flex", borderRadius: "999px", overflow: "hidden", background: "var(--line)" }}>
              <div style={{ width: `${risePct}%`, background: "var(--up)" }} />
              <div style={{ width: `${flatPct}%`, background: "var(--muted)" }} />
              <div style={{ width: `${fallPct}%`, background: "var(--down)" }} />
            </div>
            {env && (
              <div style={{ marginTop: "0.55rem", fontSize: "0.78rem", color: "var(--muted)" }}>
                涨停 {env.limit_up_count} 家 · 涨跌比 {(env.up_down_ratio * 100).toFixed(0)}% · 沪深300{" "}
                <span className={pctClass(env.index_pct)}>{formatPct(env.index_pct)}</span> · 环境分{" "}
                <span style={{ fontFamily: "JetBrains Mono" }}>{env.env_score.toFixed(0)}</span>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="card-glass" style={{ marginBottom: "1rem", padding: "0.85rem 1.1rem" }}>
        <div className="form-row" style={{ alignItems: "flex-end", marginBottom: 0, flexWrap: "wrap", gap: "1rem" }}>
          <div className="form-group">
            <label>开始日期</label>
            <input
              type="date"
              value={scanStart}
              min={jqMin || undefined}
              max={scanEnd || jqMax || undefined}
              onChange={(e) => setScanStart(e.target.value)}
              disabled={scanRunning}
            />
          </div>
          <div className="form-group">
            <label>结束日期</label>
            <input
              type="date"
              value={scanEnd}
              min={scanStart || jqMin || undefined}
              max={jqMax || undefined}
              onChange={(e) => setScanEnd(e.target.value)}
              disabled={scanRunning}
            />
          </div>
          <div className="form-group">
            <label>每板块分析股数</label>
            <input
              type="number"
              min={0}
              max={500}
              step={1}
              value={maxStocksPerConcept}
              onChange={(e) => onMaxStocksChange(e.target.value)}
              onBlur={onMaxStocksBlur}
              disabled={scanRunning || settingsSaving}
              style={{ width: "6rem" }}
              title="0 表示分析全部成分股"
            />
          </div>
          {jqRangeLabel && (
            <span style={{ fontSize: "0.8rem", color: "var(--muted)", paddingBottom: "0.5rem" }}>
              {jqRangeLabel}
            </span>
          )}
        </div>
        <p style={{ margin: "0.65rem 0 0", fontSize: "0.78rem", color: "var(--muted)" }}>
          开始/结束日期为必填，严格按该区间内的开市日扫描，不会自动向前补日。仪表盘展示结束日对应结果。
          {maxStocksPerConcept > 0
            ? ` 每板块取 Top ${maxStocksPerConcept} 只热门成分股。`
            : " 分析全部成分股（较慢）。"}
          {settingsSaving ? " 正在保存…" : ""}
        </p>
        <SectorScanPicker disabled={scanRunning} />
        <div style={{ marginTop: "0.75rem" }}>
          <button
            type="button"
            className="btn btn-ghost"
            style={{ fontSize: "0.8rem" }}
            disabled={scanRunning || clearing}
            onClick={() => void clearAllData()}
          >
            {clearing ? "清空中…" : "清空缓存与扫描数据"}
          </button>
        </div>
      </div>

      {scanRunning && scanTask && (
        <div
          className="card-glass task-status-bar task-running"
          style={{ marginBottom: "1rem", padding: "0.85rem 1.1rem" }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}>
            <span className="task-spinner" aria-hidden />
            <strong>扫描进行中</strong>
            <span style={{ fontSize: "0.88rem", opacity: 0.9 }}>{scanTask.message}</span>
          </div>
          <p style={{ fontSize: "0.78rem", color: "var(--muted)", margin: "0 0 0.5rem" }}>
            请求区间：{scanTask.scan_start_date || scanStart} ~ {scanTask.scan_end_date || scanEnd}
            {scanTask.trade_days && scanTask.trade_days.length > 0 ? (
              <>
                {" "}
                · 实际开市日 {scanTask.trade_days.length} 天（{scanTask.trade_days[0]} ~{" "}
                {scanTask.trade_days[scanTask.trade_days.length - 1]}）
              </>
            ) : null}
            {scanTask.trade_date ? ` · 正在处理 ${scanTask.trade_date}` : ""}
          </p>
          {scanTask.total > 0 && (
            <div className="task-progress-track">
              <div
                className="task-progress-fill"
                style={{
                  width: `${Math.min(100, Math.round((scanTask.progress / scanTask.total) * 100))}%`,
                }}
              />
            </div>
          )}
        </div>
      )}

      <h3 style={{ marginBottom: "1rem", fontSize: "1rem", color: "var(--muted)" }}>
        本次扫描板块{sectors.length > 0 ? `（${sectors.length}）` : ""}
      </h3>
      {!sectors.length ? (
        <div className="card-glass">
          <p style={{ color: "var(--muted)" }}>暂无数据：勾选扫描板块后点击「执行收盘扫描」</p>
        </div>
      ) : (
        <div className="sector-grid">
          {sectors.map((s) => {
            const leaderLabel =
              s.leader_stock_name && s.leader_stock
                ? `${s.leader_stock_name}（${s.leader_stock}）`
                : s.leader_stock_name || s.leader_stock;
            const detailUrl = displayDate
              ? `/sectors/${encodeURIComponent(s.sector_code)}?trade_date=${displayDate}`
              : `/sectors/${encodeURIComponent(s.sector_code)}`;
            return (
              <Link key={s.sector_code} to={detailUrl} style={{ textDecoration: "none", color: "inherit" }}>
                <div className="sector-card">
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <div>
                      <div style={{ fontWeight: 600 }}>{s.sector_name}</div>
                      <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>{s.sector_code}</div>
                    </div>
                    <span className={`stage-badge stage-${s.stage}`}>{STAGE_LABEL[s.stage] || s.stage}</span>
                  </div>
                  <div style={{ margin: "0.65rem 0 0.25rem", display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                    <span className={`hint-pill ${s.is_main_line ? "text-up" : ""}`}>
                      {s.is_main_line ? "主线通过" : "未通过主线"}
                    </span>
                    {s.main_line_tier && s.main_line_tier !== "rotation" && (
                      <span className="hint-pill">{s.main_line_tier === "top" ? "顶级主线" : "次级主线"}</span>
                    )}
                  </div>
                  {!!(s.rules?.length) && (
                    <div style={{ fontSize: "0.78rem", color: "var(--muted)", lineHeight: 1.5 }}>
                      {(() => {
                        const passed = (s.rules || []).filter((r) => (r as { passed?: boolean }).passed).map((r) => (r as { label?: string }).label).filter(Boolean);
                        const failed = (s.rules || []).filter((r) => !(r as { passed?: boolean }).passed).map((r) => (r as { label?: string }).label).filter(Boolean);
                        return (
                          <>
                            {passed.length > 0 && <div>满足：{passed.slice(0, 3).join("、")}{passed.length > 3 ? "…" : ""}</div>}
                            {failed.length > 0 && <div>不满足：{failed.slice(0, 3).join("、")}{failed.length > 3 ? "…" : ""}</div>}
                          </>
                        );
                      })()}
                    </div>
                  )}
                  {leaderLabel && (
                    <div style={{ marginTop: "0.5rem", fontSize: "0.75rem" }}>
                      龙头 {leaderLabel}
                      {s.leader_streak ? ` · ${s.leader_streak}连板` : ""}
                    </div>
                  )}
                </div>
              </Link>
            );
          })}
        </div>
      )}

    </>
  );
}
