import { useEffect, useRef, useState } from "react";
import { api, TaskStatus } from "../api";

export default function TaskStatusBar({ onDone }: { onDone?: () => void }) {
  const [task, setTask] = useState<TaskStatus | null>(null);
  const doneNotified = useRef(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const apply = (t: TaskStatus) => {
      if (import.meta.env.DEV) {
        console.log("[ThemeRadar] GET /api/tasks/scan", t);
      }
      setTask(t.status === "idle" ? null : t);
      window.dispatchEvent(new CustomEvent("themeradar:scan-task", { detail: t }));
      if (t.status === "running") {
        doneNotified.current = false;
        if (!intervalRef.current) {
          intervalRef.current = setInterval(poll, 2000);
        }
      } else {
        if (intervalRef.current) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
        if (t.status === "done" && !doneNotified.current) {
          doneNotified.current = true;
          window.dispatchEvent(
            new CustomEvent("themeradar:scan-complete", { detail: t })
          );
          if (onDone) onDone();
        }
      }
    };

    const poll = () => {
      api.scanTaskStatus().then(apply).catch(() => {});
    };

    poll();
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [onDone]);

  if (!task) return null;

  const running = task.status === "running";
  const failed = task.status === "failed";
  const done = task.status === "done";

  const pct =
    task.total > 0
      ? Math.min(100, Math.round((task.progress / task.total) * 100))
      : running
      ? undefined
      : 100;
  const elapsedSec =
    running && task.started_at ? Math.max(0, (Date.now() - Date.parse(task.started_at)) / 1000) : 0;
  const etaSec =
    running && task.total > 0 && task.progress > 0
      ? Math.max(0, (elapsedSec / task.progress) * (task.total - task.progress))
      : null;
  const etaLabel =
    etaSec == null
      ? ""
      : etaSec < 60
      ? `预计剩余约 ${Math.round(etaSec)} 秒`
      : `预计剩余约 ${Math.ceil(etaSec / 60)} 分钟`;

  const dateRange =
    task.scan_start_date && task.scan_end_date
      ? task.scan_start_date === task.scan_end_date
        ? task.scan_start_date
        : `${task.scan_start_date} ~ ${task.scan_end_date}`
      : task.trade_date ?? "";

  return (
    <div
      className={`task-status-bar ${
        running ? "task-running" : failed ? "task-failed" : "task-done"
      }`}
    >
      {/* 头部：状态标题 + 日期 */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "1rem",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          {running && <span className="task-spinner" aria-hidden />}
          <strong>
            {running ? "后台扫描中" : failed ? "扫描失败" : "扫描完成"}
          </strong>
          {dateRange && (
            <span
              style={{
                fontSize: "0.82rem",
                opacity: 0.8,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {dateRange}
            </span>
          )}
        </div>
        {running && pct != null && (
          <span
            style={{
              fontSize: "0.88rem",
              fontWeight: 600,
              fontVariantNumeric: "tabular-nums",
              minWidth: "3.2rem",
              textAlign: "right",
            }}
          >
            {pct}%
          </span>
        )}
      </div>

      {/* 进度条 */}
      {(running || done) && (
        <div className="task-progress-track" style={{ marginTop: "0.45rem" }}>
          <div
            className="task-progress-fill"
            style={{
              width: pct != null ? `${pct}%` : "15%",
              animation: pct == null ? undefined : "none",
              transition: "width 0.4s ease",
            }}
          />
        </div>
      )}

      {/* 当前步骤说明 */}
      {running && task.message && (
        <p
          style={{
            marginTop: "0.3rem",
            fontSize: "0.8rem",
            opacity: 0.85,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {task.message}
          {task.total > 0 && (
            <span style={{ opacity: 0.6, marginLeft: "0.4rem" }}>
              ({task.progress}/{task.total} 步)
            </span>
          )}
          {etaLabel && <span style={{ opacity: 0.6, marginLeft: "0.6rem" }}>· {etaLabel}</span>}
        </p>
      )}

      {failed && task.error && (
        <p style={{ marginTop: "0.5rem", fontSize: "0.8rem" }}>{task.error}</p>
      )}

      {done && (
        <p style={{ marginTop: "0.35rem", fontSize: "0.8rem", opacity: 0.85 }}>
          {task.message || "扫描结果已同步至仪表盘，点击板块卡片可查看详情"}
        </p>
      )}
    </div>
  );
}
