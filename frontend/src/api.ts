const BASE = "";

async function req<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

export interface ConfigField {
  id: string;
  label: string;
  type: "port" | "storage_path" | "string" | "number" | "boolean";
  default: string | number | boolean | null;
  placeholder?: string;
  binds_to: string;
  required: boolean;
  visibility: "visible" | "advanced" | "hidden";
  source: "user" | "platform" | "derived";
  allowed_values?: string[] | null;
  ui_widget?: "input" | "select";
  editable?: boolean;
}

export interface CapabilityProvides {
  key: string;
  type: string;
  sensitive: boolean;
  rotates: boolean;
}

export interface CustomEnvEntry {
  key: string;
  value: string;
}

export interface CustomStorageEntry {
  host_path: string;
  container_path: string;
  propagation: "private" | "shared" | "slave" | "rslave";
  mutability: "read-write" | "read-only";
}

export interface AppTemplate {
  id: string;
  slug: string;
  name: string;
  description: string;
  icon_url: string;
  source_url: string;
  latest_version: string;
  version_count: number;
  compose_template: string;
  config_schema: ConfigField[];
  hook_definitions: Record<string, string>;
  provides: CapabilityProvides[];
  allow_custom_env: boolean;
  allow_custom_storage: boolean;
}

export interface TemplateVersion {
  id: string;
  template_id: string;
  version: string;
  schema_version: number;
  content_hash: string;
  compose: string;
  config_schema: ConfigField[];
  hook_definitions: Record<string, string>;
  provides: string[];
  consumes: string[];
  created_at: string;
}

export interface InstalledApp {
  id: string;
  template_id: string;
  template_version_id: string | null;
  slug: string;
  name: string;
  config: Record<string, unknown>;
  state: "installing" | "running" | "stopped" | "error" | "removing";
  compose_path: string;
  created_at: string;
  app_templates?: AppTemplate & {
    installed_version: string | null;
    compose_template?: string;
  };
}

export interface Job {
  id: string;
  installed_app_id: string | null;
  type: string;
  status: "pending" | "running" | "success" | "failed" | "cancelled";
  dry_run: boolean;
  created_at: string;
  job_steps?: JobStep[];
}

export interface JobStep {
  id: string;
  job_id: string;
  step: string;
  status: "pending" | "running" | "success" | "failed" | "skipped";
  log: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface PreviewResult {
  app_id: string;
  slug: string;
  config: Record<string, unknown>;
  compose_rendered: string;
  compose_ok: boolean;
  compose_error: string | null;
  hook_steps: { hook: string; action: string }[];
  host_compose_path: string;
  compose_base: string;
}

export interface GlobalSettings {
  timezone: string;
  puid: string;
  pgid: string;
  template_repo_url: string;
}

export interface ComposeBase {
  host_path: string | null;
  error: string | null;
}

export interface SyncResult {
  ok: boolean;
  error?: string;
  results: { slug: string; version: string; status: "added" | "unchanged" }[];
  errors: { slug: string; error: string }[];
  synced_at?: string;
  repo_url?: string;
}

export const api = {
  templates: {
    list: () => req<AppTemplate[]>("/api/templates"),
    get: (slug: string) => req<AppTemplate>(`/api/templates/${slug}`),
    versions: (slug: string) => req<TemplateVersion[]>(`/api/templates/${slug}/versions`),
    sync: (repo_url?: string) =>
      req<SyncResult>("/api/templates/sync", {
        method: "POST",
        body: JSON.stringify({ repo_url: repo_url ?? null }),
      }),
  },
  apps: {
    list: () => req<InstalledApp[]>("/api/apps"),
    get: (id: string) => req<InstalledApp>(`/api/apps/${id}`),
    install: (template_slug: string, name: string, config: Record<string, unknown>, version?: string) =>
      req<{ app: InstalledApp; job: Job }>("/api/apps", {
        method: "POST",
        body: JSON.stringify({ template_slug, name, config, version: version ?? null }),
      }),
    updateConfig: (id: string, config: Record<string, unknown>) =>
      req<{ job: Job }>(`/api/apps/${id}/config`, {
        method: "PUT",
        body: JSON.stringify({ config }),
      }),
    remove: (id: string) =>
      req<{ job: Job }>(`/api/apps/${id}`, { method: "DELETE" }),
    preview: (id: string) => req<PreviewResult>(`/api/apps/${id}/preview`, { method: "POST" }),
  },
  jobs: {
    list: (app_id?: string) =>
      req<Job[]>(`/api/jobs${app_id ? `?app_id=${app_id}` : ""}`),
    get: (id: string) => req<Job>(`/api/jobs/${id}`),
  },
  settings: {
    get: () => req<GlobalSettings>("/api/settings"),
    update: (settings: Partial<GlobalSettings>) =>
      req<GlobalSettings>("/api/settings", {
        method: "PUT",
        body: JSON.stringify({ settings }),
      }),
    composeBase: () => req<ComposeBase>("/api/settings/compose-base"),
  },
};

export const DEFAULT_PLACEHOLDERS: Record<ConfigField["type"], string> = {
  storage_path: "Enter host path",
  port: "Enter port number",
  string: "Enter value",
  number: "Enter number",
  boolean: "",
};

export function fieldPlaceholder(field: ConfigField): string {
  if (field.placeholder != null) return field.placeholder;
  return DEFAULT_PLACEHOLDERS[field.type] ?? "";
}

/** Resolve a host path against a compose base + app slug, client-side. */
export function resolveHostPath(hostPath: string, appSlug: string, composeBase: string): string {
  if (!hostPath) return "";
  if (hostPath.startsWith("/")) return hostPath;
  const stripped = hostPath.replace(/^\.\//, "");
  return `${composeBase.replace(/\/$/, "")}/${appSlug}/${stripped}`;
}
