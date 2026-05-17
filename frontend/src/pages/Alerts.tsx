import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Alert } from "../api";
import { ALERT_LABEL } from "../utils";

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    api
      .alerts()
      .then(setAlerts)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const filtered = filter ? alerts.filter((a) => a.alert_code === filter) : alerts;

  if (loading) return <div className="loading">加载中…</div>;

  return (
    <>
      <h2 className="page-title">预警中心</h2>
      <div className="form-row">
        <div className="form-group">
          <label>类型筛选</label>
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">全部</option>
            {Object.entries(ALERT_LABEL).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="card-glass">
        {filtered.length === 0 ? (
          <p style={{ color: "var(--muted)" }}>暂无预警，请先执行收盘扫描</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>日期</th>
                <th>类型</th>
                <th>板块</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((a) => (
                <tr key={a.id}>
                  <td>{a.trade_date}</td>
                  <td>
                    <span className="stage-badge stage-ferment">
                      {ALERT_LABEL[a.alert_code] || a.alert_code}
                    </span>
                  </td>
                  <td>
                    {a.sector_code !== "MARKET" ? (
                      <Link to={`/sectors/${a.sector_code}`}>{a.sector_name}</Link>
                    ) : (
                      a.sector_name
                    )}
                  </td>
                  <td style={{ maxWidth: 400 }}>{a.human_reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
