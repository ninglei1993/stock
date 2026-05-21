import { useCallback, useState } from "react";
import { BrowserRouter, Navigate, NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import Alerts from "./pages/Alerts";
import SectorDetail from "./pages/SectorDetail";
import Review from "./pages/Review";
import Backtest from "./pages/Backtest";
import Guide from "./pages/Guide";
import AStrategy from "./pages/AStrategy";
import TaskStatusBar from "./components/TaskStatusBar";

export default function App() {
  const [refreshKey, setRefreshKey] = useState(0);
  const onScanDone = useCallback(() => setRefreshKey((k) => k + 1), []);

  return (
    <BrowserRouter>
      <div className="app-layout">
        <aside className="sidebar">
          <h1>主线雷达</h1>
          <p className="tagline">盘面先热，消息后吹</p>
          <nav>
            <NavLink to="/" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`} end>
              仪表盘
            </NavLink>
            <NavLink to="/alerts" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              预警中心
            </NavLink>
            <NavLink to="/review" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              复盘日历
            </NavLink>
            <NavLink to="/backtest" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              回测中心
            </NavLink>
            <NavLink to="/a-strategy" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              A策略
            </NavLink>
            <NavLink to="/guide" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              使用指南
            </NavLink>
          </nav>
          <p className="disclaimer" style={{ marginTop: "2rem" }}>
            数据仅供参考，不构成投资建议。请自行决策并控制风险。
          </p>
        </aside>
        <main className="main">
          <TaskStatusBar onDone={onScanDone} />
          <Routes>
            <Route path="/" element={<Dashboard key={refreshKey} />} />
            <Route path="/sectors-list" element={<Navigate to="/" replace />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/sectors/:code" element={<SectorDetail key={refreshKey} />} />
            <Route path="/review" element={<Review />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/backtest/:id" element={<Backtest />} />
            <Route path="/a-strategy" element={<AStrategy />} />
            <Route path="/guide" element={<Guide />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
