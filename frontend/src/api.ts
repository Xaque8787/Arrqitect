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
  requires?: ConfigRequires[];
}

export interface ConfigRequires {
  app: string;
  config?: string | null;
  action?: string | null;
  severity: "error" | "warning";
  message?: string | null;
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
  state: "staged" | "installing" | "running" | "stopped" | "error" | "removing";
  compose_path: string;
  created_at: string;
  actions?: AppActionRecord[];
  app_templates?: AppTemplate & {
    installed_version: string | null;
    compose_template?: string;
  };
}

export interface Job {
  id: string;
  installed_app_id: string | null;
  type: string;
  status: "pending" | "running" | "success" | "degraded" | "failed" | "cancelled" | "obsolete";
  dry_run: boolean;
  is_reconcile: boolean;
  created_at: string;
  bulk_app_ids?: string[];
  job_steps?: JobStep[];
}

export interface JobStep {
  id: string;
  job_id: string;
  step: string;
  status: "pending" | "running" | "success" | "continue_success" | "failed" | "timeout" | "skipped" | "obsolete";
  log: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ValidationResult {
  severity: "error" | "warning" | "info";
  step_id: string | null;
  message: string;
}

export interface QueueValidationIssue {
  severity: "error" | "warning";
  type: string;
  consumer_app_id: string;
  consumer_app_name: string;
  message: string;
  target_app_slug: string | null;
  field_id: string | null;
  action_id: string | null;
}

export interface QueueValidationResult {
  valid: boolean;
  install_order: string[];
  issues: QueueValidationIssue[];
}

export interface TemplateUpdatePreview {
  up_to_date: boolean;
  from_version: string;
  to_version: string;
  new_required_fields?: ConfigField[];
  removed_fields?: string[];
  new_version_id?: string;
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

export interface ActionFieldDef {
  id: string;
  label: string;
  type: "text" | "boolean" | "number" | "select";
  default: string;
  options?: string[];
  allow_custom?: boolean;
  visibility?: "visible" | "advanced";
}

export interface ActionVariantDef {
  id: string;
  label: string;
  description?: string;
  idempotency_value?: string;
  fields: ActionFieldDef[];
}

export interface ActionDef {
  id: string;
  label: string;
  description?: string;
  variants: ActionVariantDef[];
}

export interface ActionsSchema {
  actions: ActionDef[];
}

export interface AppActionRecord {
  id: string;
  app_id: string;
  action_id: string;
  variant_id: string;
  fields: Record<string, string>;
  created_at?: string;
}

export interface AppSnapshot {
  id: string;
  installed_app_id: string;
  template_version_id: string | null;
  config: Record<string, unknown>;
  ir_hash: string;
  compose_hash: string;
  created_at: string;
  version_label: string | null;
}

export interface ContainerServicePort {
  URL: string;
  TargetPort: number;
  PublishedPort: number;
  Protocol: string;
}

export interface ContainerService {
  name: string;
  state: string;
  status: string;
  image: string;
  ports: ContainerServicePort[];
}

export interface ContainerStatus {
  services: ContainerService[];
  available: boolean;
  error?: string;
}

export interface ContainerLogs {
  lines: string[];
  service: string | null;
  fetched_at: string;
}

export const api = {
  templates: {
    list: () => req<AppTemplate[]>("/api/templates"),
    get: (slug: string) => req<AppTemplate>(`/api/templates/${slug}`),
    versions: (slug: string) => req<TemplateVersion[]>(`/api/templates/${slug}/versions`),
    actions: (slug: string) => req<ActionsSchema>(`/api/templates/${slug}/actions`),
    sync: (repo_url?: string) =>
      req<SyncResult>("/api/templates/sync", {
        method: "POST",
        body: JSON.stringify({ repo_url: repo_url ?? null }),
      }),
  },
  apps: {
    list: () => req<InstalledApp[]>("/api/apps"),
    get: (id: string) => req<InstalledApp>(`/api/apps/${id}`),
    install: (
      template_slug: string,
      name: string,
      config: Record<string, unknown>,
      version?: string,
      actions?: { action_id: string; variant_id: string; fields: Record<string, string> }[],
    ) =>
      req<{ app: InstalledApp; job: Job }>("/api/apps", {
        method: "POST",
        body: JSON.stringify({ template_slug, name, config, version: version ?? null, actions: actions ?? [] }),
      }),
    updateConfig: (id: string, config: Record<string, unknown>) =>
      req<{ job: Job }>(`/api/apps/${id}/config`, {
        method: "PUT",
        body: JSON.stringify({ config }),
      }),
    remove: (id: string) =>
      req<{ job: Job }>(`/api/apps/${id}`, { method: "DELETE" }),
    preview: (id: string) => req<PreviewResult>(`/api/apps/${id}/preview`, { method: "POST" }),
    listActions: (id: string) => req<AppActionRecord[]>(`/api/apps/${id}/actions`),
    createAction: (id: string, action_id: string, variant_id: string, fields: Record<string, string>) =>
      req<AppActionRecord>(`/api/apps/${id}/actions`, {
        method: "POST",
        body: JSON.stringify({ action_id, variant_id, fields }),
      }),
    deleteAction: (id: string, action_record_id: string) =>
      req<{ ok: boolean }>(`/api/apps/${id}/actions/${action_record_id}`, { method: "DELETE" }),
    runAction: (id: string, action_record_id: string) =>
      req<{ ok: boolean; degraded: boolean }>(`/api/apps/${id}/actions/${action_record_id}/run`, { method: "POST" }),
    snapshots: (id: string) =>
      req<AppSnapshot[]>(`/api/apps/${id}/snapshots`),
    rollback: (id: string, snapshot_id: string) =>
      req<{ job: Job }>(`/api/apps/${id}/rollback/${snapshot_id}`, { method: "POST" }),
    containerStatus: (id: string) =>
      req<ContainerStatus>(`/api/apps/${id}/status`),
    containerLogs: (id: string, service?: string, lines?: number) => {
      const params = new URLSearchParams();
      if (service) params.set("service", service);
      if (lines) params.set("lines", String(lines));
      const qs = params.toString();
      return req<ContainerLogs>(`/api/apps/${id}/logs${qs ? `?${qs}` : ""}`);
    },
  },
  queue: {
    list: () => req<InstalledApp[]>("/api/queue"),
    stage: (
      template_slug: string,
      name: string,
      config: Record<string, unknown>,
      version?: string,
      actions?: { action_id: string; variant_id: string; fields: Record<string, string> }[],
    ) =>
      req<{ id: string; slug: string; name: string; state: "staged" }>("/api/queue/stage", {
        method: "POST",
        body: JSON.stringify({ template_slug, name, config, version: version ?? null, actions: actions ?? [] }),
      }),
    update: (
      app_id: string,
      config: Record<string, unknown>,
      actions?: { action_id: string; variant_id: string; fields: Record<string, string> }[],
    ) =>
      req<{ ok: boolean }>(`/api/queue/${app_id}`, {
        method: "PUT",
        body: JSON.stringify({ config, actions: actions ?? [] }),
      }),
    remove: (app_id: string) =>
      req<{ ok: boolean }>(`/api/queue/${app_id}`, { method: "DELETE" }),
    validate: () => req<QueueValidationResult>("/api/queue/validate", { method: "POST" }),
    install: (force = false) =>
      req<{ job: Job; install_order: string[] }>("/api/queue/install", {
        method: "POST",
        body: JSON.stringify({ force }),
      }),
    previewUpdate: (app_id: string) =>
      req<TemplateUpdatePreview>(`/api/queue/app-update/${app_id}/preview`),
    commitUpdate: (app_id: string, extra_config?: Record<string, unknown>) =>
      req<{ job: Job }>(`/api/queue/app-update/${app_id}/commit`, {
        method: "POST",
        body: JSON.stringify({ extra_config: extra_config ?? {} }),
      }),
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
