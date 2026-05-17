import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
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
import { pctClass, STRATEGY_LABEL, RUN_STATUS_LABEL } from "../utils";
import {
  SECTOR_SELECT_ALGO,
  STOCK_SELECT_ALGO,
  STRATEGY_RULES,
} from "../constants/strategyAlgo";

const STRATEGIES = [
  { id: "fish_body", name: STRATEGY_LABEL.fish_body },
  { id: "sprout_probe", name: STRATEGY_LABEL.sprout_probe },
  { id: "fixed_hold", name: STRATEGY_LABEL.fixed_hold },
  { id: "top5_rotation", name: STRATEGY_LABEL.top5_rotation },
];

function StrategyAlgoPanel({ strategyId }: { strategyId: string }) {
  const rule = STRATEGY_RULES[strategyId] || STRATEGY_RULES.fish_body;
  return (
    <div className="card-glass strategy-algo" style={{ marginBottom: "1.5rem" }}>
      <h3 style={{ fontSize: "1rem", marginBottom: "0.75rem" }}>回测算法说明</h3>
      <pre className="algo-block">{SECTOR_SELECT_ALGO}</pre>
      <pre className="algo-block">{STOCK_SELECT_ALGO}</pre>
      <div className="algo-rule">
        <strong>当前策略：{rule.name}</strong>
        <div>买入条件：{rule.buy}</div>
        <div>卖出条件：{rule.sell}</div>
      </div>
    </div>
  );
}

export default function Backtest() {
  const { id } = useParams<{ id: string }>();
  const [runs, setRuns] = useState<BacktestRun[]>([]);
  const [report, setReport] = useState<BacktestReport | null>(null);
  const [trades, setTrades] = useState<BacktestTrade[]>([]);
  const [startDate, setStartDate] = useState("2024-04-01");
  const [endDate, setEndDate] = useState("2025-04-01");
  const [jqMin, setJqMin] = useState("");
  const [jqMax, setJqMax] = useState("");
  const [strategy, setStrategy] = useState("fish_body");
  const [submitting, setSubmitting] = useState(false);
  const [loadError, setLoadError] = useState("");

  const loadRuns = () => api.listBacktests().then(setRuns).catch(console.error);

  useEffect(() => {
    loadRuns();
    api.systemStatus().then((s) => {
      if (!s.jq_data_range) return;
      const { start, end } = s.jq_data_range;
      setJqMin(start);
      setJqMax(end);
      setStartDate(start);
      setEndDate(end);
    });
  }, []);

  useEffect(() => {
    if (!id) {
      setReport(null);
      setTrades([]);
      return;
    }
    const runId = parseInt(id, 10);
    setLoadError("");
    const poll = () => {
      api
        .getBacktest(runId)
        .then((run) => {
          if (run.status === "done") {
            return Promise.all([
              api.backtestReport(runId),
              api.backtestTrades(runId),
            ]).then(([r, t]) => {
              setReport(r);
              setTrades(t);
            });
          } else if (run.status === "failed") {
            setLoadError(run.error_message || "回测失败");
          } else if (run.status === "running" || run.status === "pending") {
            setTimeout(poll, 2000);
          }
          loadRuns();
        })
        .catch((e) => setLoadError(e instanceof Error ? e.message : "加载失败"));
    };
    poll();
  }, [id]);

  const submit = async () => {
    setSubmitting(true);
    try {
      const run = await api.createBacktest({
        strategy_id: strategy,
        start_date: startDate,
        end_date: endDate,
        params: { max_positions: 3, position_size: 0.1 },
      });
      window.location.href = `/backtest/${run.id}`;
    } catch (e) {
      alert(e instanceof Error ? e.message : "创建失败");
    } finally {
      setSubmitting(false);
    }
  };

  const activeStrategy = report?.run?.strategy_id || strategy;

  return (
    <>
      <h2 className="page-title">回测中心</h2>
      {loadError && <div className="error card-glass">{loadError}</div>}

      <StrategyAlgoPanel strategyId={activeStrategy} />

      {!id && (
        <div className="card-glass" style={{ marginBottom: "1.5rem" }}>
          <h3 style={{ fontSize: "1rem", marginBottom: "1rem" }}>新建回测</h3>
          {jqMin && jqMax && (
            <p style={{ fontSize: "0.8rem", color: "var(--muted)", marginBottom: "0.75rem" }}>
              聚宽数据权限：{jqMin} ~ {jqMax}（超出范围将自动截断）
            </p>
          )}
          <div className="form-row">
            <div className="form-group">
              <label>开始日期</label>
              <input
                type="date"
                value={startDate}
                min={jqMin || undefined}
                max={jqMax || undefined}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div className="form-group">
              <label>结束日期</label>
              <input
                type="date"
                value={endDate}
                min={jqMin || undefined}
                max={jqMax || undefined}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
            <div className="form-group">
              <label>策略</label>
              <select
                value={strategy}
                onChange={(e) => setStrategy(e.target.value)}
              >
                {STRATEGIES.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>
            <button className="btn btn-primary" onClick={submit} disabled={submitting}>
              {submitting ? "提交中…" : "开始回测"}
            </button>
          </div>
        </div>
      )}

      {report && report.metrics && (
        <>
          {report.trade_mode_note && (
            <div className="card-glass demo-banner" style={{ marginBottom: "1rem" }}>
              <strong>成交说明：</strong>
              {report.trade_mode_note}
            </div>
          )}
          <div className="metric-grid" style={{ marginBottom: "1rem" }}>
            {[
              ["累计收益", `${report.metrics.total_return}%`, report.metrics.total_return],
              ["最大回撤", `${report.metrics.max_drawdown}%`, -1],
              ["胜率", `${report.metrics.win_rate}%`, report.metrics.win_rate],
              ["鱼身捕获率", `${report.metrics.fish_body_capture}%`, report.metrics.fish_body_capture],
              ["基准收益", `${report.metrics.benchmark_return}%`, report.metrics.benchmark_return],
            ].map(([label, val, num]) => (
              <div key={label} className="metric-card">
                <div className="metric-label">{label}</div>
                <div
                  className={`metric-value ${
                    typeof num === "number" && num >= 0 && label !== "最大回撤"
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
          <div className="card-glass" style={{ height: 320, marginBottom: "1rem" }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={report.equity_curve}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.15)" />
                <XAxis dataKey="trade_date" tick={{ fill: "#94a3b8", fontSize: 10 }} />
                <YAxis tick={{ fill: "#94a3b8", fontSize: 10 }} domain={["auto", "auto"]} />
                <Tooltip contentStyle={{ background: "#1a222d", border: "1px solid #334155" }} />
                <Legend />
                <Line type="monotone" dataKey="equity" name="策略净值" stroke="#60a5fa" dot={false} strokeWidth={2} />
                <Line type="monotone" dataKey="benchmark" name="沪深300" stroke="#64748b" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
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
                  <th>卖出代码</th>
                  <th>卖出名称</th>
                  <th>卖出价</th>
                  <th>持仓天数</th>
                  <th>收益率</th>
                  <th>信号</th>
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
                    <td>{t.exit_date || "—"}</td>
                    <td style={{ fontFamily: "JetBrains Mono" }}>{t.sell_stock_code || t.stock_code}</td>
                    <td>{t.sell_stock_name || t.stock_name || "—"}</td>
                    <td>{t.exit_price != null ? t.exit_price.toFixed(2) : "—"}</td>
                    <td>{t.holding_days != null ? `${t.holding_days} 天` : "—"}</td>
                    <td className={pctClass(t.return_pct || 0)}>
                      {t.return_pct != null ? `${t.return_pct}%` : "—"}
                    </td>
                    <td>{t.alert_name_cn || t.alert_code}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {trades.length === 0 && (
              <p style={{ padding: "1rem", color: "var(--muted)" }}>本区间无成交</p>
            )}
          </div>
        </>
      )}

      <div className="card-glass" style={{ marginTop: "1.5rem" }}>
        <h3 style={{ marginBottom: "0.75rem" }}>历史回测</h3>
        <table>
          <thead>
            <tr>
              <th>编号</th>
              <th>策略</th>
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
                <td>{STRATEGY_LABEL[r.strategy_id] || r.strategy_id}</td>
                <td>
                  {r.start_date} ~ {r.end_date}
                </td>
                <td>{RUN_STATUS_LABEL[r.status] || r.status}</td>
                <td>{r.total_days ? `${r.progress}/${r.total_days}` : "—"}</td>
                <td>
                  <Link to={`/backtest/${r.id}`}>查看</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
