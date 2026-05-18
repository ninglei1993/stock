import { useEffect, useState } from "react";
import { api, SystemStatus } from "../api";

export default function DataSourceBadge({ compact = false }: { compact?: boolean }) {
  const [status, setStatus] = useState<SystemStatus | null>(null);

  useEffect(() => {
    const load = () =>
      api.systemStatus().then((s) => {
        if (import.meta.env.DEV) {
          console.log("[ThemeRadar] GET /api/system/status", s);
          if (s.scan_task?.status === "running") {
            console.log("[ThemeRadar] scan_task", s.scan_task);
          }
        }
        setStatus(s);
      }).catch(() => {});
    load();
    const t = setInterval(load, 60000);
    const onDs = () => load();
    window.addEventListener("themeradar:data-source-changed", onDs);
    return () => {
      clearInterval(t);
      window.removeEventListener("themeradar:data-source-changed", onDs);
    };
  }, []);

  if (!status) return null;

  const live = status.is_live_data;
  const cls = live ? "ds-badge ds-live" : "ds-badge ds-demo";
  const scopeLabel =
    status.scan_scope_label ||
    (status.use_explicit_sector_selection && status.selected_sector_count
      ? `已勾选 ${status.selected_sector_count} 个板块`
      : status.ingest_concept_filter
      ? `关键词「${status.ingest_concept_filter}」`
      : "");

  if (compact) {
    return (
      <span className={cls} title={status.data_source_label}>
        <span className="ds-dot" />
        {status.data_source_short || (live ? "实盘" : "演示")}
      </span>
    );
  }

  return (
    <div className={`card-glass ${cls}`} style={{ marginBottom: "1rem", padding: "0.75rem 1rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
        <span className="ds-dot" />
        <strong>{status.data_source_label}</strong>
        <span style={{ color: "var(--muted)", fontSize: "0.85rem" }}>
          · 概念 {status.universe_total} 个
          {status.jq_configured ? "" : " · 未配置聚宽账号"}
          {status.jq_data_range
            ? ` · 数据权限 ${status.jq_data_range.start} ~ ${status.jq_data_range.end}`
            : ""}
          {scopeLabel ? ` · 扫描范围：${scopeLabel}` : ""}
          {status.scan_volatile_storage ? " · 扫描仅内存不写库" : ""}
        </span>
      </div>
      {live && status.jq_data_range && (
        <p style={{ marginTop: "0.5rem", fontSize: "0.8rem", color: "var(--muted)" }}>
          默认扫描交易日：<strong>{status.default_scan_date || status.jq_data_range.latest_trade_day}</strong>
          （权限内最后交易日，非系统当天日期）
        </p>
      )}
      {!live && (
        <p style={{ marginTop: "0.5rem", fontSize: "0.8rem", color: "var(--muted)" }}>
          当前为演示数据：仅约 20 个内置概念，股票代码为随机合成。请在 .env 填写聚宽账号并设置
          DEMO_MODE=false 后执行 docker compose restart api。
        </p>
      )}
    </div>
  );
}
