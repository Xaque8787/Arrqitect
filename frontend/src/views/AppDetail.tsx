import { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { ArrowLeft, Trash2, Eye, RefreshCw, X, Plus } from "lucide-react";
import { api, resolveHostPath, fieldPlaceholder } from "../api";
import type { InstalledApp, ConfigField, PreviewResult, CustomEnvEntry, CustomStorageEntry } from "../api";

function PreviewModal({ result, onClose }: { result: PreviewResult; onClose: () => void }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" style={{ width: 640 }} onClick={e => e.stopPropagation()}>
        <div className="modal-title">Dry Run Preview — {result.slug}</div>

        <div className="detail-section-title">Resolved Config</div>
        <table className="config-table" style={{ marginBottom: 16 }}>
          <tbody>
            {Object.entries(result.config).map(([k, v]) => (
              <tr key={k}>
                <td>{k}</td>
                <td>{String(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="detail-section-title">Rendered docker-compose.yml</div>
        {result.compose_ok ? (
          <pre className="preview-compose">{result.compose_rendered}</pre>
        ) : (
          <div style={{ color: "var(--color-error)", fontSize: 13, marginBottom: 12 }}>
            Render error: {result.compose_error}
          </div>
        )}

        <div className="detail-section-title" style={{ marginTop: 16 }}>Hook Steps</div>
        {result.hook_steps.length === 0 ? (
          <div style={{ color: "var(--color-text-dim)", fontSize: 13 }}>No hooks defined</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {result.hook_steps.map(h => (
              <div key={h.hook} style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
                <span style={{ color: "var(--color-primary)", fontWeight: 600 }}>{h.hook}</span>: {h.action}
              </div>
            ))}
          </div>
        )}

        <div style={{ marginTop: 16, fontSize: 12, color: "var(--color-text-dim)" }}>
          Host path: <code style={{ fontFamily: "ui-monospace, monospace" }}>{result.host_compose_path}</code>
        </div>

        <div className="modal-actions">
          <button className="btn btn-ghost" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

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
          disabled={field.editable === false}
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
          disabled={field.editable === false}
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
        disabled={field.editable === false}
      />
    </div>
  );
}

function CustomEnvSection({
  entries,
  onChange,
}: {
  entries: CustomEnvEntry[];
  onChange: (entries: CustomEnvEntry[]) => void;
}) {
  const add = () => onChange([...entries, { key: "", value: "" }]);
  const remove = (i: number) => onChange(entries.filter((_, idx) => idx !== i));
  const update = (i: number, field: keyof CustomEnvEntry, val: string) => {
    onChange(entries.map((e, idx) => idx === i ? { ...e, [field]: val } : e));
  };

  return (
    <div className="custom-section">
      <div className="custom-section-header">
        <span className="custom-section-label">Custom Environment Variables</span>
        <button type="button" className="btn btn-ghost btn-sm" onClick={add}>
          <Plus size={12} /> Add Variable
        </button>
      </div>
      {entries.length === 0 ? (
        <div className="custom-empty">No custom variables added.</div>
      ) : (
        <div className="custom-rows">
          {entries.map((entry, i) => (
            <div key={i} className="custom-row">
              <input
                className="form-input"
                placeholder="KEY"
                value={entry.key}
                onChange={e => update(i, "key", e.target.value)}
                style={{ fontFamily: "ui-monospace, monospace", fontSize: 12 }}
              />
              <span className="custom-row-sep">=</span>
              <input
                className="form-input"
                placeholder="value"
                value={entry.value}
                onChange={e => update(i, "value", e.target.value)}
              />
              <button type="button" className="custom-row-remove" onClick={() => remove(i)} title="Remove">
                <X size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CustomStorageSection({
  entries,
  onChange,
}: {
  entries: CustomStorageEntry[];
  onChange: (entries: CustomStorageEntry[]) => void;
}) {
  const add = () => onChange([...entries, { host_path: "", container_path: "", propagation: "private", mutability: "read-write" }]);
  const remove = (i: number) => onChange(entries.filter((_, idx) => idx !== i));
  const update = (i: number, field: keyof CustomStorageEntry, val: string) => {
    onChange(entries.map((e, idx) => idx === i ? { ...e, [field]: val } : e));
  };

  return (
    <div className="custom-section">
      <div className="custom-section-header">
        <span className="custom-section-label">Custom Volumes</span>
        <button type="button" className="btn btn-ghost btn-sm" onClick={add}>
          <Plus size={12} /> Add Volume
        </button>
      </div>
      {entries.length === 0 ? (
        <div className="custom-empty">No custom volumes added.</div>
      ) : (
        <div className="custom-rows">
          {entries.map((entry, i) => (
            <div key={i} className="custom-row">
              <input
                className="form-input"
                placeholder="Host path (e.g. /mnt/media)"
                value={entry.host_path}
                onChange={e => update(i, "host_path", e.target.value)}
              />
              <span className="custom-row-sep">→</span>
              <input
                className="form-input"
                placeholder="Container path (e.g. /media)"
                value={entry.container_path}
                onChange={e => update(i, "container_path", e.target.value)}
                style={{ fontFamily: "ui-monospace, monospace", fontSize: 12 }}
              />
              <button type="button" className="custom-row-remove" onClick={() => remove(i)} title="Remove">
                <X size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CustomStoragePropagationRows({
  entries,
  onChange,
}: {
  entries: CustomStorageEntry[];
  onChange: (entries: CustomStorageEntry[]) => void;
}) {
  if (entries.length === 0) return null;
  const update = (i: number, val: CustomStorageEntry["propagation"]) => {
    onChange(entries.map((e, idx) => idx === i ? { ...e, propagation: val } : e));
  };

  return (
    <>
      {entries.map((entry, i) => {
        const label = entry.container_path || `Volume ${i + 1}`;
        return (
          <div className="form-group" key={i}>
            <label className="form-label">{label} — Propagation</label>
            <select
              className="form-input"
              value={entry.propagation}
              onChange={e => update(i, e.target.value as CustomStorageEntry["propagation"])}
            >
              <option value="private">private</option>
              <option value="shared">shared</option>
              <option value="slave">slave</option>
              <option value="rslave">rslave</option>
            </select>
          </div>
        );
      })}
    </>
  );
}

function EditConfigModal({ app, schema, composeBase, onClose, onSaved }: {
  app: InstalledApp;
  schema: ConfigField[];
  composeBase: string | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [config, setConfig] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(app.config).map(([k, v]) => [k, String(v)]))
  );

  const [customEnv, setCustomEnv] = useState<CustomEnvEntry[]>(() => {
    const raw = app.config.custom_env;
    return Array.isArray(raw) ? (raw as CustomEnvEntry[]) : [];
  });

  const [customStorage, setCustomStorage] = useState<CustomStorageEntry[]>(() => {
    const raw = app.config.custom_storage;
    return Array.isArray(raw) ? (raw as CustomStorageEntry[]) : [];
  });

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const allowCustomEnv = app.app_templates?.allow_custom_env ?? false;
  const allowCustomStorage = app.app_templates?.allow_custom_storage ?? false;

  const visibleFields = schema.filter(f => (f.visibility ?? "visible") === "visible");
  const advancedFields = schema.filter(f => (f.visibility ?? "visible") === "advanced");
  const hasAdvanced = advancedFields.length > 0 || customStorage.length > 0;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const resolved: Record<string, unknown> = {};
      for (const field of schema) {
        if ((field.visibility ?? "visible") === "hidden") continue;
        resolved[field.id] = field.type === "number" || field.type === "port"
          ? Number(config[field.id])
          : config[field.id];
      }
      if (allowCustomEnv) {
        resolved.custom_env = customEnv.filter(e => e.key.trim());
      }
      if (allowCustomStorage) {
        resolved.custom_storage = customStorage.filter(e => e.host_path.trim() && e.container_path.trim());
      }
      const { job } = await api.apps.updateConfig(app.id, resolved);
      onSaved();
      navigate(`/jobs/${job.id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Update failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-wide" onClick={e => e.stopPropagation()}>
        <div className="modal-title">Edit Config — {app.name}</div>
        <form onSubmit={handleSubmit}>
          {visibleFields.map(field => (
            <ConfigFieldInput
              key={field.id}
              field={field}
              value={config[field.id] ?? ""}
              onChange={v => setConfig(c => ({ ...c, [field.id]: v }))}
              appSlug={app.slug}
              composeBase={composeBase}
            />
          ))}

          {allowCustomStorage && (
            <CustomStorageSection entries={customStorage} onChange={setCustomStorage} />
          )}

          {allowCustomEnv && (
            <CustomEnvSection entries={customEnv} onChange={setCustomEnv} />
          )}

          {hasAdvanced && (
            <details className="advanced-section">
              <summary className="advanced-section-toggle">Advanced</summary>
              <div className="advanced-section-body">
                {advancedFields.map(field => (
                  <ConfigFieldInput
                    key={field.id}
                    field={field}
                    value={config[field.id] ?? ""}
                    onChange={v => setConfig(c => ({ ...c, [field.id]: v }))}
                    appSlug={app.slug}
                    composeBase={composeBase}
                  />
                ))}
                {allowCustomStorage && customStorage.length > 0 && (
                  <CustomStoragePropagationRows entries={customStorage} onChange={setCustomStorage} />
                )}
              </div>
            </details>
          )}

          {error && <div className="form-error">{error}</div>}
          <div className="modal-actions">
            <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? <span className="spinner" /> : "Save & Redeploy"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function AppDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [app, setApp] = useState<InstalledApp | null>(null);
  const [loading, setLoading] = useState(true);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [composeBase, setComposeBase] = useState<string | null>(null);

  const load = () => {
    if (!id) return;
    api.apps.get(id).then(setApp).finally(() => setLoading(false));
  };

  useEffect(load, [id]);

  useEffect(() => {
    api.settings.composeBase().then(r => {
      if (r.host_path) setComposeBase(r.host_path);
    });
  }, []);

  const handleRemove = async () => {
    if (!app || !confirm(`Remove ${app.name}? This will run docker compose down.`)) return;
    setRemoving(true);
    const { job } = await api.apps.remove(app.id);
    navigate(`/jobs/${job.id}`);
  };

  const handlePreview = async () => {
    if (!app) return;
    setLoadingPreview(true);
    const result = await api.apps.preview(app.id);
    setPreview(result);
    setLoadingPreview(false);
  };

  if (loading) return <div className="loading-center"><div className="spinner" /></div>;
  if (!app) return <div style={{ padding: 32, color: "var(--color-text-muted)" }}>App not found.</div>;

  const schema: ConfigField[] = app.app_templates?.config_schema ?? [];

  return (
    <div>
      <div className="page-header">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => navigate("/apps")}>
            <ArrowLeft size={14} />
          </button>
          <div>
            <div className="page-title">{app.name}</div>
            <div className="page-subtitle">{app.slug}</div>
          </div>
          <span className={`badge badge-${app.state}`}>{app.state}</span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn btn-ghost btn-sm" onClick={handlePreview} disabled={loadingPreview}>
            {loadingPreview ? <span className="spinner" style={{ width: 14, height: 14 }} /> : <Eye size={14} />}
            Preview
          </button>
          <button className="btn btn-ghost btn-sm" onClick={() => setEditOpen(true)}>
            <RefreshCw size={14} /> Edit Config
          </button>
          <button className="btn btn-danger btn-sm" onClick={handleRemove} disabled={removing}>
            <Trash2 size={14} /> Remove
          </button>
        </div>
      </div>

      <div className="detail-section">
        <div className="detail-section-title">Configuration</div>
        <div className="card">
          <table className="config-table">
            <tbody>
              {Object.entries(app.config).map(([k, v]) => (
                <tr key={k}>
                  <td>{k}</td>
                  <td>{String(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {app.compose_path && (
        <div className="detail-section">
          <div className="detail-section-title">Compose File</div>
          <div className="card" style={{ fontSize: 12, fontFamily: "ui-monospace, monospace", color: "var(--color-text-muted)" }}>
            {app.compose_path}
          </div>
        </div>
      )}

      <div className="detail-section">
        <div className="detail-section-title">
          <Link to={`/jobs?app_id=${app.id}`} style={{ color: "inherit" }}>Recent Jobs</Link>
        </div>
        <AppJobs appId={app.id} />
      </div>

      {preview && <PreviewModal result={preview} onClose={() => setPreview(null)} />}
      {editOpen && (
        <EditConfigModal
          app={app}
          schema={schema}
          composeBase={composeBase}
          onClose={() => setEditOpen(false)}
          onSaved={() => { setEditOpen(false); load(); }}
        />
      )}
    </div>
  );
}

function AppJobs({ appId }: { appId: string }) {
  const [jobs, setJobs] = useState<ReturnType<typeof api.jobs.list> extends Promise<infer T> ? T : never>([]);
  const navigate = useNavigate();

  useEffect(() => {
    api.jobs.list(appId).then(setJobs);
  }, [appId]);

  if (jobs.length === 0) {
    return <div style={{ color: "var(--color-text-dim)", fontSize: 13 }}>No jobs yet.</div>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {jobs.slice(0, 10).map(job => (
        <div
          key={job.id}
          className="card"
          style={{ padding: "10px 16px", display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer" }}
          onClick={() => navigate(`/jobs/${job.id}`)}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 13, fontWeight: 500 }}>{job.type}</span>
            {job.dry_run && <span className="tag">dry run</span>}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ fontSize: 11, color: "var(--color-text-dim)" }}>
              {new Date(job.created_at).toLocaleString()}
            </span>
            <span className={`badge badge-${job.status}`}>{job.status}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
