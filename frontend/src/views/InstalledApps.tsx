import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Server } from "lucide-react";
import { api } from "../api";
import type { InstalledApp } from "../api";

export default function InstalledApps() {
  const [apps, setApps] = useState<InstalledApp[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.apps.list().then(setApps).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="loading-center"><div className="spinner" /></div>;

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Installed Apps</div>
          <div className="page-subtitle">{apps.length} app{apps.length !== 1 ? "s" : ""} installed</div>
        </div>
        <Link to="/library" className="btn btn-primary btn-sm">+ Install App</Link>
      </div>

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
