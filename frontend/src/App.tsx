import { useCallback, useState } from "react";
import { BrowserRouter, Navigate, NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import ScanPanel from "./pages/ScanPanel";
import SectorDetail from "./pages/SectorDetail";
import AStrategyDetail from "./pages/AStrategyDetail";
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
            <NavLink to="/scan" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              扫盘
            </NavLink>
            <NavLink to="/a-strategy" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              A策略
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
            <Route path="/scan" element={<ScanPanel key={refreshKey} />} />
            <Route path="/a-strategy" element={<AStrategyDetail key={refreshKey} />} />
            <Route path="/sectors-list" element={<Navigate to="/scan" replace />} />
            <Route path="/sectors/:code" element={<SectorDetail key={refreshKey} />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
