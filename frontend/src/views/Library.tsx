import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Package, RefreshCw, CircleCheck as CheckCircle, CircleAlert as AlertCircle, X, Plus, ChevronRight, ChevronLeft, Zap } from "lucide-react";
import { api, resolveHostPath, fieldPlaceholder } from "../api";
import type { AppTemplate, ConfigField, SyncResult, CustomEnvEntry, CustomStorageEntry, ActionsSchema, ActionDef, ActionVariantDef, ActionFieldDef } from "../api";

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
    const next = entries.map((e, idx) => idx === i ? { ...e, [field]: val } : e);
    onChange(next);
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
    const next = entries.map((e, idx) => idx === i ? { ...e, [field]: val } : e);
    onChange(next);
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
    const next = entries.map((e, idx) => idx === i ? { ...e, propagation: val } : e);
    onChange(next);
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

interface QueuedAction {
  action_id: string;
  variant_id: string;
  fields: Record<string, string>;
  label: string;
  variant_label: string;
}

function ActionFieldInput({
  fieldDef,
  value,
  onChange,
}: {
  fieldDef: ActionFieldDef;
  value: string;
  onChange: (v: string) => void;
}) {
  if (fieldDef.type === "boolean") {
    return (
      <div className="form-group" style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <label className="form-label" style={{ marginBottom: 0, flex: 1 }}>{fieldDef.label}</label>
        <input
          type="checkbox"
          checked={value === "true"}
          onChange={e => onChange(e.target.checked ? "true" : "false")}
          style={{ width: 16, height: 16 }}
        />
      </div>
    );
  }
  if (fieldDef.type === "select" && fieldDef.options?.length) {
    return (
      <div className="form-group">
        <label className="form-label">{fieldDef.label}</label>
        <select className="form-input" value={value} onChange={e => onChange(e.target.value)}>
          {fieldDef.options.map(opt => <option key={opt} value={opt}>{opt}</option>)}
          {fieldDef.allow_custom && !fieldDef.options.includes(value) && (
            <option value={value}>{value}</option>
          )}
        </select>
        {fieldDef.allow_custom && (
          <input
            className="form-input"
            style={{ marginTop: 4 }}
            value={value}
            onChange={e => onChange(e.target.value)}
            placeholder="Or enter custom URL"
          />
        )}
      </div>
    );
  }
  return (
    <div className="form-group">
      <label className="form-label">{fieldDef.label}</label>
      <input
        className="form-input"
        type={fieldDef.type === "number" ? "number" : "text"}
        value={value}
        onChange={e => onChange(e.target.value)}
      />
    </div>
  );
}

function VariantFormModal({
  variantDef,
  onAdd,
  onClose,
}: {
  variantDef: ActionVariantDef;
  onAdd: (fields: Record<string, string>) => void;
  onClose: () => void;
}) {
  const [fields, setFields] = useState<Record<string, string>>(
    Object.fromEntries(variantDef.fields.map(f => [f.id, f.default ?? ""]))
  );
  const visibleFields = variantDef.fields.filter(f => (f.visibility ?? "visible") === "visible");
  const advancedFields = variantDef.fields.filter(f => f.visibility === "advanced");

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-title">{variantDef.label}</div>
        {variantDef.description && (
          <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 16 }}>
            {variantDef.description}
          </div>
        )}
        {visibleFields.map(f => (
          <ActionFieldInput
            key={f.id}
            fieldDef={f}
            value={fields[f.id] ?? ""}
            onChange={v => setFields(prev => ({ ...prev, [f.id]: v }))}
          />
        ))}
        {advancedFields.length > 0 && (
          <details className="advanced-section" style={{ marginTop: 8 }}>
            <summary className="advanced-section-toggle">Advanced</summary>
            <div className="advanced-section-body">
              {advancedFields.map(f => (
                <ActionFieldInput
                  key={f.id}
                  fieldDef={f}
                  value={fields[f.id] ?? ""}
                  onChange={v => setFields(prev => ({ ...prev, [f.id]: v }))}
                />
              ))}
            </div>
          </details>
        )}
        <div className="modal-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" onClick={() => onAdd(fields)}>Add</button>
        </div>
      </div>
    </div>
  );
}

function ActionsStep({
  actionsSchema,
  queued,
  onChange,
}: {
  actionsSchema: ActionsSchema;
  queued: QueuedAction[];
  onChange: (q: QueuedAction[]) => void;
}) {
  const [pickingVariant, setPickingVariant] = useState<{ action: ActionDef; variant: ActionVariantDef } | null>(null);

  if (actionsSchema.actions.length === 0) {
    return <div style={{ color: "var(--color-text-dim)", fontSize: 13, padding: "8px 0" }}>No configurable actions for this template.</div>;
  }

  const remove = (idx: number) => onChange(queued.filter((_, i) => i !== idx));

  return (
    <div>
      <div style={{ marginBottom: 12, fontSize: 13, color: "var(--color-text-muted)" }}>
        These actions run automatically after the app installs. You can skip and configure them later.
      </div>

      {actionsSchema.actions.map(actionDef => (
        <div key={actionDef.id} className="custom-section" style={{ marginBottom: 12 }}>
          <div className="custom-section-header">
            <span className="custom-section-label">{actionDef.label}</span>
          </div>
          {actionDef.description && (
            <div style={{ fontSize: 12, color: "var(--color-text-dim)", marginBottom: 8 }}>{actionDef.description}</div>
          )}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
            {actionDef.variants.map(variant => (
              <button
                key={variant.id}
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setPickingVariant({ action: actionDef, variant })}
              >
                <Plus size={12} /> {variant.label}
              </button>
            ))}
          </div>
        </div>
      ))}

      {queued.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-muted)", marginBottom: 6 }}>Queued Actions</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {queued.map((q, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 10px", background: "var(--color-surface-raised)", borderRadius: 6, fontSize: 13 }}>
                <Zap size={12} style={{ color: "var(--color-primary)", flexShrink: 0 }} />
                <span style={{ fontWeight: 500 }}>{q.label}</span>
                <span style={{ color: "var(--color-text-dim)" }}>·</span>
                <span style={{ color: "var(--color-text-muted)" }}>{q.variant_label}</span>
                {q.fields.name && q.fields.name !== q.variant_label && (
                  <>
                    <span style={{ color: "var(--color-text-dim)" }}>·</span>
                    <span style={{ color: "var(--color-text-dim)", fontSize: 12 }}>{q.fields.name}</span>
                  </>
                )}
                <button
                  type="button"
                  className="custom-row-remove"
                  style={{ marginLeft: "auto" }}
                  onClick={() => remove(i)}
                >
                  <X size={13} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {pickingVariant && (
        <VariantFormModal
          variantDef={pickingVariant.variant}
          onAdd={fields => {
            onChange([...queued, {
              action_id: pickingVariant.action.id,
              variant_id: pickingVariant.variant.id,
              fields,
              label: pickingVariant.action.label,
              variant_label: pickingVariant.variant.label,
            }]);
            setPickingVariant(null);
          }}
          onClose={() => setPickingVariant(null)}
        />
      )}
    </div>
  );
}

function InstallModal({ template, composeBase, onClose, onInstalled }: {
  template: AppTemplate;
  composeBase: string | null;
  onClose: () => void;
  onInstalled: () => void;
}) {
  const [step, setStep] = useState<"config" | "actions">("config");
  const [name, setName] = useState(template.name);
  const [config, setConfig] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      template.config_schema.map(f => [f.id, f.default != null ? String(f.default) : ""])
    )
  );
  const [customEnv, setCustomEnv] = useState<CustomEnvEntry[]>([]);
  const [customStorage, setCustomStorage] = useState<CustomStorageEntry[]>([]);
  const [queuedActions, setQueuedActions] = useState<QueuedAction[]>([]);
  const [actionsSchema, setActionsSchema] = useState<ActionsSchema | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    api.templates.actions(template.slug).then(schema => {
      if (schema.actions.length > 0) setActionsSchema(schema);
    }).catch(() => {});
  }, [template.slug]);

  const visibleFields = template.config_schema.filter(f => (f.visibility ?? "visible") === "visible");
  const advancedFields = template.config_schema.filter(f => (f.visibility ?? "visible") === "advanced");
  const hasAdvanced = advancedFields.length > 0 || customStorage.length > 0;

  const handleInstall = async () => {
    setLoading(true);
    setError(null);
    try {
      const resolvedConfig: Record<string, unknown> = {};
      for (const field of template.config_schema) {
        resolvedConfig[field.id] = field.type === "number" || field.type === "port"
          ? Number(config[field.id])
          : config[field.id];
      }
      if (template.allow_custom_env) {
        resolvedConfig.custom_env = customEnv.filter(e => e.key.trim());
      }
      if (template.allow_custom_storage) {
        resolvedConfig.custom_storage = customStorage.filter(e => e.host_path.trim() && e.container_path.trim());
      }
      const actions = queuedActions.map(q => ({
        action_id: q.action_id,
        variant_id: q.variant_id,
        fields: q.fields,
      }));
      const { job } = await api.apps.install(template.slug, name, resolvedConfig, undefined, actions);
      onInstalled();
      navigate(`/jobs/${job.id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Install failed");
      setStep("config");
    } finally {
      setLoading(false);
    }
  };

  const handleConfigNext = (e: React.FormEvent) => {
    e.preventDefault();
    if (actionsSchema) {
      setStep("actions");
    } else {
      handleInstall();
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-wide" onClick={e => e.stopPropagation()}>
        <div className="modal-title">
          Install {template.name}
          {actionsSchema && (
            <span style={{ fontSize: 12, fontWeight: 400, color: "var(--color-text-dim)", marginLeft: 10 }}>
              Step {step === "config" ? "1" : "2"} of 2
            </span>
          )}
        </div>

        {template.latest_version && (
          <div className="modal-version-badge">v{template.latest_version}</div>
        )}

        {step === "config" && (
          <>
            <div className="modal-global-note">
              <span>PUID, PGID, and Timezone are set globally in</span>
              <a href="/settings" className="inline-link" onClick={e => e.stopPropagation()}>Settings</a>
            </div>

            <form onSubmit={handleConfigNext}>
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

              {template.allow_custom_storage && (
                <CustomStorageSection entries={customStorage} onChange={setCustomStorage} />
              )}

              {template.allow_custom_env && (
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
                        appSlug={template.slug}
                        composeBase={composeBase}
                      />
                    ))}
                    {template.allow_custom_storage && customStorage.length > 0 && (
                      <CustomStoragePropagationRows entries={customStorage} onChange={setCustomStorage} />
                    )}
                  </div>
                </details>
              )}

              {error && <div className="form-error">{error}</div>}

              <div className="modal-actions">
                <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={loading}>
                  {loading ? <span className="spinner" /> : actionsSchema ? (
                    <><span>Next</span><ChevronRight size={14} /></>
                  ) : "Install"}
                </button>
              </div>
            </form>
          </>
        )}

        {step === "actions" && actionsSchema && (
          <>
            <ActionsStep
              actionsSchema={actionsSchema}
              queued={queuedActions}
              onChange={setQueuedActions}
            />
            {error && <div className="form-error">{error}</div>}
            <div className="modal-actions">
              <button type="button" className="btn btn-ghost" onClick={() => setStep("config")}>
                <ChevronLeft size={14} /> Back
              </button>
              <button type="button" className="btn btn-ghost" onClick={handleInstall} disabled={loading}>
                {loading ? <span className="spinner" /> : "Skip & Install"}
              </button>
              <button type="button" className="btn btn-primary" onClick={handleInstall} disabled={loading}>
                {loading ? <span className="spinner" /> : `Install${queuedActions.length > 0 ? ` + ${queuedActions.length} action${queuedActions.length !== 1 ? "s" : ""}` : ""}`}
              </button>
            </div>
          </>
        )}
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
