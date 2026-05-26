"""
Full schema initialization. Runs on every startup via CREATE TABLE IF NOT EXISTS.
Always reflects the current desired state — new installs get the complete schema
without needing to run any migrations.

When you add a migration that alters the schema, also update this file so fresh
installs are correct from the start.
"""

from app.db.client import get_sync_conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS app_templates (
    id             TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    slug           TEXT UNIQUE NOT NULL,
    name           TEXT NOT NULL,
    description    TEXT NOT NULL DEFAULT '',
    icon_url       TEXT NOT NULL DEFAULT '',
    source_url     TEXT NOT NULL DEFAULT '',
    latest_version TEXT NOT NULL DEFAULT '',
    compose_template TEXT NOT NULL DEFAULT '',
    config_schema    TEXT NOT NULL DEFAULT '[]',
    hook_definitions TEXT NOT NULL DEFAULT '{}',
    provides         TEXT NOT NULL DEFAULT '[]',
    allow_custom_env     INTEGER NOT NULL DEFAULT 0,
    allow_custom_storage INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS template_versions (
    id                  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    template_id         TEXT NOT NULL REFERENCES app_templates(id) ON DELETE CASCADE,
    version             TEXT NOT NULL,
    schema_version      INTEGER NOT NULL DEFAULT 1,
    content_hash        TEXT NOT NULL,
    compose             TEXT NOT NULL DEFAULT '',
    config_schema       TEXT NOT NULL DEFAULT '[]',
    hook_definitions    TEXT NOT NULL DEFAULT '{}',
    provides            TEXT NOT NULL DEFAULT '[]',
    consumes            TEXT NOT NULL DEFAULT '[]',
    service_definitions TEXT NOT NULL DEFAULT '',
    has_passthrough     INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (template_id, version)
);

CREATE INDEX IF NOT EXISTS idx_template_versions_template ON template_versions(template_id);

CREATE TABLE IF NOT EXISTS installed_apps (
    id                  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    template_id         TEXT NOT NULL REFERENCES app_templates(id),
    template_version_id TEXT REFERENCES template_versions(id) ON DELETE SET NULL,
    slug                TEXT NOT NULL,
    name                TEXT NOT NULL,
    config              TEXT NOT NULL DEFAULT '{}',
    state               TEXT NOT NULL DEFAULT 'stopped'
                            CHECK (state IN ('installing','running','stopped','error','removing')),
    compose_path        TEXT NOT NULL DEFAULT '',
    ir_hash             TEXT NOT NULL DEFAULT '',
    compose_hash        TEXT NOT NULL DEFAULT '',
    generation          INTEGER NOT NULL DEFAULT 1,
    template_source     TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS app_registry (
    id                       TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    provider_id              TEXT NOT NULL REFERENCES installed_apps(id) ON DELETE CASCADE,
    key                      TEXT NOT NULL,
    value                    TEXT NOT NULL DEFAULT '',
    type                     TEXT NOT NULL DEFAULT 'metadata'
                                 CHECK (type IN ('credential','endpoint','metadata','feature-flag')),
    sensitive                INTEGER NOT NULL DEFAULT 0,
    rotates                  INTEGER NOT NULL DEFAULT 0,
    capability_version       INTEGER NOT NULL DEFAULT 1,
    capability_schema_version TEXT NOT NULL DEFAULT '',
    source_template_hash     TEXT NOT NULL DEFAULT '',
    published_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (provider_id, key)
);

CREATE TABLE IF NOT EXISTS runtime_dependencies (
    id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    consumer_id     TEXT NOT NULL REFERENCES installed_apps(id) ON DELETE CASCADE,
    provider_id     TEXT NOT NULL REFERENCES installed_apps(id) ON DELETE CASCADE,
    dependency_type TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (consumer_id, provider_id, dependency_type)
);

CREATE TABLE IF NOT EXISTS jobs (
    id               TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    installed_app_id TEXT REFERENCES installed_apps(id) ON DELETE SET NULL,
    type             TEXT NOT NULL
                         CHECK (type IN ('install','update','remove','reconcile','preview')),
    status           TEXT NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending','running','success','degraded','failed','cancelled','obsolete')),
    dry_run          INTEGER NOT NULL DEFAULT 0,
    is_reconcile     INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS job_steps (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    job_id      TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    step        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN (
                        'pending','running','success','continue_success',
                        'failed','timeout','skipped','obsolete'
                    )),
    log         TEXT NOT NULL DEFAULT '',
    started_at  TEXT,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_installed_apps_template ON installed_apps(template_id);
CREATE INDEX IF NOT EXISTS idx_installed_apps_slug     ON installed_apps(slug);
CREATE INDEX IF NOT EXISTS idx_runtime_deps_consumer   ON runtime_dependencies(consumer_id);
CREATE INDEX IF NOT EXISTS idx_runtime_deps_provider   ON runtime_dependencies(provider_id);
CREATE INDEX IF NOT EXISTS idx_jobs_app                ON jobs(installed_app_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status             ON jobs(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_one_active_per_app_type
    ON jobs (installed_app_id, type)
    WHERE status IN ('pending', 'running');
CREATE INDEX IF NOT EXISTS idx_job_steps_job           ON job_steps(job_id);
CREATE INDEX IF NOT EXISTS idx_registry_key            ON app_registry(key);
CREATE INDEX IF NOT EXISTS idx_registry_provider       ON app_registry(provider_id);

CREATE TABLE IF NOT EXISTS global_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS app_events (
    id                TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    installed_app_id  TEXT NOT NULL REFERENCES installed_apps(id) ON DELETE CASCADE,
    event_type        TEXT NOT NULL
                          CHECK (event_type IN (
                              'capability_changed',
                              'capability_published',
                              'provider_removed'
                          )),
    payload           TEXT NOT NULL DEFAULT '{}',
    status            TEXT NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'claimed', 'processed', 'failed_permanent')),
    claimed_by_job_id TEXT,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    claimed_at        TEXT,
    processed_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_app_events_app_status ON app_events (installed_app_id, status);
CREATE INDEX IF NOT EXISTS idx_app_events_status     ON app_events (status);

CREATE TABLE IF NOT EXISTS reconcile_state (
    id                 TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    consumer_app_id    TEXT NOT NULL UNIQUE REFERENCES installed_apps(id) ON DELETE CASCADE,
    last_reconciled_at TEXT,
    last_seen_versions TEXT NOT NULL DEFAULT '{}',
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_reconcile_state_consumer ON reconcile_state (consumer_app_id);
"""


def init_db() -> None:
    conn = get_sync_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        print("[db] Schema initialized")
    finally:
        conn.close()
