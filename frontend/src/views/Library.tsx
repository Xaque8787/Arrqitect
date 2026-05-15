import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Package, RefreshCw, CircleCheck as CheckCircle, CircleAlert as AlertCircle } from "lucide-react";
import { api, resolveHostPath, fieldPlaceholder } from "../api";
import type { AppTemplate, ConfigField, SyncResult } from "../api";

function StoragePathField({
  field,
  value,
  onChange,
  appSlug,
  composeBase,
}: {
  field: ConfigField;
  value: string;
  onChange: (v: string) => void;
  appSlug: string;
  composeBase: string | null;
}) {
  const isRelative = value && !value.startsWith("/");
  const resolved = isRelative && composeBase
    ? resolveHostPath(value, appSlug, composeBase)
    : null;

  return (
    <div className="volume-mount-field">
      <div className="volume-mount-label">{field.label}</div>
      <div className="volume-mount-host">
        <div className="volume-side-tag volume-side-host">Host Path</div>
        <input
          className="form-input"
          value={value}
          onChange={e => onChange(e.target.value)}
          required={field.required}
          placeholder={fieldPlaceholder(field)}
        />
        {resolved && (
          <div className="volume-resolved">
            <span className="volume-resolved-arrow">↳</span>
            <code>{resolved}</code>
          </div>
        )}
      </div>
    </div>
  );
}

function ConfigFieldInput({
  field,
  value,
  onChange,
  appSlug,
  composeBase,
}: {
  field: ConfigField;
  value: string;
  onChange: (v: string) => void;
  appSlug: string;
  composeBase: string | null;
}) {
  if (field.type === "storage_path") {
    return (
      <StoragePathField
        field={field}
        value={value}
        onChange={onChange}
        appSlug={appSlug}
        composeBase={composeBase}
      />
    );
  }
  if (field.ui_widget === "select" && field.allowed_values?.length) {
    return (
      <div className="form-group">
        <label className="form-label">{field.label}</label>
        <select
          className="form-input"
          value={value}
          onChange={e => onChange(e.target.value)}
          required={field.required}
        >
          {field.allowed_values.map(v => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      </div>
    );
  }
  return (
    <div className="form-group">
      <label className="form-label">{field.label}</label>
      <input
        className="form-input"
        type={field.type === "number" || field.type === "port" ? "number" : "text"}
        value={value}
        onChange={e => onChange(e.target.value)}
        required={field.required}
        placeholder={fieldPlaceholder(field)}
      />
    </div>
  );
}

function InstallModal({ template, composeBase, onClose, onInstalled }: {
  template: AppTemplate;
  composeBase: string | null;
  onClose: () => void;
  onInstalled: () => void;
}) {
  const [name, setName] = useState(template.name);
  const [config, setConfig] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      template.config_schema.map(f => [f.id, f.default != null ? String(f.default) : ""])
    )
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const visibleFields = template.config_schema.filter(f => (f.visibility ?? "visible") === "visible");
  const advancedFields = template.config_schema.filter(f => (f.visibility ?? "visible") === "advanced");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const resolvedConfig: Record<string, unknown> = {};
      for (const field of template.config_schema) {
        resolvedConfig[field.id] = field.type === "number" || field.type === "port"
          ? Number(config[field.id])
          : config[field.id];
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
      <div className="modal modal-wide" onClick={e => e.stopPropagation()}>
        <div className="modal-title">Install {template.name}</div>

        {template.latest_version && (
          <div className="modal-version-badge">v{template.latest_version}</div>
        )}

        <div className="modal-global-note">
          <span>PUID, PGID, and Timezone are set globally in</span>
          <a href="/settings" className="inline-link" onClick={e => e.stopPropagation()}>Settings</a>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">Instance Name</label>
            <input
              className="form-input"
              value={name}
              onChange={e => setName(e.target.value)}
              required
            />
          </div>

          {visibleFields.map(field => (
            <ConfigFieldInput
              key={field.id}
              field={field}
              value={config[field.id] ?? ""}
              onChange={v => setConfig(c => ({ ...c, [field.id]: v }))}
              appSlug={template.slug}
              composeBase={composeBase}
            />
          ))}

          {advancedFields.length > 0 && (
            <details className="advanced-section">
              <summary className="advanced-section-toggle">Advanced</summary>
              <div className="advanced-section-body">
                {advancedFields.map(field => (
                  <ConfigFieldInput
                    key={field.id}
                    field={field}
                    value={config[field.id] ?? ""}
                    onChange={v => setConfig(c => ({ ...c, [field.id]: v }))}
                    appSlug={template.slug}
                    composeBase={composeBase}
                  />
                ))}
              </div>
            </details>
          )}

          {error && <div className="form-error">{error}</div>}

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

function SyncStatusBanner({ result, onDismiss }: { result: SyncResult; onDismiss: () => void }) {
  const added = result.results.filter(r => r.status === "added").length;
  const unchanged = result.results.filter(r => r.status === "unchanged").length;
  const hasErrors = result.errors.length > 0;

  return (
    <div className={`sync-banner ${hasErrors ? "sync-banner-warn" : "sync-banner-ok"}`}>
      <div className="sync-banner-content">
        {hasErrors ? <AlertCircle size={14} /> : <CheckCircle size={14} />}
        <span>
          Sync complete —{" "}
          {added > 0 && <strong>{added} new</strong>}
          {added > 0 && unchanged > 0 && ", "}
          {unchanged > 0 && <span>{unchanged} unchanged</span>}
          {hasErrors && (
            <span className="sync-banner-errors">
              {" "}· {result.errors.length} error{result.errors.length !== 1 ? "s" : ""}:{" "}
              {result.errors.map(e => e.slug).join(", ")}
            </span>
          )}
        </span>
      </div>
      <button className="sync-banner-dismiss" onClick={onDismiss} aria-label="Dismiss">×</button>
    </div>
  );
}

export default function Library() {
  const [templates, setTemplates] = useState<AppTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<SyncResult | null>(null);
  const [installing, setInstalling] = useState<AppTemplate | null>(null);
  const [composeBase, setComposeBase] = useState<string | null>(null);

  useEffect(() => {
    loadTemplates();
    api.settings.composeBase().then(r => {
      if (r.host_path) setComposeBase(r.host_path);
    });
  }, []);

  function loadTemplates() {
    setLoading(true);
    api.templates.list().then(setTemplates).finally(() => setLoading(false));
  }

  async function handleSync() {
    setSyncing(true);
    setSyncResult(null);
    try {
      const result = await api.templates.sync();
      setSyncResult(result);
      loadTemplates();
    } catch (err) {
      setSyncResult({
        ok: false,
        error: err instanceof Error ? err.message : "Sync failed",
        results: [],
        errors: [],
      });
    } finally {
      setSyncing(false);
    }
  }

  if (loading) return <div className="loading-center"><div className="spinner" /></div>;

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">App Library</div>
          <div className="page-subtitle">{templates.length} available template{templates.length !== 1 ? "s" : ""}</div>
        </div>
        <button
          className="btn btn-ghost"
          onClick={handleSync}
          disabled={syncing}
        >
          <RefreshCw size={14} className={syncing ? "spin" : ""} />
          {syncing ? "Syncing…" : "Sync Templates"}
        </button>
      </div>

      {syncResult && (
        <SyncStatusBanner result={syncResult} onDismiss={() => setSyncResult(null)} />
      )}

      {templates.length === 0 ? (
        <div className="empty-state">
          <Package size={48} className="empty-state-icon" />
          <div className="empty-state-title">No templates available</div>
          <div className="empty-state-desc">
            Use the Sync button to fetch templates from the configured repository,
            or check your repository URL in Settings.
          </div>
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
                  <div className="app-card-slug">
                    {tmpl.slug}
                    {tmpl.latest_version && (
                      <span className="template-version-badge">v{tmpl.latest_version}</span>
                    )}
                  </div>
                </div>
              </div>
              <div className="app-card-desc">{tmpl.description}</div>
              <div className="app-card-footer">
                <div className="app-card-tags">
                  {tmpl.provides.map(p => (
                    <span key={p.key} className="tag">{p.key}</span>
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
          composeBase={composeBase}
          onClose={() => setInstalling(null)}
          onInstalled={() => setInstalling(null)}
        />
      )}
    </div>
  );
}
