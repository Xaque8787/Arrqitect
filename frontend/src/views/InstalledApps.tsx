import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Server, CircleArrowUp as ArrowUpCircle } from "lucide-react";
import { api } from "../api";
import type { InstalledApp } from "../api";

export default function InstalledApps() {
  const [apps, setApps] = useState<InstalledApp[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.apps.list().then(setApps).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="loading-center"><div className="spinner" /></div>;

  const updatesAvailable = apps.filter(
    a => a.app_templates?.installed_version &&
         a.app_templates?.latest_version &&
         a.app_templates.installed_version !== a.app_templates.latest_version
  );

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Installed Apps</div>
          <div className="page-subtitle">{apps.length} app{apps.length !== 1 ? "s" : ""} installed</div>
        </div>
        <Link to="/library" className="btn btn-primary btn-sm">+ Install App</Link>
      </div>

      {updatesAvailable.length > 0 && (
        <div className="updates-banner">
          <ArrowUpCircle size={18} style={{ color: "var(--color-primary)", flexShrink: 0 }} />
          <div style={{ flex: 1, fontSize: 13, color: "var(--color-primary)", fontWeight: 600 }}>
            {updatesAvailable.length} app{updatesAvailable.length !== 1 ? "s have" : " has"} updates available
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {updatesAvailable.map(a => (
              <Link key={a.id} to={`/apps/${a.id}`} className="btn btn-ghost btn-sm" style={{ fontSize: 11 }}>
                {a.name}
              </Link>
            ))}
          </div>
        </div>
      )}

      {apps.length === 0 ? (
        <div className="empty-state">
          <Server size={48} className="empty-state-icon" />
          <div className="empty-state-title">No apps installed yet</div>
          <div className="empty-state-desc">Head to the App Library to install your first app.</div>
          <Link to="/library" className="btn btn-primary" style={{ marginTop: 8 }}>Browse Library</Link>
        </div>
      ) : (
        <div className="grid-3">
          {apps.map(app => (
            <Link key={app.id} to={`/apps/${app.id}`} style={{ textDecoration: "none" }}>
              <div className="card">
                <div className="app-card-header">
                  {app.app_templates?.icon_url ? (
                    <img src={app.app_templates.icon_url} className="app-card-icon" alt="" />
                  ) : (
                    <div className="app-card-icon-placeholder">⬡</div>
                  )}
                  <div>
                    <div className="app-card-name">{app.name}</div>
                    <div className="app-card-slug">{app.slug}</div>
                  </div>
                </div>
                <div className="app-card-footer">
                  <span className={`badge badge-${app.state}`}>{app.state}</span>
                  {app.app_templates?.installed_version && app.app_templates.latest_version &&
                    app.app_templates.installed_version !== app.app_templates.latest_version && (
                    <span className="badge badge-update">update available</span>
                  )}
                  <span style={{ fontSize: 12, color: "var(--color-text-dim)" }}>
                    {new Date(app.created_at).toLocaleDateString()}
                  </span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
