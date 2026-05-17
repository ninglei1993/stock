import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import Alerts from "./pages/Alerts";
import SectorDetail from "./pages/SectorDetail";
import Review from "./pages/Review";
import Backtest from "./pages/Backtest";
import Guide from "./pages/Guide";
import Sectors from "./pages/Sectors";

export default function App() {
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
            <NavLink to="/sectors-list" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              板块列表
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
            <NavLink to="/guide" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              使用指南
            </NavLink>
          </nav>
          <p className="disclaimer" style={{ marginTop: "2rem" }}>
            数据仅供参考，不构成投资建议。请自行决策并控制风险。
          </p>
        </aside>
        <main className="main">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/sectors-list" element={<Sectors />} />
            <Route path="/sectors/:code" element={<SectorDetail />} />
            <Route path="/review" element={<Review />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/backtest/:id" element={<Backtest />} />
            <Route path="/guide" element={<Guide />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
