import { useCallback, useEffect, useMemo, useState } from "react";
import { api, BacktestSectorCandidate } from "../api";
import { STAGE_LABEL } from "../utils";

type Props = {
  selected: Set<string>;
  onChange: (codes: Set<string>) => void;
  disabled?: boolean;
};

export default function BacktestSectorPicker({ selected, onChange, disabled }: Props) {
  const [sectors, setSectors] = useState<BacktestSectorCandidate[]>([]);
  const [tradeDate, setTradeDate] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [backtestRes, scanRes] = await Promise.all([
        api.backtestSectorCandidates().catch(() => null),
        api.getScanSectors(),
      ]);

      const fallbackSectors: BacktestSectorCandidate[] = scanRes.universe.map((item, idx) => ({
        sector_code: item.sector_code,
        sector_name: item.sector_name,
        rank: idx + 1,
        total_score: 0,
        stage: "unknown",
        persistence_score: 0,
        capital_score: 0,
        breadth_score: 0,
        leader_score: 0,
        relative_score: 0,
      }));

      const resolvedSectors =
        backtestRes && backtestRes.sectors.length > 0 ? backtestRes.sectors : fallbackSectors;
      setSectors(resolvedSectors);
      setTradeDate(backtestRes?.trade_date ?? null);

      const availableCodes = new Set(resolvedSectors.map((item) => item.sector_code));
      const preferredScanSelected =
        scanRes.use_explicit_selection && scanRes.selected_codes.length > 0
          ? scanRes.selected_codes.filter((code) => availableCodes.has(code))
          : [];
      const defaultSelectedCodes =
        preferredScanSelected.length > 0
          ? preferredScanSelected
          : resolvedSectors.map((item) => item.sector_code);
      onChange(new Set(defaultSelectedCodes));
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载板块失败");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅挂载时默认全选
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = useMemo(() => {
    const q = filter.trim().toUpperCase();
    if (!q) return sectors;
    return sectors.filter(
      (c) =>
        c.sector_name.toUpperCase().includes(q) ||
        c.sector_code.toUpperCase().includes(q)
    );
  }, [sectors, filter]);

  const toggle = (code: string) => {
    const next = new Set(selected);
    if (next.has(code)) next.delete(code);
    else next.add(code);
    onChange(next);
  };

  const selectAll = () => onChange(new Set(filtered.map((s) => s.sector_code)));
  const clearAll = () => onChange(new Set());

  if (loading) {
    return (
      <p style={{ fontSize: "0.85rem", color: "var(--muted)" }}>正在加载仪表盘扫盘板块…</p>
    );
  }

  if (error) {
    return (
      <p style={{ fontSize: "0.85rem", color: "var(--danger)" }}>
        {error}
        <button type="button" className="btn btn-ghost" style={{ marginLeft: "0.5rem" }} onClick={load}>
          重试
        </button>
      </p>
    );
  }

  return (
    <div className="sector-scan-picker">
      <p style={{ fontSize: "0.78rem", color: "var(--muted)", margin: "0 0 0.5rem" }}>
        回测板块（{tradeDate ? `来自仪表盘扫盘 ${tradeDate}` : "使用扫盘Tab板块配置"}）已选{" "}
        <strong>{selected.size}</strong> / {sectors.length}
        {selected.size === 0 ? "（请至少勾选一个）" : ""}
      </p>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.5rem",
          alignItems: "center",
          marginBottom: "0.5rem",
        }}
      >
        <input
          type="search"
          placeholder="搜索板块"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          disabled={disabled}
          style={{ flex: "1 1 12rem", minWidth: "10rem" }}
        />
        <button type="button" className="btn btn-ghost" style={{ fontSize: "0.8rem" }} disabled={disabled} onClick={selectAll}>
          全选
        </button>
        <button type="button" className="btn btn-ghost" style={{ fontSize: "0.8rem" }} disabled={disabled} onClick={clearAll}>
          清空
        </button>
      </div>
      <div
        style={{
          maxHeight: "200px",
          overflowY: "auto",
          border: "1px solid var(--border)",
          borderRadius: "8px",
          padding: "0.5rem 0.75rem",
          background: "rgba(0,0,0,0.15)",
        }}
      >
        <ul style={{ listStyle: "none", margin: 0, padding: 0, columns: "min(300px, 100%) 2" }}>
          {filtered.map((c) => (
            <li key={c.sector_code} style={{ breakInside: "avoid", marginBottom: "0.35rem" }}>
              <label
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: "0.4rem",
                  fontSize: "0.82rem",
                  cursor: disabled ? "not-allowed" : "pointer",
                }}
              >
                <input
                  type="checkbox"
                  checked={selected.has(c.sector_code)}
                  disabled={disabled}
                  onChange={() => toggle(c.sector_code)}
                />
                <span>
                  <strong>#{c.rank}</strong> {c.sector_name}
                  <span style={{ color: "var(--muted)", marginLeft: "0.35rem" }}>
                    {c.sector_code}
                    {c.total_score > 0 ? ` · ${c.total_score.toFixed(0)}分` : ""}
                    {c.stage !== "unknown" ? ` · ${STAGE_LABEL[c.stage] || c.stage}` : ""}
                  </span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
