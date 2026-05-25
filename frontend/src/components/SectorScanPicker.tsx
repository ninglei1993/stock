import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ConceptItem } from "../api";

type Props = {
  disabled?: boolean;
};

export default function SectorScanPicker({ disabled }: Props) {
  const [universe, setUniverse] = useState<ConceptItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [historySelected, setHistorySelected] = useState<Set<string>>(new Set());
  const [useExplicit, setUseExplicit] = useState(false);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [scanHistory, setScanHistory] = useState<
    Array<{ label: string; codes: string[]; saved_at: string }>
  >([]);
  const [historyLabel, setHistoryLabel] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([api.getScanSectors(), api.getScanHistory()])
      .then(([res, hist]) => {
        setUniverse(res.universe);
        const selectedSet = new Set(res.selected_codes);
        setSelected(selectedSet);
        setHistorySelected(new Set(res.selected_codes));
        setUseExplicit(res.use_explicit_selection);
        setScanHistory(hist.history);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "加载板块失败"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
    const onApplied = () => load();
    window.addEventListener("themeradar:scan-history-applied", onApplied);
    return () => window.removeEventListener("themeradar:scan-history-applied", onApplied);
  }, [load]);

  const filtered = useMemo(() => {
    const q = filter.trim().toUpperCase();
    const base = q
      ? universe.filter(
          (c) =>
            c.sector_name.toUpperCase().includes(q) ||
            c.sector_code.toUpperCase().includes(q)
        )
      : universe;
    return [...base].sort((a, b) => {
      const aSelected = selected.has(a.sector_code) ? 1 : 0;
      const bSelected = selected.has(b.sector_code) ? 1 : 0;
      if (aSelected !== bSelected) return bSelected - aSelected;
      return a.sector_name.localeCompare(b.sector_name, "zh-Hans-CN");
    });
  }, [universe, filter, selected]);

  const historySelectedCount = useMemo(() => {
    let count = 0;
    selected.forEach((code) => {
      if (historySelected.has(code)) count += 1;
    });
    return count;
  }, [selected, historySelected]);

  const isHistorySelected = (code: string) => historySelected.has(code);
  const isSelected = (code: string) => selected.has(code);

  const filteredCountBySelection = useMemo(() => {
    let selectedCount = 0;
    filtered.forEach((c) => {
      if (selected.has(c.sector_code)) selectedCount += 1;
    });
    return selectedCount;
  }, [filtered, selected]);

  const persist = async (nextSelected: Set<string>, nextExplicit: boolean) => {
    setSaving(true);
    setError("");
    try {
      await api.setScanSectors({
        use_explicit_selection: nextExplicit,
        selected_codes: Array.from(nextSelected),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const toggle = (code: string) => {
    const next = new Set(selected);
    if (next.has(code)) next.delete(code);
    else next.add(code);
    setSelected(next);
    setUseExplicit(true);
    void persist(next, true);
  };

  const selectAllFiltered = () => {
    const next = new Set(selected);
    filtered.forEach((c) => next.add(c.sector_code));
    setSelected(next);
    setUseExplicit(true);
    void persist(next, true);
  };

  const clearAll = () => {
    const next = new Set<string>();
    setSelected(next);
    setUseExplicit(true);
    void persist(next, true);
  };

  const useAllConcepts = () => {
    setUseExplicit(false);
    void persist(selected, false);
  };

  const refreshHistory = () => {
    api
      .getScanHistory()
      .then((res) => setScanHistory(res.history))
      .catch(() => {});
  };

  const saveCurrentToHistory = async () => {
    if (selected.size === 0) {
      setError("请先勾选至少一个板块");
      return;
    }
    const label =
      historyLabel.trim() ||
      window.prompt("请输入保存名称", "未命名")?.trim() ||
      "未命名";
    setSaving(true);
    setError("");
    try {
      await api.saveScanHistory(label, Array.from(selected));
      setHistoryLabel("");
      refreshHistory();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存历史失败");
    } finally {
      setSaving(false);
    }
  };

  const applyHistoryEntry = async (entry: { label: string; codes: string[]; saved_at: string }) => {
    const next = new Set(entry.codes);
    setSelected(next);
    setUseExplicit(true);
    await persist(next, true);
    window.dispatchEvent(new CustomEvent("themeradar:scan-history-applied"));
  };

  const formatHistoryDate = (iso: string) => {
    try {
      return new Date(iso).toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return iso;
    }
  };

  if (loading) {
    return (
      <p style={{ fontSize: "0.85rem", color: "var(--muted)", margin: "0.5rem 0 0" }}>
        正在加载概念板块列表…
      </p>
    );
  }

  return (
    <>
    <div className="sector-scan-picker">
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.5rem",
          alignItems: "center",
          marginBottom: "0.5rem",
        }}
      >
        <label style={{ fontSize: "0.85rem", color: "var(--muted)" }}>扫描板块</label>
        <input
          type="search"
          placeholder="搜索板块名称或代码"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          disabled={disabled || saving}
          style={{ flex: "1 1 12rem", minWidth: "10rem" }}
        />
        <button
          type="button"
          className="btn btn-ghost"
          style={{ fontSize: "0.8rem", padding: "0.25rem 0.6rem" }}
          disabled={disabled || saving}
          onClick={selectAllFiltered}
        >
          全选当前列表
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          style={{ fontSize: "0.8rem", padding: "0.25rem 0.6rem" }}
          disabled={disabled || saving}
          onClick={clearAll}
        >
          清空勾选
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          style={{ fontSize: "0.8rem", padding: "0.25rem 0.6rem" }}
          disabled={disabled || saving}
          onClick={useAllConcepts}
          title="关闭仅勾选，改为全概念扫描"
        >
          扫描全部概念
        </button>
      </div>
      <p style={{ fontSize: "0.78rem", color: "var(--muted)", margin: "0 0 0.5rem" }}>
        {useExplicit ? (
          <>
            已勾选 <strong>{selected.size}</strong> 个板块，扫描时仅处理勾选项。
            {selected.size === 0 ? "（请至少勾选一个）" : ""}
            {historySelectedCount > 0 ? ` 其中历史勾选 ${historySelectedCount} 个。` : ""}
          </>
        ) : (
          <>未启用勾选模式，扫描将覆盖全部概念。勾选任意板块会自动切换为「仅扫勾选」。</>
        )}
        {saving ? " 保存中…" : ""}
      </p>
      {error && (
        <p style={{ fontSize: "0.78rem", color: "var(--danger)", marginBottom: "0.5rem" }}>{error}</p>
      )}
      <div
        style={{
          maxHeight: "220px",
          overflowY: "auto",
          border: "1px solid var(--border)",
          borderRadius: "8px",
          padding: "0.5rem 0.75rem",
          background: "rgba(0,0,0,0.15)",
        }}
      >
        <p style={{ margin: "0 0 0.45rem", fontSize: "0.74rem", color: "var(--muted)" }}>
          已勾选项自动置顶；带「历史勾选」标签表示来自上一次保存的板块配置。
          {filtered.length > 0 ? ` 当前筛选命中 ${filtered.length} 个，已勾选 ${filteredCountBySelection} 个。` : ""}
        </p>
        {filtered.length === 0 ? (
          <p style={{ color: "var(--muted)", fontSize: "0.85rem" }}>无匹配板块</p>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0, columns: "min(280px, 100%) 2" }}>
            {filtered.map((c) => (
              <li key={c.sector_code} style={{ breakInside: "avoid", marginBottom: "0.35rem" }}>
                <label
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: "0.4rem",
                    fontSize: "0.82rem",
                    cursor: disabled || saving ? "not-allowed" : "pointer",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={isSelected(c.sector_code)}
                    disabled={disabled || saving}
                    onChange={() => toggle(c.sector_code)}
                  />
                  <span>
                    {c.sector_name}
                    <span style={{ color: "var(--muted)", marginLeft: "0.35rem", fontSize: "0.72rem" }}>
                      {c.sector_code}
                    </span>
                    {isSelected(c.sector_code) && (
                      <span
                        style={{
                          marginLeft: "0.35rem",
                          fontSize: "0.68rem",
                          color: isHistorySelected(c.sector_code) ? "#f59e0b" : "var(--muted)",
                        }}
                      >
                        {isHistorySelected(c.sector_code) ? "历史勾选" : "已勾选"}
                      </span>
                    )}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>

    <div style={{ marginTop: "0.85rem" }}>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.5rem",
          alignItems: "center",
          marginBottom: "0.45rem",
        }}
      >
        <label style={{ fontSize: "0.85rem", color: "var(--muted)" }}>勾选历史</label>
        <input
          type="text"
          placeholder="保存名称（可选）"
          value={historyLabel}
          onChange={(e) => setHistoryLabel(e.target.value)}
          disabled={disabled || saving}
          style={{ flex: "1 1 10rem", minWidth: "8rem", fontSize: "0.82rem" }}
        />
        <button
          type="button"
          className="btn btn-ghost"
          style={{ fontSize: "0.8rem", padding: "0.25rem 0.6rem" }}
          disabled={disabled || saving || selected.size === 0}
          onClick={() => void saveCurrentToHistory()}
        >
          保存当前勾选
        </button>
      </div>
      {scanHistory.length === 0 ? (
        <p style={{ fontSize: "0.78rem", color: "var(--muted)", margin: 0 }}>
          暂无历史记录，保存当前勾选后可快速恢复。
        </p>
      ) : (
        <ul
          style={{
            listStyle: "none",
            margin: 0,
            padding: 0,
            display: "flex",
            flexDirection: "column",
            gap: "0.35rem",
          }}
        >
          {scanHistory
            .slice()
            .reverse()
            .map((entry, idx) => (
              <li key={`${entry.saved_at}-${idx}`}>
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={disabled || saving}
                  onClick={() => void applyHistoryEntry(entry)}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    fontSize: "0.8rem",
                    padding: "0.4rem 0.65rem",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: "0.5rem",
                  }}
                >
                  <span>
                    <strong>{entry.label}</strong>
                    <span style={{ color: "var(--muted)", marginLeft: "0.5rem" }}>
                      {entry.codes.length} 个板块
                    </span>
                  </span>
                  <span style={{ color: "var(--muted)", fontSize: "0.72rem", flexShrink: 0 }}>
                    {formatHistoryDate(entry.saved_at)}
                  </span>
                </button>
              </li>
            ))}
        </ul>
      )}
    </div>
    </>
  );
}
