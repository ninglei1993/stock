import { useEffect, useState } from "react";
import { api, DataSourcesResponse } from "../api";

export default function DataSourceSelector() {
  const [sources, setSources] = useState<DataSourcesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = () => {
    api.dataSources().then(setSources).catch(() => {});
  };

  useEffect(() => {
    load();
    const onChanged = () => load();
    window.addEventListener("themeradar:data-source-changed", onChanged);
    return () => window.removeEventListener("themeradar:data-source-changed", onChanged);
  }, []);

  const onChange = async (source: string) => {
    if (sources?.current === source) return;
    setLoading(true);
    setError("");
    try {
      await api.setDataSource(source);
      load();
      window.dispatchEvent(new CustomEvent("themeradar:data-source-changed"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "切换失败");
    } finally {
      setLoading(false);
    }
  };

  if (!sources) return null;

  return (
    <div className="card-glass ds-selector" style={{ marginBottom: "1rem", padding: "0.85rem 1.1rem" }}>
      <div style={{ fontSize: "0.85rem", color: "var(--muted)", marginBottom: "0.65rem" }}>
        行情数据源
        {sources.active_adapter && (
          <span style={{ marginLeft: "0.5rem" }}>
            当前适配器：<strong>{sources.active_adapter}</strong>
          </span>
        )}
      </div>
      <div className="ds-options">
        {sources.options.filter((o) => o.id !== "demo").map((o) => (
          <label
            key={o.id}
            className={`ds-option ${o.active ? "ds-option-active" : ""} ${!o.configured && o.id !== "demo" ? "ds-option-disabled" : ""}`}
          >
            <input
              type="radio"
              name="data_source"
              value={o.id}
              checked={o.active}
              disabled={loading || (!o.configured && o.id !== "demo")}
              onChange={() => onChange(o.id)}
            />
            <span>
              <strong>{o.label}</strong>
              <small>{o.description}</small>
            </span>
          </label>
        ))}
      </div>
      {loading && <p style={{ fontSize: "0.8rem", color: "var(--muted)", marginTop: "0.5rem" }}>切换中…</p>}
      {error && <p style={{ fontSize: "0.8rem", color: "var(--danger)", marginTop: "0.5rem" }}>{error}</p>}
    </div>
  );
}
