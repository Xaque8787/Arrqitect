import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Server } from "lucide-react";
import { api } from "../api";
import type { InstalledApp, Job } from "../api";

export default function Dashboard() {
  const [apps, setApps] = useState<InstalledApp[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.apps.list(), api.jobs.list()])
      .then(([a, j]) => { setApps(a); setJobs(j); })
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="loading-center"><div className="spinner" /></div>;

  const running = apps.filter(a => a.state === "running").length;
  const errored = apps.filter(a => a.state === "error").length;
  const recentJobs = jobs.slice(0, 8);

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Dashboard</div>
          <div className="page-subtitle">Platform overview</div>
        </div>
      </div>

      <div className="stats-row">
        <div className="stat-card">
          <div className="stat-value">{apps.length}</div>
          <div className="stat-label">Installed apps</div>
        </div>
        <div className="stat-card">
          <div className="stat-value" style={{ color: "var(--color-success)" }}>{running}</div>
          <div className="stat-label">Running</div>
        </div>
        <div className="stat-card">
          <div className="stat-value" style={{ color: errored > 0 ? "var(--color-error)" : undefined }}>{errored}</div>
          <div className="stat-label">Errors</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{jobs.length}</div>
          <div className="stat-label">Total jobs</div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
        <div>
          <div className="detail-section-title" style={{ marginBottom: 12 }}>Installed Apps</div>
          {apps.length === 0 ? (
            <div className="empty-state" style={{ padding: "32px 0" }}>
              <Server size={32} className="empty-state-icon" />
              <div className="empty-state-title">No apps installed</div>
              <Link to="/library" className="btn btn-primary btn-sm" style={{ marginTop: 8 }}>Browse Library</Link>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {apps.map(app => (
                <Link key={app.id} to={`/apps/${app.id}`} style={{ textDecoration: "none" }}>
                  <div className="card" style={{ padding: "12px 16px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      {app.app_templates?.icon_url ? (
                        <img src={app.app_templates.icon_url} className="app-card-icon" alt="" style={{ width: 28, height: 28 }} />
                      ) : (
                        <div className="app-card-icon-placeholder" style={{ width: 28, height: 28, fontSize: 14 }}>⬡</div>
                      )}
                      <span style={{ fontSize: 13, fontWeight: 500, color: "var(--color-text)" }}>{app.name}</span>
                    </div>
                    <span className={`badge badge-${app.state}`}>{app.state}</span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>

        <div>
          <div className="detail-section-title" style={{ marginBottom: 12 }}>Recent Jobs</div>
          {recentJobs.length === 0 ? (
            <div className="empty-state" style={{ padding: "32px 0" }}>
              <div className="empty-state-title">No jobs yet</div>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {recentJobs.map(job => (
                <Link key={job.id} to={`/jobs/${job.id}`} style={{ textDecoration: "none" }}>
                  <div className="card" style={{ padding: "12px 16px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <div>
                      <span style={{ fontSize: 13, fontWeight: 500, color: "var(--color-text)" }}>{job.type}</span>
                      {job.dry_run && <span className="tag" style={{ marginLeft: 6 }}>dry run</span>}
                    </div>
                    <span className={`badge badge-${job.status}`}>{job.status}</span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
