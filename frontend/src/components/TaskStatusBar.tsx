import { useEffect, useRef, useState } from "react";
import { api, TaskStatus } from "../api";

export default function TaskStatusBar({ onDone }: { onDone?: () => void }) {
  const [task, setTask] = useState<TaskStatus | null>(null);
  const doneNotified = useRef(false);

  useEffect(() => {
    const poll = () => {
      api
        .scanTaskStatus()
        .then((t) => {
          setTask(t);
          if (t.status === "running") doneNotified.current = false;
          if (t.status === "done" && onDone && !doneNotified.current) {
            doneNotified.current = true;
            onDone();
          }
        })
        .catch(() => {});
    };
    poll();
    const t = setInterval(poll, 2000);
    return () => clearInterval(t);
  }, [onDone]);

  if (!task || task.status === "idle") return null;

  const running = task.status === "running";
  const failed = task.status === "failed";
  const done = task.status === "done";

  const pct =
    task.total > 0 ? Math.min(100, Math.round((task.progress / task.total) * 100)) : running ? undefined : 100;

  return (
    <div className={`task-status-bar ${running ? "task-running" : failed ? "task-failed" : "task-done"}`}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "1rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          {running && <span className="task-spinner" aria-hidden />}
          <strong>
            {running ? "后台任务进行中" : failed ? "后台任务失败" : "后台任务已完成"}
          </strong>
          <span style={{ fontSize: "0.88rem", opacity: 0.9 }}>{task.message}</span>
        </div>
        {task.trade_date && (
          <span style={{ fontSize: "0.8rem", opacity: 0.75 }}>交易日 {task.trade_date}</span>
        )}
      </div>
      {running && (
        <div className="task-progress-track">
          <div
            className="task-progress-fill"
            style={{ width: pct != null ? `${pct}%` : "30%", animation: pct == null ? undefined : "none" }}
          />
        </div>
      )}
      {failed && task.error && (
        <p style={{ marginTop: "0.5rem", fontSize: "0.8rem" }}>{task.error}</p>
      )}
      {done && (
        <p style={{ marginTop: "0.35rem", fontSize: "0.8rem", opacity: 0.85 }}>
          可刷新板块列表查看最新评分
        </p>
      )}
    </div>
  );
}
