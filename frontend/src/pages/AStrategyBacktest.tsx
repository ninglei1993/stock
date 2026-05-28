import { useEffect, useRef, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { api, BacktestRun, BacktestReport, BacktestTrade, NearMissItem } from "../api";
import BacktestSectorPicker from "../components/BacktestSectorPicker";
import { pctClass } from "../utils";

function NearMissSection({ runId }: { runId: number | null }) {
  const [items, setItems] = useState<NearMissItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) {
      setItems([]);
      return;
    }
    setLoading(true);
    api.aStrategyBacktestNearMiss(runId)
      .then((res) => setItems(res.items || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [runId]);

  if (loading) {
    return (
      <div className="card-glass" style={{ marginTop: "1.5rem" }}>
        <p style={{ color: "var(--muted)", padding: "0.5rem" }}>加载每日回测数据…</p>
      </div>
    );
  }
  if (items.length === 0) return null;

  const STAGE_LABEL: Record<string, string> = {
    dormant: "沉寂",
    sprout: "萌芽",
    ferment: "发酵",
    climax: "高潮",
    decay: "衰退",
  };
  const STAGE_COLOR: Record<string, string> = {
    dormant: "#64748b",
    sprout: "#fbbf24",
    ferment: "#34d399",
    climax: "#f87171",
    decay: "#94a3b8",
  };

  return (
    <div className="card-glass" style={{ marginTop: "1.5rem" }}>
      <h3 style={{ marginBottom: "0.75rem" }}>
        每日条件命中明细
        <span style={{ fontSize: "0.78rem", color: "var(--muted)", marginLeft: "0.5rem" }}>
          每条数据直接展示规则按钮（通过/未通过一目了然）
        </span>
      </h3>
      <table className="sectors-table">
        <thead>
          <tr>
            <th>日期</th>
            <th>板块</th>
            <th>通过条件</th>
            <th>规则按钮</th>
            <th>阶段</th>
            <th>环境分</th>
            <th>未通过原因</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const rowKey = `${item.trade_date}:${item.sector_code}`;
            const isExpanded = expandedKey === rowKey;
            return (
              <>
                <tr key={rowKey}>
                  <td>{item.trade_date}</td>
                  <td style={{ fontWeight: 600 }}>{item.sector_name}</td>
                  <td>
                    <span
                      style={{
                        display: "inline-block",
                        padding: "2px 8px",
                        borderRadius: "4px",
                        fontSize: "0.82rem",
                        fontWeight: 600,
                        background: item.all_passed
                          ? "rgba(16, 185, 129, 0.15)"
                          : "rgba(251, 191, 36, 0.15)",
                        color: item.all_passed ? "#34d399" : "#fbbf24",
                      }}
                    >
                      {item.pass_count}/{item.total_rules}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                      {item.rules.map((r) => (
                        <button
                          key={`${rowKey}:${r.key}`}
                          type="button"
                          disabled
                          title={r.threshold || "无阈值"}
                          style={{
                            border: "none",
                            borderRadius: "999px",
                            padding: "3px 8px",
                            fontSize: "0.74rem",
                            cursor: "default",
                            color: r.passed ? "#34d399" : "#f87171",
                            background: r.passed
                              ? "rgba(16, 185, 129, 0.12)"
                              : "rgba(248, 113, 113, 0.12)",
                          }}
                        >
                          {(r.label || r.key) || "规则"} · {r.passed ? "通过" : "未通过"}
                        </button>
                      ))}
                    </div>
                  </td>
                  <td style={{ color: STAGE_COLOR[item.stage] || "#94a3b8", fontWeight: 600 }}>
                    {STAGE_LABEL[item.stage] || item.stage}
                  </td>
                  <td>
                    {item.env_score != null ? (
                      <span
                        style={{
                          fontWeight: 600,
                          color: item.env_score >= 60 ? "#34d399" : item.env_score >= 40 ? "#fbbf24" : "#f87171",
                        }}
                      >
                        {item.env_score}
                        {item.can_long === false && (
                          <span style={{ fontSize: "0.7rem", color: "#f87171", marginLeft: 4 }}>禁多</span>
                        )}
                      </span>
                    ) : "—"}
                  </td>
                  <td style={{ fontSize: "0.78rem", color: "var(--muted)" }}>
                    {item.rule_fail_reasons?.length ? item.rule_fail_reasons.join("、") : "—"}
                  </td>
                  <td>
                    <button
                      className="btn btn-ghost"
                      type="button"
                      style={{ fontSize: "0.75rem", padding: "4px 10px" }}
                      onClick={() => setExpandedKey(isExpanded ? null : rowKey)}
                    >
                      {isExpanded ? "收起" : "详情"}
                    </button>
                  </td>
                </tr>
                {isExpanded && (
                  <tr key={`${rowKey}-detail`}>
                    <td colSpan={8} style={{ padding: 0 }}>
                      <div
                        style={{
                          padding: "0.75rem 1rem",
                          background: "rgba(30, 41, 59, 0.5)",
                          borderBottom: "1px solid rgba(148,163,184,0.1)",
                        }}
                      >
                        {/* 汇总指标行 */}
                        <div style={{ display: "flex", gap: "1.5rem", flexWrap: "wrap", marginBottom: "0.75rem", fontSize: "0.82rem" }}>
                          <span style={{ color: "var(--muted)" }}>
                            阶段：<strong style={{ color: STAGE_COLOR[item.stage] || "#94a3b8" }}>{STAGE_LABEL[item.stage] || item.stage}</strong>
                          </span>
                          {item.env_score != null && (
                            <span style={{ color: "var(--muted)" }}>
                              环境分：<strong style={{ color: item.env_score >= 60 ? "#34d399" : item.env_score >= 40 ? "#fbbf24" : "#f87171" }}>
                                {item.env_score}
                              </strong>
                              {item.can_long === false && <span style={{ color: "#f87171", marginLeft: 4 }}>(禁多)</span>}
                              {item.can_long === true && <span style={{ color: "#34d399", marginLeft: 4 }}>(可做多)</span>}
                            </span>
                          )}
                          {item.confirm_state && item.confirm_state !== "pending" && (
                            <span style={{ color: "#34d399" }}>确认状态：{item.confirm_state}</span>
                          )}
                          {item.exit_state && item.exit_state !== "normal" && (
                            <span style={{ color: "#f87171" }}>退出信号：已触发</span>
                          )}
                        </div>
                        {/* 规则详情表 */}
                        <table
                          style={{
                            width: "100%",
                            fontSize: "0.82rem",
                            borderCollapse: "collapse",
                          }}
                        >
                          <thead>
                            <tr style={{ color: "var(--muted)" }}>
                              <th style={{ textAlign: "left", padding: "4px 8px" }}>条件</th>
                              <th style={{ textAlign: "center", padding: "4px 8px" }}>结果</th>
                              <th style={{ textAlign: "left", padding: "4px 8px" }}>阈值</th>
                              <th style={{ textAlign: "left", padding: "4px 8px" }}>当前值</th>
                              <th style={{ textAlign: "left", padding: "4px 8px" }}>来源</th>
                            </tr>
                          </thead>
                          <tbody>
                            {item.rules.map((r) => (
                              <tr
                                key={`${rowKey}-detail-${r.key}`}
                                style={{ borderBottom: "1px solid rgba(148,163,184,0.06)" }}
                              >
                                <td style={{ padding: "4px 8px" }}>{r.label || r.key || "规则"}</td>
                                <td
                                  style={{
                                    textAlign: "center",
                                    padding: "4px 8px",
                                    color: r.passed ? "#34d399" : "#f87171",
                                    fontWeight: 600,
                                  }}
                                >
                                  {r.passed ? "通过" : "未通过"}
                                </td>
                                <td style={{ padding: "4px 8px", color: "var(--muted)", fontSize: "0.78rem" }}>
                                  {r.threshold || "—"}
                                </td>
                                <td
                                  style={{
                                    padding: "4px 8px",
                                    color: "var(--muted)",
                                    fontSize: "0.78rem",
                                    fontFamily: "JetBrains Mono, monospace",
                                    wordBreak: "break-all",
                                  }}
                                >
                                  {r.current == null
                                    ? "—"
                                    : typeof r.current === "object"
                                      ? (() => {
                                          const obj = r.current as Record<string, unknown>;
                                          return (
                                            <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px" }}>
                                              {Object.entries(obj).map(([k, v]) => {
                                                if (k.endsWith("debug") || k.endsWith("_tail") || k.endsWith("_last6")) return null;
                                                const display = v == null ? "—"
                                                  : typeof v === "number" ? (v > 1000 ? v.toFixed(0) : Number(v.toFixed(4)).toString())
                                                  : typeof v === "boolean" ? (v ? "是" : "否")
                                                  : Array.isArray(v) ? `[${v.length}项]`
                                                  : typeof v === "object" ? JSON.stringify(v)
                                                  : String(v);
                                                return (
                                                  <span key={k}>
                                                    <span style={{ color: "var(--muted)" }}>{k}:</span>{" "}
                                                    <span style={{ color: "#e2e8f0" }}>{display}</span>
                                                  </span>
                                                );
                                              })}
                                            </div>
                                          );
                                        })()
                                      : String(r.current)}
                                </td>
                                <td style={{ padding: "4px 8px", color: "var(--muted)", fontSize: "0.78rem" }}>
                                  {r.source === "manual" ? "手动" : "自动"}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </td>
                  </tr>
                )}
              </>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const DEFAULT_CAPITAL = 1_000_000;

const ALERT_LABEL: Record<string, string> = {
  A_STRATEGY_BUY: "A策略买入",
  A_STRATEGY_EXIT: "A策略退出",
  A_STRATEGY_STOP_LOSS: "A策略止损",
};

export default function AStrategyBacktest() {
  const [startDate, setStartDate] = useState("2024-04-01");
  const [endDate, setEndDate] = useState("2025-04-01");
  const [selectedSectors, setSelectedSectors] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);

  const [activeRunId, setActiveRunId] = useState<number | null>(null);
  const [activeRun, setActiveRun] = useState<BacktestRun | null>(null);
  const [report, setReport] = useState<BacktestReport | null>(null);
  const [trades, setTrades] = useState<BacktestTrade[]>([]);
  const [error, setError] = useState("");

  const pollRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    api.systemStatus().then((s) => {
      if (s.default_scan_start) setStartDate(s.default_scan_start);
      if (s.default_scan_end) setEndDate(s.default_scan_end);
    });
  }, []);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, []);

  const pollRun = (runId: number) => {
    if (pollRef.current) clearTimeout(pollRef.current);

    const tick = async () => {
      try {
        const run = await api.getAStrategyBacktest(runId);
        setActiveRun(run);
        if (run.status === "done") {
          const [r, t] = await Promise.all([
            api.aStrategyBacktestReport(runId),
            api.aStrategyBacktestTrades(runId),
          ]);
          setReport(r);
          setTrades(t);
          return;
        }
        if (run.status === "failed") {
          setError(run.error_message || "回测失败");
          return;
        }
        pollRef.current = setTimeout(tick, 3000);
      } catch (e) {
        setError(e instanceof Error ? e.message : "轮询失败");
      }
    };
    tick();
  };

  const submit = async () => {
    if (selectedSectors.size === 0) {
      alert("请至少勾选一个回测板块");
      return;
    }
    setSubmitting(true);
    setError("");
    setReport(null);
    setTrades([]);
    setActiveRun(null);
    try {
      const run = await api.createAStrategyBacktest({
        start_date: startDate,
        end_date: endDate,
        params: {
          sector_codes: Array.from(selectedSectors),
          initial_capital: DEFAULT_CAPITAL,
        },
      });
      setActiveRunId(run.id);
      setActiveRun(run);
      pollRun(run.id);
    } catch (e) {
      alert(e instanceof Error ? e.message : "创建失败");
    } finally {
      setSubmitting(false);
    }
  };

  const runStatus = activeRun?.status ?? null;
  const isRunning = runStatus === "running" || runStatus === "pending";
  const isCreatingRun = submitting && !activeRun;
  const showProgress = isCreatingRun || !!activeRun;
  const progressPct = activeRun
    ? activeRun.total_days > 0
      ? Math.round((activeRun.progress / activeRun.total_days) * 100)
      : runStatus === "done"
        ? 100
        : 0
    : isCreatingRun
      ? 5
    : 0;
  const progressTitle =
    isCreatingRun
      ? "正在创建回测任务…"
      : runStatus === "done"
        ? "回测已完成"
        : runStatus === "failed"
          ? "回测失败"
          : "回测进行中…";

  const initialCapitalFromRun = Number(
    (report?.run?.params as { initial_capital?: number } | undefined)?.initial_capital
  );
  const useAbsoluteEquity =
    !!report?.equity_curve?.length &&
    (report.equity_curve[0]?.equity ?? 0) >= 10_000;

  const chartData =
    report?.equity_curve?.map((p) => {
      const bench =
        useAbsoluteEquity && p.benchmark < 1000
          ? p.benchmark *
            (initialCapitalFromRun >= 10_000 ? initialCapitalFromRun : DEFAULT_CAPITAL)
          : p.benchmark;
      return { ...p, benchmark: bench };
    }) ?? [];

  return (
    <>
      <h2 className="page-title">A策略回测</h2>
      <p style={{ fontSize: "0.82rem", color: "var(--muted)", marginBottom: "1rem" }}>
        严格遵循A策略6条硬性规则买入、退出信号卖出、-8%止损。买卖标的为板块龙头成分股。
      </p>

      {error && <div className="error card-glass" style={{ marginBottom: "1rem" }}>{error}</div>}

      {/* --- 新建回测表单 --- */}
      <div className="card-glass" style={{ marginBottom: "1.5rem" }}>
        <h3 style={{ fontSize: "1rem", marginBottom: "1rem" }}>新建回测</h3>
        <div style={{ marginBottom: "1rem" }}>
          <BacktestSectorPicker
            selected={selectedSectors}
            onChange={setSelectedSectors}
            disabled={submitting || isRunning}
          />
        </div>
        <div className="form-row">
          <div className="form-group">
            <label>开始日期</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              disabled={isRunning}
            />
          </div>
          <div className="form-group">
            <label>结束日期</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              disabled={isRunning}
            />
          </div>
          <div className="form-group">
            <label>初始资金</label>
            <input
              type="text"
              value="100万"
              disabled
              style={{ width: "6rem" }}
            />
          </div>
          <button
            className="btn btn-primary"
            onClick={submit}
            disabled={submitting || isRunning}
          >
            {submitting ? "提交中…" : "开始回测"}
          </button>
        </div>
      </div>

      {/* --- 回测进度 --- */}
      {showProgress && (
        <div className="card-glass" style={{ marginBottom: "1.5rem" }}>
          <h3 style={{ fontSize: "1rem", marginBottom: "0.75rem" }}>
            {progressTitle} {progressPct}%
          </h3>
          <div
            style={{
              height: "8px",
              borderRadius: "4px",
              background: "rgba(255,255,255,0.08)",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width: `${progressPct}%`,
                height: "100%",
                background:
                  isCreatingRun
                    ? "linear-gradient(90deg, #6366f1, #818cf8)"
                    : runStatus === "failed"
                    ? "linear-gradient(90deg, #ef4444, #f87171)"
                    : runStatus === "done"
                      ? "linear-gradient(90deg, #10b981, #34d399)"
                      : "linear-gradient(90deg, #3b82f6, #60a5fa)",
                borderRadius: "4px",
                transition: "width 0.4s ease",
              }}
            />
          </div>
          <p style={{ fontSize: "0.78rem", color: "var(--muted)", marginTop: "0.5rem" }}>
            {isCreatingRun
              ? "正在等待后端创建任务并返回 run id…"
              : `已处理 ${activeRun?.progress ?? 0} / ${activeRun?.total_days ?? "?"} 个交易日（含前21日预热数据）`}
          </p>
        </div>
      )}

      {/* --- 回测结果 --- */}
      {report && report.metrics && (
        <>
          {report.trade_mode_note && (
            <div className="card-glass demo-banner" style={{ marginBottom: "1rem" }}>
              <strong>成交说明：</strong>
              {report.trade_mode_note}
            </div>
          )}
          <div className="metric-grid" style={{ marginBottom: "1rem" }}>
            {(
              [
                ["累计收益", `${report.metrics.total_return}%`, report.metrics.total_return],
                ["最大回撤", `${report.metrics.max_drawdown}%`, -1],
                ["胜率", `${report.metrics.win_rate}%`, report.metrics.win_rate],
                ["交易笔数", `${report.metrics.trade_count}`, 0],
                ["基准收益", `${report.metrics.benchmark_return}%`, report.metrics.benchmark_return],
              ] as [string, string, number][]
            ).map(([label, val, num]) => (
              <div key={label} className="metric-card">
                <div className="metric-label">{label}</div>
                <div
                  className={`metric-value ${
                    typeof num === "number" && num > 0 && label !== "最大回撤" && label !== "交易笔数"
                      ? "text-up"
                      : typeof num === "number" && num < 0
                        ? "text-down"
                        : ""
                  }`}
                >
                  {val}
                </div>
              </div>
            ))}
          </div>

          {/* 每日回测规则明细（放在上半屏，避免被误认为未展示） */}
          {activeRunId && <NearMissSection runId={activeRunId} />}

          {/* 收益曲线 */}
          <div className="card-glass" style={{ height: 320, marginBottom: "1rem" }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.15)" />
                <XAxis dataKey="trade_date" tick={{ fill: "#94a3b8", fontSize: 10 }} />
                <YAxis
                  tick={{ fill: "#94a3b8", fontSize: 10 }}
                  domain={["auto", "auto"]}
                  tickFormatter={(v) =>
                    useAbsoluteEquity ? `${(Number(v) / 10000).toFixed(0)}万` : String(v)
                  }
                />
                <Tooltip contentStyle={{ background: "#1a222d", border: "1px solid #334155" }} />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="equity"
                  name="策略资产"
                  stroke="#60a5fa"
                  dot={false}
                  strokeWidth={2}
                />
                <Line
                  type="monotone"
                  dataKey="benchmark"
                  name="沪深300"
                  stroke="#64748b"
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* 交易明细 */}
          <div className="card-glass sectors-table-wrap">
            <h3 style={{ marginBottom: "0.75rem", padding: "0 0.5rem" }}>交易明细</h3>
            <table className="sectors-table">
              <thead>
                <tr>
                  <th>板块</th>
                  <th>信号日</th>
                  <th>买入日</th>
                  <th>买入代码</th>
                  <th>买入名称</th>
                  <th>买入价</th>
                  <th>卖出日</th>
                  <th>卖出价</th>
                  <th>持仓天数</th>
                  <th>收益率</th>
                  <th>信号类型</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => (
                  <tr key={t.id}>
                    <td>{t.sector_name}</td>
                    <td>{t.signal_date || "—"}</td>
                    <td>{t.entry_date}</td>
                    <td style={{ fontFamily: "JetBrains Mono" }}>{t.stock_code}</td>
                    <td>{t.stock_name || "—"}</td>
                    <td>{t.entry_price.toFixed(2)}</td>
                    <td>{t.exit_date || "持仓中"}</td>
                    <td>{t.exit_price != null ? t.exit_price.toFixed(2) : "—"}</td>
                    <td>{t.holding_days != null ? `${t.holding_days}天` : "—"}</td>
                    <td className={pctClass(t.return_pct || 0)}>
                      {t.return_pct != null ? `${t.return_pct}%` : "—"}
                    </td>
                    <td>{ALERT_LABEL[t.alert_code] || t.alert_name_cn || t.alert_code}</td>
                    <td style={{ fontSize: "0.75rem", maxWidth: "16rem" }}>
                      {t.human_reason}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {trades.length === 0 && (
              <p style={{ padding: "1rem", color: "var(--muted)" }}>
                暂无合适买入点（所选板块未满足A策略买入条件）
              </p>
            )}
          </div>
        </>
      )}

    </>
  );
}
