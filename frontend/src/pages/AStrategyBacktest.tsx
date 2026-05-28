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
import { api, BacktestRun, BacktestReport, BacktestTrade } from "../api";
import BacktestSectorPicker from "../components/BacktestSectorPicker";
import { pctClass, RUN_STATUS_LABEL } from "../utils";

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
  const [runs, setRuns] = useState<BacktestRun[]>([]);
  const [error, setError] = useState("");

  const pollRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    api.listAStrategyBacktests().then(setRuns).catch(console.error);
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
          api.listAStrategyBacktests().then(setRuns).catch(console.error);
          return;
        }
        if (run.status === "failed") {
          setError(run.error_message || "回测失败");
          api.listAStrategyBacktests().then(setRuns).catch(console.error);
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

  const viewRun = async (runId: number) => {
    setError("");
    setReport(null);
    setTrades([]);
    setActiveRunId(runId);
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
      } else if (run.status === "running" || run.status === "pending") {
        pollRun(runId);
      } else if (run.status === "failed") {
        setError(run.error_message || "回测失败");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    }
  };

  const progressPct =
    activeRun && activeRun.total_days > 0
      ? Math.round((activeRun.progress / activeRun.total_days) * 100)
      : 0;

  const isRunning =
    activeRun?.status === "running" || activeRun?.status === "pending";

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
      {isRunning && (
        <div className="card-glass" style={{ marginBottom: "1.5rem" }}>
          <h3 style={{ fontSize: "1rem", marginBottom: "0.75rem" }}>
            回测进行中… {progressPct}%
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
                background: "linear-gradient(90deg, #3b82f6, #60a5fa)",
                borderRadius: "4px",
                transition: "width 0.4s ease",
              }}
            />
          </div>
          <p style={{ fontSize: "0.78rem", color: "var(--muted)", marginTop: "0.5rem" }}>
            已处理 {activeRun?.progress ?? 0} / {activeRun?.total_days ?? "?"} 个交易日
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

      {/* --- 历史回测列表 --- */}
      <div className="card-glass" style={{ marginTop: "1.5rem" }}>
        <h3 style={{ marginBottom: "0.75rem" }}>历史回测</h3>
        <table>
          <thead>
            <tr>
              <th>编号</th>
              <th>区间</th>
              <th>状态</th>
              <th>进度</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <td>{r.id}</td>
                <td>
                  {r.start_date} ~ {r.end_date}
                </td>
                <td>{RUN_STATUS_LABEL[r.status] || r.status}</td>
                <td>{r.total_days ? `${r.progress}/${r.total_days}` : "—"}</td>
                <td>
                  <button
                    className="btn btn-ghost"
                    style={{ fontSize: "0.8rem" }}
                    onClick={() => viewRun(r.id)}
                    disabled={activeRunId === r.id && isRunning}
                  >
                    {activeRunId === r.id && isRunning ? "加载中…" : "查看"}
                  </button>
                </td>
              </tr>
            ))}
            {runs.length === 0 && (
              <tr>
                <td colSpan={5} style={{ color: "var(--muted)", padding: "1rem" }}>
                  暂无回测记录
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
