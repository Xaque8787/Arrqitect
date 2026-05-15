import { useEffect, useState } from "react";
import { Settings2, RefreshCw } from "lucide-react";
import { api } from "../api";
import type { GlobalSettings, ComposeBase } from "../api";

export default function Settings() {
  const [settings, setSettings] = useState<GlobalSettings | null>(null);
  const [form, setForm] = useState<GlobalSettings | null>(null);
  const [composeBase, setComposeBase] = useState<ComposeBase | null>(null);
  const [baseLoading, setBaseLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    api.settings.get().then(s => { setSettings(s); setForm(s); });
    fetchComposeBase();
  }, []);

  function fetchComposeBase() {
    setBaseLoading(true);
    api.settings.composeBase().then(setComposeBase).finally(() => setBaseLoading(false));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    try {
      const updated = await api.settings.update(form);
      setSettings(updated);
      setForm(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  const isDirty = form && settings && JSON.stringify(form) !== JSON.stringify(settings);

  if (!form) return <div className="loading-center"><div className="spinner" /></div>;

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Settings</div>
          <div className="page-subtitle">Global defaults injected into every app deployment</div>
        </div>
      </div>

      <div className="settings-layout">
        {/* Global defaults */}
        <div className="settings-card">
          <div className="settings-card-title">
            <Settings2 size={14} />
            Global Defaults
          </div>
          <p className="settings-card-desc">
            These values are automatically injected into all app compose templates.
            You do not need to set them per-app.
          </p>
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label className="form-label">Timezone</label>
              <input
                className="form-input"
                value={form.timezone}
                onChange={e => setForm(f => f && { ...f, timezone: e.target.value })}
                placeholder="Etc/UTC"
              />
              <div className="form-hint">IANA timezone string — e.g. <code>America/New_York</code>, <code>Europe/London</code></div>
            </div>
            <div className="settings-row-2">
              <div className="form-group">
                <label className="form-label">PUID</label>
                <input
                  className="form-input"
                  type="number"
                  value={form.puid}
                  onChange={e => setForm(f => f && { ...f, puid: e.target.value })}
                  placeholder="1000"
                />
                <div className="form-hint">User ID for container file ownership</div>
              </div>
              <div className="form-group">
                <label className="form-label">PGID</label>
                <input
                  className="form-input"
                  type="number"
                  value={form.pgid}
                  onChange={e => setForm(f => f && { ...f, pgid: e.target.value })}
                  placeholder="1000"
                />
                <div className="form-hint">Group ID for container file ownership</div>
              </div>
            </div>

            {saveError && <div className="settings-msg settings-msg-error">{saveError}</div>}
            {saved && <div className="settings-msg settings-msg-success">Settings saved.</div>}

            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button type="submit" className="btn btn-primary" disabled={saving || !isDirty}>
                {saving
                  ? <><span className="spinner spinner-sm" /> Saving…</>
                  : "Save Settings"}
              </button>
            </div>
          </form>
        </div>

        {/* Compose base path */}
        <div className="settings-card">
          <div className="settings-card-title">
            <RefreshCw size={14} />
            Compose Base Path
          </div>
          <p className="settings-card-desc">
            Derived by inspecting the running <code>arrqitect</code> container — specifically the
            host-side source of its <code>/compose</code> bind mount. Relative paths you enter
            for app volumes (e.g. <code>./config</code>) resolve under this directory.
          </p>

          {baseLoading ? (
            <div className="settings-base-loading">
              <div className="spinner spinner-sm" />
              Inspecting container…
            </div>
          ) : composeBase ? (
            composeBase.host_path ? (
              <div className="settings-base-result">
                <div className="settings-base-path">{composeBase.host_path}</div>
                <div className="settings-base-example">
                  e.g. <code>./config</code> for sonarr →{" "}
                  <code>{composeBase.host_path.replace(/\/$/, "")}/sonarr/config</code>
                </div>
              </div>
            ) : (
              <div className="settings-msg settings-msg-error">
                {composeBase.error ?? "Could not determine compose base path."}<br />
                <span style={{ fontWeight: 400 }}>
                  Check that the Docker socket is mounted and the container name is{" "}
                  <code>arrqitect</code>.
                </span>
              </div>
            )
          ) : null}

          <button
            type="button"
            className="btn btn-ghost btn-sm"
            style={{ marginTop: 12 }}
            onClick={fetchComposeBase}
            disabled={baseLoading}
          >
            <RefreshCw size={12} />
            Refresh
          </button>
        </div>
      </div>
    </div>
  );
}
