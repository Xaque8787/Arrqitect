import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import { LayoutDashboard, Package, Server, Settings } from "lucide-react";
import Dashboard from "./views/Dashboard";
import Library from "./views/Library";
import InstalledApps from "./views/InstalledApps";
import AppDetail from "./views/AppDetail";
import JobLog from "./views/JobLog";
import SettingsPage from "./views/Settings";
import "./App.css";

function Nav() {
  const links = [
    { to: "/", label: "Dashboard", icon: LayoutDashboard },
    { to: "/library", label: "App Library", icon: Package },
    { to: "/apps", label: "Installed", icon: Server },
  ];
  return (
    <nav className="sidebar">
      <div className="sidebar-brand">
        <span className="brand-icon">⬡</span>
        <span className="brand-name">Arrqitect</span>
      </div>
      <ul className="sidebar-nav">
        {links.map(({ to, label, icon: Icon }) => (
          <li key={to}>
            <NavLink to={to} end={to === "/"} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
              <Icon size={16} />
              <span>{label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
      <div className="sidebar-footer">
        <NavLink to="/settings" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
          <Settings size={16} />
          <span>Settings</span>
        </NavLink>
        <span className="version-badge">v1</span>
      </div>
    </nav>
  );
}

function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="layout">
      <Nav />
      <main className="main-content">{children}</main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/library" element={<Library />} />
          <Route path="/apps" element={<InstalledApps />} />
          <Route path="/apps/:id" element={<AppDetail />} />
          <Route path="/jobs/:id" element={<JobLog />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
