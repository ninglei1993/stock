import { useEffect, useState } from "react";
import { useParams, Link, useSearchParams } from "react-router-dom";
import { api, SectorDetail as SectorDetailType } from "../api";
import { STAGE_LABEL, POSITION_LABEL, pctClass, formatPct } from "../utils";

export default function SectorDetail() {
  const { code } = useParams<{ code: string }>();
  const [searchParams] = useSearchParams();
  const tradeDate = searchParams.get("trade_date") || undefined;
  const stocksLimitFromQuery = searchParams.get("stocks_limit");
  const initialStocksLimit = stocksLimitFromQuery === "0" ? 0 : 30;
  const [stocksLimit, setStocksLimit] = useState<number>(initialStocksLimit);
  const [detail, setDetail] = useState<SectorDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const showAllStocks = stocksLimit === 0;
  const [rulesDetailOpen, setRulesDetailOpen] = useState(false);
  const [rulesDetailPayload, setRulesDetailPayload] = useState<{
    trade_date: string;
    rules: unknown[];
  } | null>(null);

  const summarizeRuleCurrent = (current: unknown) => {
    if (!current || typeof current !== "object" || Array.isArray(current)) return current;
    const clone: Record<string, unknown> = { ...(current as Record<string, unknown>) };
    // 把“长字段”留给弹窗查看，避免表格行高被撑爆
    delete clone.vol_ratio_debug;
    delete clone.share_8d_debug;
    delete clone.net_inflow_history_tail;
    return clone;
  };

  useEffect(() => {
    if (!code) return;
    setLoading(true);
    api
      .sector(code, tradeDate, stocksLimit)
      .then(setDetail)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [code, tradeDate, stocksLimit]);

  if (loading) return <div className="loading">加载中…</div>;
  if (error) return <div className="error">{error}</div>;
  if (!detail) return null;
  const rules = detail.rules || [];
  const passed = rules.filter((r) => r.passed);
  const failed = rules.filter((r) => !r.passed);
  // 当存在未通过规则时，只展示未通过规则的“详细计算数据”，避免让通过项淹没关键信息。
  const ruleTableRows = failed.length > 0 ? failed : rules;

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
          <span className={`hint-pill ${detail.is_main_line ? "text-up" : "text-down"}`}>
            {detail.is_main_line ? "主线通过" : "未通过主线"}
          </span>
        </div>
        <p className="detail-meta">
          {detail.sector_code} · {detail.trade_date}
          {rules.length > 0 ? (
            <>
              {" "}
              · 主线指标 <strong>{passed.length}</strong>/{rules.length}
            </>
          ) : null}
          {detail.inflow_days > 0 && ` · 资金连续流入 ${detail.inflow_days} 日`}
        </p>
      </div>

      {(rules.length > 0 || (detail.rule_fail_reasons?.length || 0) > 0) && (
        <div className="card-glass" style={{ marginBottom: "1rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.75rem", marginBottom: "0.6rem" }}>
            <h3 style={{ fontSize: "0.95rem", margin: 0 }}>A策略主线指标</h3>
            {rules.length > 0 && (
              <button
                type="button"
                className="btn btn-ghost"
                style={{ fontSize: "0.8rem" }}
                onClick={() => {
                  setRulesDetailPayload({
                    trade_date: detail.trade_date,
                    rules: ruleTableRows,
                  });
                  setRulesDetailOpen(true);
                }}
              >
                查看详情
              </button>
            )}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.8rem", marginBottom: "0.75rem" }}>
            <div>
              <div style={{ fontSize: "0.82rem", color: "var(--muted)", marginBottom: "0.35rem" }}>满足</div>
              {passed.length === 0 ? (
                <div style={{ fontSize: "0.85rem", color: "var(--muted)" }}>—</div>
              ) : (
                <ul style={{ margin: 0, paddingLeft: "1.2rem", lineHeight: 1.7 }}>
                  {passed.map((r) => (
                    <li key={r.key} style={{ fontSize: "0.85rem" }}>{r.label}</li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <div style={{ fontSize: "0.82rem", color: "var(--muted)", marginBottom: "0.35rem" }}>不满足</div>
              {failed.length === 0 ? (
                <div style={{ fontSize: "0.85rem", color: "var(--muted)" }}>—</div>
              ) : (
                <ul style={{ margin: 0, paddingLeft: "1.2rem", lineHeight: 1.7 }}>
                  {failed.map((r) => (
                    <li key={r.key} style={{ fontSize: "0.85rem" }}>{r.label}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
          {rules.length > 0 && (
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>指标</th>
                    <th>结果</th>
                    <th>阈值</th>
                    <th>当前值</th>
                    <th>来源</th>
                  </tr>
                </thead>
                <tbody>
                    {ruleTableRows.map((r) => (
                    <tr key={r.key}>
                      <td>{r.label}</td>
                      <td className={r.passed ? "text-up" : "text-down"} style={{ fontWeight: 700 }}>
                        {r.passed ? "满足" : "不满足"}
                      </td>
                      <td style={{ fontFamily: "JetBrains Mono", fontSize: "0.82rem" }}>{r.threshold || "—"}</td>
                      <td style={{ fontFamily: "JetBrains Mono", fontSize: "0.82rem" }}>
                          {r.current == null
                            ? "—"
                            : typeof r.current === "string"
                              ? r.current
                              : (
                                <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word", fontFamily: "JetBrains Mono", fontSize: "0.82rem", lineHeight: 1.3, maxHeight: "6rem", overflow: "auto" }}>
                                  {JSON.stringify(summarizeRuleCurrent(r.current), null, 2)}
                                </pre>
                              )}
                      </td>
                      <td style={{ fontSize: "0.82rem", color: "var(--muted)" }}>{r.source || "auto"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {rulesDetailOpen && rulesDetailPayload && (
            <div
              role="dialog"
              aria-modal="true"
              onClick={() => setRulesDetailOpen(false)}
              style={{
                position: "fixed",
                inset: 0,
                background: "rgba(0,0,0,0.55)",
                zIndex: 1000,
                display: "flex",
                justifyContent: "center",
                alignItems: "center",
                padding: "1rem",
              }}
            >
              <div
                onClick={(e) => e.stopPropagation()}
                style={{
                  width: "min(980px, 100%)",
                  maxHeight: "80vh",
                  overflow: "auto",
                  background: "#0b1220",
                  border: "1px solid rgba(148,163,184,0.25)",
                  borderRadius: "12px",
                  padding: "1rem",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem", marginBottom: "0.75rem" }}>
                  <div style={{ fontWeight: 700 }}>规则详情（可核算中间量）</div>
                  <button type="button" className="btn btn-ghost" style={{ fontSize: "0.8rem" }} onClick={() => setRulesDetailOpen(false)}>
                    关闭
                  </button>
                </div>
                <pre style={{ margin: 0, fontFamily: "JetBrains Mono", fontSize: "0.82rem", lineHeight: 1.35, whiteSpace: "pre-wrap" }}>
                  {JSON.stringify(rulesDetailPayload, null, 2)}
                </pre>
              </div>
            </div>
          )}
        </div>
      )}

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
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.75rem", marginBottom: "0.6rem" }}>
          <p style={{ margin: 0, fontSize: "0.78rem", color: "var(--muted)" }}>
            当前展示：{showAllStocks ? "全部成分股" : `Top ${stocksLimit}`}
          </p>
          <button
            type="button"
            className="btn btn-ghost"
            style={{ fontSize: "0.8rem" }}
            onClick={() => setStocksLimit((v) => (v === 0 ? 30 : 0))}
          >
            {showAllStocks ? "收起 Top 30" : "展开全部"}
          </button>
        </div>
        {(detail.pct_display_days?.length ?? 0) > 1 && (
          <p style={{ fontSize: "0.78rem", color: "var(--muted)", marginBottom: "0.75rem" }}>
            涨跌幅列为扫描区间内最近 {detail.pct_display_days!.length} 个交易日（
            {detail.pct_display_days![0]} ~{" "}
            {detail.pct_display_days![detail.pct_display_days!.length - 1]}）
          </p>
        )}
        {showAllStocks ? (
          <div style={{ maxHeight: "60vh", overflowY: "auto" }}>
            {detail.stocks.map((s) => (
              <div
                key={s.stock_code}
                style={{
                  display: "grid",
                  gridTemplateColumns: "110px 1fr 90px 140px",
                  gap: "0.6rem",
                  alignItems: "center",
                  padding: "0.45rem 0",
                  borderBottom: "1px solid var(--line)",
                }}
              >
                <div style={{ fontFamily: "JetBrains Mono", fontSize: "0.85rem" }}>{s.stock_code}</div>
                <div style={{ fontSize: "0.9rem" }}>{s.stock_name || "—"}</div>
                <div className={pctClass(s.pct_change)} style={{ fontWeight: 700 }}>
                  {formatPct(s.pct_change)}
                </div>
                <div style={{ textAlign: "right" }}>
                  <div style={{ fontSize: "0.82rem", color: "var(--muted)" }}>
                    {s.is_limit_up
                      ? `涨停${s.limit_up_streak > 0 ? ` / ${s.limit_up_streak}板` : ""}`
                      : s.limit_up_streak > 0
                        ? `${s.limit_up_streak}板`
                        : "—"}
                  </div>
                  <div style={{ fontWeight: 700 }}>{(s.money / 1e5).toFixed(2)} 亿</div>
                </div>
              </div>
            ))}
          </div>
        ) : (
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
                    <td>{(s.money / 1e5).toFixed(2)} 亿</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {detail.data_missing_items && detail.data_missing_items.length > 0 && (
        <div className="card-glass" style={{ marginTop: "1rem", borderColor: "rgba(245, 158, 11, 0.55)" }}>
          <h3 style={{ fontSize: "0.95rem", marginBottom: "0.5rem", color: "#f59e0b" }}>数据缺失说明</h3>
          <p style={{ fontSize: "0.8rem", color: "var(--muted)", marginBottom: "0.55rem" }}>
            以下字段当前未成功获取，页面未做默认值兜底，请检查数据源权限、日期区间和板块成分获取链路：
          </p>
          <ul style={{ margin: 0, paddingLeft: "1.2rem", lineHeight: 1.7 }}>
            {detail.data_missing_items.map((item) => (
              <li key={item} style={{ fontSize: "0.85rem" }}>
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
