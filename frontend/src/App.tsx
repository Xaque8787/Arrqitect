import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import { LayoutDashboard, Package, Server, Settings, ListOrdered } from "lucide-react";
import { QueueProvider, useQueue } from "./QueueContext";
import Dashboard from "./views/Dashboard";
import Library from "./views/Library";
import InstalledApps from "./views/InstalledApps";
import AppDetail from "./views/AppDetail";
import JobLog from "./views/JobLog";
import SettingsPage from "./views/Settings";
import "./App.css";

function QueueBadge() {
  const { count } = useQueue();
  if (count === 0) return null;
  return (
    <span style={{
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      minWidth: 18,
      height: 18,
      padding: "0 5px",
      borderRadius: 9,
      background: "var(--color-primary)",
      color: "#fff",
      fontSize: 11,
      fontWeight: 700,
      lineHeight: 1,
      marginLeft: "auto",
    }}>
      {count}
    </span>
  );
}

function Nav() {
  const links = [
    { to: "/", label: "Dashboard", icon: LayoutDashboard, badge: null },
    { to: "/library", label: "App Library", icon: Package, badge: null },
    { to: "/apps", label: "Installed", icon: Server, badge: null },
    { to: "/queue", label: "Install Queue", icon: ListOrdered, badge: <QueueBadge /> },
  ];
  return (
    <nav className="sidebar">
      <div className="sidebar-brand">
        <span className="brand-icon">⬡</span>
        <span className="brand-name">Arrqitect</span>
      </div>
      <ul className="sidebar-nav">
        {links.map(({ to, label, icon: Icon, badge }) => (
          <li key={to}>
            <NavLink to={to} end={to === "/"} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
              <Icon size={16} />
              <span style={{ flex: 1 }}>{label}</span>
              {badge}
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

// Lazy import for Queue view
import Queue from "./views/Queue";

export default function App() {
  return (
    <BrowserRouter>
      <QueueProvider>
        <Layout>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/library" element={<Library />} />
            <Route path="/apps" element={<InstalledApps />} />
            <Route path="/apps/:id" element={<AppDetail />} />
            <Route path="/queue" element={<Queue />} />
            <Route path="/jobs/:id" element={<JobLog />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </Layout>
      </QueueProvider>
    </BrowserRouter>
  );
}
