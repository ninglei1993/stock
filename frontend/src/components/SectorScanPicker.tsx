import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ConceptItem } from "../api";

type Props = {
  disabled?: boolean;
};

export default function SectorScanPicker({ disabled }: Props) {
  const [universe, setUniverse] = useState<ConceptItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [useExplicit, setUseExplicit] = useState(false);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    api
      .getScanSectors()
      .then((res) => {
        setUniverse(res.universe);
        setSelected(new Set(res.selected_codes));
        setUseExplicit(res.use_explicit_selection);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "加载板块失败"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = useMemo(() => {
    const q = filter.trim().toUpperCase();
    if (!q) return universe;
    return universe.filter(
      (c) =>
        c.sector_name.toUpperCase().includes(q) ||
        c.sector_code.toUpperCase().includes(q)
    );
  }, [universe, filter]);

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

  const useEnvFilter = () => {
    setUseExplicit(false);
    void persist(selected, false);
  };

  if (loading) {
    return (
      <p style={{ fontSize: "0.85rem", color: "var(--muted)", margin: "0.5rem 0 0" }}>
        正在加载概念板块列表…
      </p>
    );
  }

  return (
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
          onClick={useEnvFilter}
          title="改用 .env 中 INGEST_CONCEPT_FILTER / INGEST_MAX_CONCEPTS"
        >
          使用环境关键词
        </button>
      </div>
      <p style={{ fontSize: "0.78rem", color: "var(--muted)", margin: "0 0 0.5rem" }}>
        {useExplicit ? (
          <>
            已勾选 <strong>{selected.size}</strong> 个板块，扫描时仅处理勾选项。
            {selected.size === 0 ? "（请至少勾选一个）" : ""}
          </>
        ) : (
          <>未启用勾选模式，扫描使用环境变量关键词筛选（见 .env）。勾选任意板块将自动切换为「仅扫勾选」。</>
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
                    checked={selected.has(c.sector_code)}
                    disabled={disabled || saving}
                    onChange={() => toggle(c.sector_code)}
                  />
                  <span>
                    {c.sector_name}
                    <span style={{ color: "var(--muted)", marginLeft: "0.35rem", fontSize: "0.72rem" }}>
                      {c.sector_code}
                    </span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
