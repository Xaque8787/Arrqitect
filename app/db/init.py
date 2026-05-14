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
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    slug        TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    icon_url    TEXT NOT NULL DEFAULT '',
    compose_template TEXT NOT NULL DEFAULT '',
    config_schema    TEXT NOT NULL DEFAULT '[]',
    hook_definitions TEXT NOT NULL DEFAULT '{}',
    provides         TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS installed_apps (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    template_id TEXT NOT NULL REFERENCES app_templates(id),
    slug        TEXT NOT NULL,
    name        TEXT NOT NULL,
    config      TEXT NOT NULL DEFAULT '{}',
    state       TEXT NOT NULL DEFAULT 'stopped'
                    CHECK (state IN ('installing','running','stopped','error','removing')),
    compose_path TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
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
                         CHECK (status IN ('pending','running','success','failed','cancelled')),
    dry_run          INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS job_steps (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    job_id      TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    step        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','running','success','failed','skipped')),
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
CREATE INDEX IF NOT EXISTS idx_job_steps_job           ON job_steps(job_id);
"""


def init_db() -> None:
    conn = get_sync_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        print("[db] Schema initialized")
    finally:
        conn.close()
