import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Package } from "lucide-react";
import { api } from "../api";
import type { AppTemplate, ConfigField } from "../api";

function InstallModal({ template, onClose, onInstalled }: {
  template: AppTemplate;
  onClose: () => void;
  onInstalled: () => void;
}) {
  const [name, setName] = useState(template.name);
  const [config, setConfig] = useState<Record<string, string>>(() =>
    Object.fromEntries(template.config_schema.map(f => [f.key, String(f.default ?? "")]))
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const resolvedConfig: Record<string, unknown> = {};
      for (const field of template.config_schema) {
        resolvedConfig[field.key] = field.type === "number" ? Number(config[field.key]) : config[field.key];
      }
      const { job } = await api.apps.install(template.slug, name, resolvedConfig);
      onInstalled();
      navigate(`/jobs/${job.id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Install failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-title">Install {template.name}</div>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">Instance Name</label>
            <input className="form-input" value={name} onChange={e => setName(e.target.value)} required />
          </div>
          {template.config_schema.map((field: ConfigField) => (
            <div key={field.key} className="form-group">
              <label className="form-label">{field.label}</label>
              <input
                className="form-input"
                type={field.type === "number" ? "number" : "text"}
                value={config[field.key] ?? ""}
                onChange={e => setConfig(c => ({ ...c, [field.key]: e.target.value }))}
                required={field.required}
              />
            </div>
          ))}
          {error && <div style={{ color: "var(--color-error)", fontSize: 13, marginBottom: 12 }}>{error}</div>}
          <div className="modal-actions">
            <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? <span className="spinner" /> : "Install"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function Library() {
  const [templates, setTemplates] = useState<AppTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [installing, setInstalling] = useState<AppTemplate | null>(null);

  useEffect(() => {
    api.templates.list().then(setTemplates).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="loading-center"><div className="spinner" /></div>;

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">App Library</div>
          <div className="page-subtitle">{templates.length} available templates</div>
        </div>
      </div>

      {templates.length === 0 ? (
        <div className="empty-state">
          <Package size={48} className="empty-state-icon" />
          <div className="empty-state-title">No templates available</div>
          <div className="empty-state-desc">Templates are seeded on startup. Check your server logs.</div>
        </div>
      ) : (
        <div className="grid-3">
          {templates.map(tmpl => (
            <div key={tmpl.id} className="card">
              <div className="app-card-header">
                {tmpl.icon_url ? (
                  <img src={tmpl.icon_url} className="app-card-icon" alt="" />
                ) : (
                  <div className="app-card-icon-placeholder">⬡</div>
                )}
                <div>
                  <div className="app-card-name">{tmpl.name}</div>
                  <div className="app-card-slug">{tmpl.slug}</div>
                </div>
              </div>
              <div className="app-card-desc">{tmpl.description}</div>
              <div className="app-card-footer">
                <div className="app-card-tags">
                  {(tmpl.provides as string[]).map(p => (
                    <span key={p} className="tag">{p}</span>
                  ))}
                </div>
                <button className="btn btn-primary btn-sm" onClick={() => setInstalling(tmpl)}>
                  Install
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {installing && (
        <InstallModal
          template={installing}
          onClose={() => setInstalling(null)}
          onInstalled={() => setInstalling(null)}
        />
      )}
    </div>
  );
}
