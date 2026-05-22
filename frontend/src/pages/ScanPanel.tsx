import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Dashboard as DashboardData, TaskStatus } from "../api";
import SectorScanPicker from "../components/SectorScanPicker";
import { STAGE_LABEL } from "../utils";

export default function ScanPanel() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanTask, setScanTask] = useState<TaskStatus | null>(null);
  const [error, setError] = useState("");
  const [scanStart, setScanStart] = useState("");
  const [scanEnd, setScanEnd] = useState("");
  const [viewDate, setViewDate] = useState("");
  const [maxStocksPerConceptInput, setMaxStocksPerConceptInput] = useState("");
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
        setMaxStocksPerConceptInput(
          s.ingest_max_stocks_per_concept > 0 ? String(s.ingest_max_stocks_per_concept) : ""
        );
      }
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

  const saveMaxStocks = async (raw: string) => {
    const parsed = raw.trim() === "" ? 0 : parseInt(raw, 10);
    const n = Math.max(0, Math.min(500, Number.isNaN(parsed) ? 0 : Math.floor(parsed)));
    setSettingsSaving(true);
    try {
      await api.setIngestSettings(n === 0 ? null : n);
      setMaxStocksPerConceptInput(n > 0 ? String(n) : "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSettingsSaving(false);
    }
  };

  const onMaxStocksChange = (raw: string) => {
    if (raw === "") {
      setMaxStocksPerConceptInput("");
      return;
    }
    const n = parseInt(raw, 10);
    if (Number.isNaN(n)) return;
    setMaxStocksPerConceptInput(String(Math.max(0, Math.min(500, n))));
  };

  const onMaxStocksBlur = () => {
    void saveMaxStocks(maxStocksPerConceptInput);
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
      await saveMaxStocks(maxStocksPerConceptInput);
      const started = await api.scanLatest({
        startDate: scanStart,
        endDate: scanEnd,
      });
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

  const stopScan = async () => {
    try {
      const res = await api.cancelScan();
      if (res.cancelled) {
        setScanTask((prev) =>
          prev ? { ...prev, message: "正在停止…" } : prev
        );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "停止失败");
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

  const maxStocksPerConcept = maxStocksPerConceptInput.trim() === "" ? 0 : (parseInt(maxStocksPerConceptInput, 10) || 0);
  const sectors = data?.top_sectors ?? [];
  const displayDate = data?.trade_date || viewDate;

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h2 className="page-title" style={{ marginBottom: 0 }}>
          扫盘
          {displayDate && (
            <span style={{ fontSize: "0.9rem", color: "var(--muted)", fontWeight: 400, marginLeft: "0.75rem" }}>
              {displayDate}
            </span>
          )}
        </h2>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          {scanRunning && (
            <button className="btn btn-ghost" onClick={stopScan} style={{ color: "var(--down)" }}>
              停止扫盘
            </button>
          )}
          <button className="btn btn-primary" onClick={runScan} disabled={scanRunning}>
            {scanRunning ? "后台扫描中…" : "执行收盘扫描"}
          </button>
        </div>
      </div>

      {error && <p className="error" style={{ marginBottom: "1rem" }}>{error}</p>}

      <div className="card-glass" style={{ marginBottom: "1rem", padding: "0.85rem 1.1rem" }}>
        <div className="form-row" style={{ alignItems: "flex-end", marginBottom: 0, flexWrap: "wrap", gap: "1rem" }}>
          <div className="form-group">
            <label>开始日期</label>
            <input
              type="date"
              value={scanStart}
              max={scanEnd || undefined}
              onChange={(e) => setScanStart(e.target.value)}
              disabled={scanRunning}
            />
          </div>
          <div className="form-group">
            <label>结束日期</label>
            <input
              type="date"
              value={scanEnd}
              min={scanStart || undefined}
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
              value={maxStocksPerConceptInput}
              onChange={(e) => onMaxStocksChange(e.target.value)}
              onBlur={onMaxStocksBlur}
              disabled={scanRunning || settingsSaving}
              style={{ width: "6rem" }}
              title="留空或0表示分析全部成分股"
              placeholder="全部"
            />
          </div>
        </div>
        <p style={{ margin: "0.65rem 0 0", fontSize: "0.78rem", color: "var(--muted)" }}>
          开始/结束日期为必填，严格按该区间内的开市日扫描，不会自动向前补日。
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

      {loading && !sectors.length ? (
        <div className="loading">加载中…</div>
      ) : (
        <>
          <h3 style={{ marginBottom: "1rem", fontSize: "1rem", color: "var(--muted)" }}>
            扫描结果{sectors.length > 0 ? `（${sectors.length} 个板块）` : ""}
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
      )}
    </>
  );
}
