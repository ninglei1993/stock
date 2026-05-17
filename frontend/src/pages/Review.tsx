import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { pctClass, formatPct } from "../utils";

export default function Review() {
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [data, setData] = useState<{ trade_date: string; sectors: Array<{
    sector_code: string;
    sector_name: string;
    score: number;
    stage: string;
    future_pcts: number[];
  }> } | null>(null);
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true);
    api
      .review(date)
      .then((d) =>
        setData({
          trade_date: d.trade_date,
          sectors: d.sectors as Array<{
            sector_code: string;
            sector_name: string;
            score: number;
            stage: string;
            future_pcts: number[];
          }>,
        })
      )
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  return (
    <>
      <h2 className="page-title">复盘日历</h2>
      <div className="form-row">
        <div className="form-group">
          <label>交易日</label>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
        <button className="btn btn-primary" onClick={load} disabled={loading}>
          {loading ? "加载中…" : "查看复盘"}
        </button>
      </div>
      {data && (
        <div className="card">
          <p style={{ marginBottom: "1rem", color: "var(--muted)" }}>
            {data.trade_date} 当日 Top 主线及随后 5 日板块涨跌（%）
          </p>
          <table>
            <thead>
              <tr>
                <th>板块</th>
                <th>分数</th>
                <th>阶段</th>
                <th>后1日</th>
                <th>后2日</th>
                <th>后3日</th>
                <th>后4日</th>
                <th>后5日</th>
              </tr>
            </thead>
            <tbody>
              {data.sectors.map((s) => (
                <tr key={s.sector_code}>
                  <td>
                    <Link to={`/sectors/${s.sector_code}`}>{s.sector_name}</Link>
                  </td>
                  <td>{s.score.toFixed(0)}</td>
                  <td>{s.stage}</td>
                  {[0, 1, 2, 3, 4].map((i) => (
                    <td key={i}>
                      {s.future_pcts[i] !== undefined ? (
                        <span className={pctClass(s.future_pcts[i])}>
                          {formatPct(s.future_pcts[i])}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
