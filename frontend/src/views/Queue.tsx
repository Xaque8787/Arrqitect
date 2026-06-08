import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ListOrdered, Trash2, CreditCard as Edit2, TriangleAlert as AlertTriangle, CircleCheck as CheckCircle, Info, ChevronRight } from "lucide-react";
import { api } from "../api";
import { useQueue } from "../QueueContext";
import type { InstalledApp, QueueValidationResult, QueueValidationIssue } from "../api";

function severityIcon(severity: "error" | "warning") {
  if (severity === "error") return <AlertTriangle size={14} style={{ color: "var(--color-error)", flexShrink: 0 }} />;
  return <AlertTriangle size={14} style={{ color: "var(--color-warning)", flexShrink: 0 }} />;
}

function ReviewInstallModal({
  apps,
  onClose,
  onInstalled,
}: {
  apps: InstalledApp[];
  onClose: () => void;
  onInstalled: (jobId: string) => void;
}) {
  const [validation, setValidation] = useState<QueueValidationResult | null>(null);
  const [validating, setValidating] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validated, setValidated] = useState(false);

  const runValidation = async () => {
    setValidating(true);
    setError(null);
    try {
      const result = await api.queue.validate();
      setValidation(result);
      setValidated(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Validation failed");
    } finally {
      setValidating(false);
    }
  };

  const handleInstall = async (force = false) => {
    setInstalling(true);
    setError(null);
    try {
      const { job } = await api.queue.install(force);
      onInstalled(job.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Install failed");
      setInstalling(false);
    }
  };

  const errors = validation?.issues.filter(i => i.severity === "error") ?? [];
  const warnings = validation?.issues.filter(i => i.severity === "warning") ?? [];
  const hasErrors = errors.length > 0;
  const hasWarnings = warnings.length > 0;

  const appById = Object.fromEntries(apps.map(a => [a.id, a]));
  const orderedApps = validation
    ? validation.install_order.map(id => appById[id]).filter(Boolean)
    : apps;

  const issuesByApp = (issues: QueueValidationIssue[]) => {
    const map: Record<string, QueueValidationIssue[]> = {};
    for (const issue of issues) {
      if (!map[issue.consumer_app_id]) map[issue.consumer_app_id] = [];
      map[issue.consumer_app_id].push(issue);
    }
    return map;
  };

  const errorMap = issuesByApp(errors);
  const warningMap = issuesByApp(warnings);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-wide" style={{ maxHeight: "90vh", display: "flex", flexDirection: "column" }} onClick={e => e.stopPropagation()}>
        <div className="modal-title">Review & Install</div>

        <div style={{ overflowY: "auto", flex: 1, minHeight: 0 }}>
          {!validated ? (
            <div style={{ padding: "24px 0", textAlign: "center" }}>
              <div style={{ fontSize: 14, color: "var(--color-text-muted)", marginBottom: 20 }}>
                Validate your queue before installing. This checks for missing config, dependency issues, and cross-app requirements.
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 8 }}>
                {apps.map((app, i) => (
                  <div key={app.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", background: "var(--color-surface-2)", borderRadius: 6 }}>
                    <span style={{ fontSize: 12, color: "var(--color-text-dim)", width: 20, textAlign: "center" }}>{i + 1}</span>
                    {app.app_templates?.icon_url ? (
                      <img src={app.app_templates.icon_url} style={{ width: 20, height: 20, borderRadius: 4, objectFit: "cover" }} alt="" />
                    ) : (
                      <div style={{ width: 20, height: 20, background: "var(--color-surface-3)", borderRadius: 4 }} />
                    )}
                    <span style={{ fontSize: 13, fontWeight: 500 }}>{app.name}</span>
                    <span style={{ fontSize: 12, color: "var(--color-text-dim)" }}>{app.slug}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {validation && (
                <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", background: hasErrors ? "var(--color-error-dim)" : hasWarnings ? "var(--color-warning-dim)" : "var(--color-success-dim)", borderRadius: 6 }}>
                  {hasErrors ? (
                    <AlertTriangle size={16} style={{ color: "var(--color-error)" }} />
                  ) : hasWarnings ? (
                    <AlertTriangle size={16} style={{ color: "var(--color-warning)" }} />
                  ) : (
                    <CheckCircle size={16} style={{ color: "var(--color-success)" }} />
                  )}
                  <span style={{ fontSize: 13, fontWeight: 600, color: hasErrors ? "var(--color-error)" : hasWarnings ? "var(--color-warning)" : "var(--color-success)" }}>
                    {hasErrors
                      ? `${errors.length} error${errors.length !== 1 ? "s" : ""} must be resolved before installing`
                      : hasWarnings
                      ? `${warnings.length} warning${warnings.length !== 1 ? "s" : ""} — review before proceeding`
                      : "All checks passed — ready to install"}
                  </span>
                </div>
              )}

              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-dim)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 8 }}>Install Order</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {orderedApps.map((app, i) => {
                    const appErrors = errorMap[app.id] ?? [];
                    const appWarnings = warningMap[app.id] ?? [];
                    return (
                      <div key={app.id} style={{ background: "var(--color-surface-2)", borderRadius: 6, overflow: "hidden" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px" }}>
                          <span style={{ fontSize: 12, color: "var(--color-text-dim)", width: 20, textAlign: "center" }}>{i + 1}</span>
                          {app.app_templates?.icon_url ? (
                            <img src={app.app_templates.icon_url} style={{ width: 20, height: 20, borderRadius: 4, objectFit: "cover" }} alt="" />
                          ) : (
                            <div style={{ width: 20, height: 20, background: "var(--color-surface-3)", borderRadius: 4 }} />
                          )}
                          <span style={{ fontSize: 13, fontWeight: 500, flex: 1 }}>{app.name}</span>
                          {appErrors.length > 0 && (
                            <span style={{ fontSize: 11, color: "var(--color-error)", fontWeight: 600 }}>{appErrors.length} error{appErrors.length !== 1 ? "s" : ""}</span>
                          )}
                          {appWarnings.length > 0 && (
                            <span style={{ fontSize: 11, color: "var(--color-warning)", fontWeight: 600 }}>{appWarnings.length} warning{appWarnings.length !== 1 ? "s" : ""}</span>
                          )}
                        </div>
                        {(appErrors.length > 0 || appWarnings.length > 0) && (
                          <div style={{ padding: "0 12px 8px 42px", display: "flex", flexDirection: "column", gap: 4 }}>
                            {[...appErrors, ...appWarnings].map((issue, j) => (
                              <div key={j} style={{ display: "flex", alignItems: "flex-start", gap: 6, fontSize: 12, color: issue.severity === "error" ? "var(--color-error)" : "var(--color-warning)" }}>
                                {severityIcon(issue.severity)}
                                <span>{issue.message}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {error && <div className="form-error" style={{ marginTop: 12 }}>{error}</div>}
        </div>

        <div className="modal-actions" style={{ borderTop: "1px solid var(--color-border)", paddingTop: 16, marginTop: 16 }}>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          {!validated ? (
            <button className="btn btn-primary" onClick={runValidation} disabled={validating}>
              {validating ? <span className="spinner" /> : "Validate Queue"}
            </button>
          ) : hasErrors ? (
            <>
              <button className="btn btn-ghost" onClick={runValidation} disabled={validating}>
                {validating ? <span className="spinner" /> : "Re-validate"}
              </button>
              <button
                className="btn btn-danger"
                onClick={() => handleInstall(true)}
                disabled={installing}
                title="Install anyway, skipping apps with unresolvable dependencies"
              >
                {installing ? <span className="spinner" /> : "Force Install"}
              </button>
            </>
          ) : (
            <>
              <button className="btn btn-ghost" onClick={runValidation} disabled={validating}>
                {validating ? <span className="spinner" /> : "Re-validate"}
              </button>
              <button className="btn btn-primary" onClick={() => handleInstall(false)} disabled={installing}>
                {installing ? <span className="spinner" /> : `Install ${apps.length} app${apps.length !== 1 ? "s" : ""}`}
                {!installing && <ChevronRight size={14} />}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function QueueAppCard({
  app,
  onRemove,
  onEdit,
}: {
  app: InstalledApp;
  onRemove: () => void;
  onEdit: () => void;
}) {
  const [removing, setRemoving] = useState(false);
  const schema = app.app_templates?.config_schema ?? [];
  const visibleConfig = schema
    .filter(f => (f.visibility ?? "visible") === "visible")
    .map(f => ({ label: f.label, value: app.config[f.id] }))
    .filter(e => e.value != null && e.value !== "");

  const actionCount = app.actions?.length ?? 0;

  const handleRemove = async () => {
    setRemoving(true);
    try {
      await api.queue.remove(app.id);
      onRemove();
    } catch {
      setRemoving(false);
    }
  };

  return (
    <div className="card" style={{ padding: "16px 20px" }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 14 }}>
        {app.app_templates?.icon_url ? (
          <img src={app.app_templates.icon_url} style={{ width: 40, height: 40, borderRadius: 8, objectFit: "cover", flexShrink: 0 }} alt="" />
        ) : (
          <div style={{ width: 40, height: 40, background: "var(--color-surface-3)", borderRadius: 8, flexShrink: 0 }} />
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span style={{ fontWeight: 600, fontSize: 15 }}>{app.name}</span>
            <span className="badge badge-staged">staged</span>
          </div>
          <div style={{ fontSize: 12, color: "var(--color-text-dim)", marginBottom: visibleConfig.length > 0 ? 10 : 0 }}>{app.slug}</div>
          {visibleConfig.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {visibleConfig.slice(0, 4).map(e => (
                <div key={String(e.label)} style={{ fontSize: 11, background: "var(--color-surface-3)", padding: "3px 8px", borderRadius: 4, color: "var(--color-text-muted)" }}>
                  <span style={{ color: "var(--color-text-dim)" }}>{e.label}:</span> {String(e.value)}
                </div>
              ))}
              {visibleConfig.length > 4 && (
                <div style={{ fontSize: 11, color: "var(--color-text-dim)", padding: "3px 4px" }}>+{visibleConfig.length - 4} more</div>
              )}
            </div>
          )}
          {actionCount > 0 && (
            <div style={{ fontSize: 11, color: "var(--color-text-dim)", marginTop: 6 }}>
              {actionCount} action{actionCount !== 1 ? "s" : ""} configured
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
          <button className="btn btn-ghost btn-sm" onClick={onEdit} title="Edit queue entry">
            <Edit2 size={13} /> Edit
          </button>
          <button className="btn btn-ghost btn-sm" onClick={handleRemove} disabled={removing} title="Remove from queue">
            {removing ? <span className="spinner" style={{ width: 13, height: 13 }} /> : <Trash2 size={13} />}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Queue() {
  const { queue, refresh } = useQueue();
  const navigate = useNavigate();
  const [reviewOpen, setReviewOpen] = useState(false);
  const [editingApp, setEditingApp] = useState<InstalledApp | null>(null);

  const handleInstalled = (jobId: string) => {
    setReviewOpen(false);
    refresh();
    navigate(`/jobs/${jobId}`);
  };

  if (queue.length === 0) {
    return (
      <div>
        <div className="page-header">
          <div>
            <div className="page-title">Install Queue</div>
            <div className="page-subtitle">Stage apps from the library, then install them together</div>
          </div>
        </div>
        <div className="empty-state">
          <ListOrdered size={48} className="empty-state-icon" />
          <div className="empty-state-title">Queue is empty</div>
          <div className="empty-state-desc">Go to the App Library and stage apps to add them here.</div>
          <Link to="/library" className="btn btn-primary" style={{ marginTop: 8 }}>Browse Library</Link>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Install Queue</div>
          <div className="page-subtitle">{queue.length} app{queue.length !== 1 ? "s" : ""} staged</div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Link to="/library" className="btn btn-ghost btn-sm">+ Add More</Link>
          <button className="btn btn-primary" onClick={() => setReviewOpen(true)}>
            Review & Install
            <ChevronRight size={14} />
          </button>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {queue.map(app => (
          <QueueAppCard
            key={app.id}
            app={app}
            onRemove={refresh}
            onEdit={() => setEditingApp(app)}
          />
        ))}
      </div>

      <div style={{ marginTop: 16, padding: "12px 16px", background: "var(--color-surface-2)", borderRadius: 8, display: "flex", alignItems: "center", gap: 8 }}>
        <Info size={14} style={{ color: "var(--color-text-dim)", flexShrink: 0 }} />
        <span style={{ fontSize: 12, color: "var(--color-text-dim)" }}>
          Apps will be installed in dependency order. Use "Review & Install" to validate and confirm the plan.
        </span>
      </div>

      {reviewOpen && (
        <ReviewInstallModal
          apps={queue}
          onClose={() => setReviewOpen(false)}
          onInstalled={handleInstalled}
        />
      )}

      {editingApp && (
        <EditQueueEntryModal
          app={editingApp}
          onClose={() => setEditingApp(null)}
          onSaved={() => { setEditingApp(null); refresh(); }}
        />
      )}
    </div>
  );
}

function EditQueueEntryModal({
  app,
  onClose,
  onSaved,
}: {
  app: InstalledApp;
  onClose: () => void;
  onSaved: () => void;
}) {
  const schema = app.app_templates?.config_schema ?? [];
  const [config, setConfig] = useState<Record<string, string>>(
    Object.fromEntries(
      schema
        .filter(f => (f.visibility ?? "visible") !== "hidden")
        .map(f => [f.id, String(app.config[f.id] ?? f.default ?? "")])
    )
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const visibleFields = schema.filter(f => (f.visibility ?? "visible") === "visible");
  const advancedFields = schema.filter(f => (f.visibility ?? "visible") === "advanced");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const resolved: Record<string, unknown> = {};
      for (const field of schema) {
        if ((field.visibility ?? "visible") === "hidden") continue;
        resolved[field.id] = field.type === "number" || field.type === "port"
          ? Number(config[field.id])
          : config[field.id];
      }
      await api.queue.update(app.id, resolved, app.actions?.map(a => ({
        action_id: a.action_id,
        variant_id: a.variant_id,
        fields: a.fields,
      })));
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-wide" onClick={e => e.stopPropagation()}>
        <div className="modal-title">Edit Queue Entry — {app.name}</div>
        <form onSubmit={handleSubmit}>
          {visibleFields.map(field => (
            <div className="form-group" key={field.id}>
              <label className="form-label">{field.label}</label>
              <input
                className="form-input"
                type={field.type === "number" || field.type === "port" ? "number" : "text"}
                value={config[field.id] ?? ""}
                onChange={e => setConfig(c => ({ ...c, [field.id]: e.target.value }))}
                required={field.required}
                placeholder={field.placeholder ?? ""}
              />
            </div>
          ))}
          {advancedFields.length > 0 && (
            <details className="advanced-section">
              <summary className="advanced-section-toggle">Advanced</summary>
              <div className="advanced-section-body">
                {advancedFields.map(field => (
                  <div className="form-group" key={field.id}>
                    <label className="form-label">{field.label}</label>
                    <input
                      className="form-input"
                      type={field.type === "number" || field.type === "port" ? "number" : "text"}
                      value={config[field.id] ?? ""}
                      onChange={e => setConfig(c => ({ ...c, [field.id]: e.target.value }))}
                      required={field.required}
                    />
                  </div>
                ))}
              </div>
            </details>
          )}
          {error && <div className="form-error">{error}</div>}
          <div className="modal-actions">
            <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? <span className="spinner" /> : "Save"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
