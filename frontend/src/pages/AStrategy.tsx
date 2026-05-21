import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, AStrategyManualInput, SectorScore } from "../api";
import { STAGE_LABEL } from "../utils";

type ManualForm = {
  auction_passed: boolean;
  negative_news: boolean;
  northbound_5d_yi: number;
  notes: string;
};

const DEFAULT_FORM: ManualForm = {
  auction_passed: true,
  negative_news: false,
  northbound_5d_yi: 0,
  notes: "",
};

function tierLabel(tier?: string): string {
  if (tier === "top") return "顶级主线";
  if (tier === "secondary") return "次级主线";
  return "轮动观察";
}

export default function AStrategy() {
  const [tradeDate, setTradeDate] = useState("");
  const [rows, setRows] = useState<SectorScore[]>([]);
  const [manualRows, setManualRows] = useState<AStrategyManualInput[]>([]);
  const [selectedCode, setSelectedCode] = useState("");
  const [form, setForm] = useState<ManualForm>(DEFAULT_FORM);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const [list, status] = await Promise.all([
        api.aStrategyMainLines(tradeDate || undefined, true),
        api.systemStatus(),
      ]);
      setRows(list.sectors || []);
      const td = list.trade_date || status.default_scan_date || "";
      setTradeDate(td || "");
      if (td) {
        const m = await api.aStrategyManualInputs(td);
        setManualRows(m || []);
      } else {
        setManualRows([]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const mainLines = useMemo(() => rows.filter((s) => s.is_main_line), [rows]);

  useEffect(() => {
    if (!selectedCode && rows.length > 0) {
      setSelectedCode(rows[0].sector_code);
    }
  }, [rows, selectedCode]);

  useEffect(() => {
    const current = manualRows.find((x) => x.sector_code === selectedCode);
    if (!current) {
      setForm(DEFAULT_FORM);
      return;
    }
    setForm({
      auction_passed: Boolean(current.values.auction_passed ?? true),
      negative_news: Boolean(current.values.negative_news ?? false),
      northbound_5d_yi: Number(current.values.northbound_5d_yi ?? 0),
      notes: String(current.values.notes ?? ""),
    });
  }, [manualRows, selectedCode]);

  const saveManual = async () => {
    if (!tradeDate || !selectedCode) return;
    setSaving(true);
    setError("");
    try {
      await api.setAStrategyManualInput({
        trade_date: tradeDate,
        sector_code: selectedCode,
        auction_passed: form.auction_passed,
        negative_news: form.negative_news,
        northbound_5d_yi: form.northbound_5d_yi,
        notes: form.notes,
      });
      const m = await api.aStrategyManualInputs(tradeDate);
      setManualRows(m || []);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  if (loading && rows.length === 0) return <div className="loading">加载中…</div>;

  return (
    <>
      <h2 className="page-title">A策略主线筛选</h2>
      {error && <p className="error">{error}</p>}
      <div className="card-glass" style={{ marginBottom: "1rem" }}>
        <div className="form-row" style={{ alignItems: "center" }}>
          <div className="form-group">
            <label>交易日</label>
            <input type="date" value={tradeDate} onChange={(e) => setTradeDate(e.target.value)} />
          </div>
          <button className="btn btn-primary" onClick={() => void load()}>
            刷新主线
          </button>
          <span style={{ color: "var(--muted)" }}>正式主线 {mainLines.length} 个</span>
        </div>
      </div>

      <div className="card-glass" style={{ marginBottom: "1rem" }}>
        <h3 style={{ fontSize: "0.95rem", marginBottom: "0.75rem" }}>主线规则结果</h3>
        <table>
          <thead>
            <tr>
              <th>板块</th>
              <th>分级</th>
              <th>状态</th>
              <th>确认/失效</th>
              <th>未通过规则</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.sector_code}>
                <td>
                  <Link to={`/sectors/${encodeURIComponent(r.sector_code)}?trade_date=${tradeDate}`}>
                    {r.sector_name}
                  </Link>
                </td>
                <td>{tierLabel(r.main_line_tier)}</td>
                <td>
                  {r.is_main_line ? (
                    <span className="text-up">通过</span>
                  ) : (
                    <span className="text-down">未通过</span>
                  )}
                </td>
                <td>
                  {(r.confirm_state || "pending") === "confirmed"
                    ? "已确立"
                    : STAGE_LABEL[r.stage || "dormant"] || r.stage}
                  {" / "}
                  {(r.exit_state || "normal") === "exit" ? "失效" : "正常"}
                </td>
                <td style={{ fontSize: "0.8rem" }}>
                  {(r.rule_fail_reasons || []).length > 0 ? (r.rule_fail_reasons || []).join("；") : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card-glass">
        <h3 style={{ fontSize: "0.95rem", marginBottom: "0.75rem" }}>人工输入（hybrid_manual）</h3>
        <div className="form-row">
          <div className="form-group">
            <label>板块</label>
            <select value={selectedCode} onChange={(e) => setSelectedCode(e.target.value)}>
              {rows.map((r) => (
                <option value={r.sector_code} key={r.sector_code}>
                  {r.sector_name} ({r.sector_code})
                </option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label>北向5日净流入（亿）</label>
            <input
              type="number"
              step="0.1"
              value={form.northbound_5d_yi}
              onChange={(e) => setForm((p) => ({ ...p, northbound_5d_yi: Number(e.target.value) || 0 }))}
            />
          </div>
          <div className="form-group">
            <label>竞价通过</label>
            <select
              value={form.auction_passed ? "yes" : "no"}
              onChange={(e) => setForm((p) => ({ ...p, auction_passed: e.target.value === "yes" }))}
            >
              <option value="yes">是</option>
              <option value="no">否</option>
            </select>
          </div>
          <div className="form-group">
            <label>负面消息</label>
            <select
              value={form.negative_news ? "yes" : "no"}
              onChange={(e) => setForm((p) => ({ ...p, negative_news: e.target.value === "yes" }))}
            >
              <option value="no">无</option>
              <option value="yes">有</option>
            </select>
          </div>
        </div>
        <div className="form-group">
          <label>备注</label>
          <input
            value={form.notes}
            onChange={(e) => setForm((p) => ({ ...p, notes: e.target.value }))}
            placeholder="如：监管问询、减持预告、政策降温等"
          />
        </div>
        <button className="btn btn-primary" disabled={saving || !selectedCode || !tradeDate} onClick={() => void saveManual()}>
          {saving ? "保存中…" : "保存人工输入"}
        </button>
      </div>
    </>
  );
}
