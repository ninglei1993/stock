import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, SectorList, SectorScore } from "../api";
import { STAGE_LABEL, POSITION_LABEL, pctClass, formatPct } from "../utils";

const STAGES = ["", "sprout", "ferment", "climax", "decay", "dormant"];

export default function Sectors() {
  const [data, setData] = useState<SectorList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [stageFilter, setStageFilter] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    api
      .listSectors()
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    if (!data?.sectors) return [];
    return data.sectors.filter((s) => {
      if (stageFilter && s.stage !== stageFilter) return false;
      if (search) {
        const q = search.toLowerCase();
        return (
          s.sector_name.toLowerCase().includes(q) ||
          s.sector_code.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [data, stageFilter, search]);

  if (loading) return <div className="loading">加载中…</div>;
  if (error) return <div className="error">{error}</div>;

  return (
    <>
      <h2 className="page-title">板块列表</h2>
      <p className="page-subtitle">
        展示当前扫描日全部已评分板块及五维得分。概念全集 {data?.universe_total ?? 0} 个，
        已评分 {data?.sectors_scored ?? 0} 个
        {data?.trade_date ? ` · ${data.trade_date}` : ""}
      </p>

      {data?.demo_mode && (
        <div className="card-glass demo-banner" style={{ marginBottom: "1rem" }}>
          <strong>演示模式</strong>：仅含内置 {data.universe_total} 个概念，行情为合成数据，不代表
          2026 年真实半导体/算力走势。接入聚宽 JQData 后可扫描全市场概念。
        </div>
      )}

      <div className="form-row" style={{ marginBottom: "1rem" }}>
        <div className="form-group">
          <label>阶段筛选</label>
          <select value={stageFilter} onChange={(e) => setStageFilter(e.target.value)}>
            {STAGES.map((st) => (
              <option key={st || "all"} value={st}>
                {st ? STAGE_LABEL[st] : "全部阶段"}
              </option>
            ))}
          </select>
        </div>
        <div className="form-group" style={{ flex: 1 }}>
          <label>搜索板块</label>
          <input
            type="text"
            placeholder="名称或代码"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {!data?.sectors.length ? (
        <div className="card-glass">
          <p style={{ color: "var(--muted)" }}>
            暂无评分数据，请先在仪表盘执行「收盘扫描」。
          </p>
          <Link to="/" className="btn btn-primary" style={{ marginTop: "1rem", display: "inline-block" }}>
            前往仪表盘
          </Link>
        </div>
      ) : (
        <div className="card-glass sectors-table-wrap">
          <table className="sectors-table">
            <thead>
              <tr>
                <th>排名</th>
                <th>板块</th>
                <th>阶段</th>
                <th>综合分</th>
                <th>涨跌幅</th>
                <th>持续</th>
                <th>资金</th>
                <th>广度</th>
                <th>龙头</th>
                <th>相对</th>
                <th>建议</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((s) => (
                <SectorRow key={s.sector_code} s={s} />
              ))}
            </tbody>
          </table>
          {filtered.length === 0 && (
            <p style={{ padding: "1rem", color: "var(--muted)" }}>无匹配板块</p>
          )}
        </div>
      )}
    </>
  );
}

function SectorRow({ s }: { s: SectorScore }) {
  return (
    <tr className={s.is_filtered ? "row-filtered" : ""}>
      <td>{s.rank}</td>
      <td>
        <div style={{ fontWeight: 600 }}>{s.sector_name}</div>
        <div style={{ fontSize: "0.72rem", color: "var(--muted)", fontFamily: "JetBrains Mono" }}>
          {s.sector_code}
        </div>
        {s.is_filtered && s.filter_reason && (
          <div className="filter-tag">{s.filter_reason}</div>
        )}
      </td>
      <td>
        <span className={`stage-badge stage-${s.stage}`}>{STAGE_LABEL[s.stage] || s.stage}</span>
      </td>
      <td>
        <span className="score-cell">{s.total_score.toFixed(0)}</span>
      </td>
      <td className={pctClass(s.pct_change ?? 0)}>
        {s.pct_change !== undefined && s.pct_change !== null ? formatPct(s.pct_change) : "—"}
      </td>
      <td className="dim-cell">{s.persistence_score.toFixed(0)}</td>
      <td className="dim-cell">{s.capital_score.toFixed(0)}</td>
      <td className="dim-cell">{s.breadth_score.toFixed(0)}</td>
      <td className="dim-cell">{s.leader_score.toFixed(0)}</td>
      <td className="dim-cell">{s.relative_score.toFixed(0)}</td>
      <td style={{ fontSize: "0.8rem" }}>{POSITION_LABEL[s.position_hint] || s.position_hint}</td>
      <td>
        <Link to={`/sectors/${s.sector_code}`} className="btn-link">
          详情
        </Link>
      </td>
    </tr>
  );
}
