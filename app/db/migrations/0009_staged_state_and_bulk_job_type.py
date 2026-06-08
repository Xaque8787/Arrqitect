"""
Add 'staged' to installed_apps.state CHECK constraint and
'bulk_install' to jobs.type CHECK constraint.

SQLite does not support ALTER COLUMN, so both tables must be
recreated with PRAGMA foreign_keys=OFF / rename / copy / drop.
"""


def upgrade(conn):
    conn.executescript("""
        PRAGMA foreign_keys = OFF;

        -- ── installed_apps ──────────────────────────────────────────────────
        CREATE TABLE installed_apps_new (
            id                  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            template_id         TEXT NOT NULL REFERENCES app_templates(id),
            template_version_id TEXT REFERENCES template_versions(id) ON DELETE SET NULL,
            slug                TEXT NOT NULL,
            name                TEXT NOT NULL,
            config              TEXT NOT NULL DEFAULT '{}',
            state               TEXT NOT NULL DEFAULT 'stopped'
                                    CHECK (state IN ('staged','installing','running','stopped','error','removing')),
            compose_path        TEXT NOT NULL DEFAULT '',
            ir_hash             TEXT NOT NULL DEFAULT '',
            compose_hash        TEXT NOT NULL DEFAULT '',
            generation          INTEGER NOT NULL DEFAULT 1,
            template_source     TEXT NOT NULL DEFAULT '',
            created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        );

        INSERT INTO installed_apps_new SELECT * FROM installed_apps;
        DROP TABLE installed_apps;
        ALTER TABLE installed_apps_new RENAME TO installed_apps;

        -- Recreate indexes dropped with the old table
        CREATE INDEX IF NOT EXISTS idx_installed_apps_template ON installed_apps(template_id);
        CREATE INDEX IF NOT EXISTS idx_installed_apps_slug     ON installed_apps(slug);
        CREATE INDEX IF NOT EXISTS idx_installed_apps_state    ON installed_apps(state);

        -- ── jobs ─────────────────────────────────────────────────────────────
        CREATE TABLE jobs_new (
            id               TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            installed_app_id TEXT REFERENCES installed_apps(id) ON DELETE SET NULL,
            type             TEXT NOT NULL
                                 CHECK (type IN ('install','update','remove','reconcile','preview','bulk_install')),
            status           TEXT NOT NULL DEFAULT 'pending'
                                 CHECK (status IN ('pending','running','success','degraded','failed','cancelled','obsolete')),
            dry_run          INTEGER NOT NULL DEFAULT 0,
            is_reconcile     INTEGER NOT NULL DEFAULT 0,
            bulk_app_ids     TEXT NOT NULL DEFAULT '[]',
            created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        );

        INSERT INTO jobs_new SELECT
            id, installed_app_id, type, status, dry_run, is_reconcile,
            COALESCE(bulk_app_ids, '[]'),
            created_at, updated_at
        FROM jobs;
        DROP TABLE jobs;
        ALTER TABLE jobs_new RENAME TO jobs;

        -- Recreate indexes dropped with the old table
        CREATE INDEX IF NOT EXISTS idx_jobs_app    ON jobs(installed_app_id);
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_one_active_per_app_type
            ON jobs (installed_app_id, type)
            WHERE status IN ('pending', 'running');

        PRAGMA foreign_keys = ON;
    """)
