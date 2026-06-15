"""
Phase 5 schema additions.

Changes:
  NEW: app_snapshots table
    - Captures installed_apps state (template_version_id, config, ir_hash, compose_hash)
      before every update job. Capped at 5 per app by application layer.
    - Used for both auto-rollback on failed updates and manual user-initiated rollback.

  jobs:
    - type CHECK extended to include 'rollback'
    - meta TEXT NOT NULL DEFAULT '{}' — stores snapshot_id for rollback jobs
"""


def upgrade(conn):
    # app_snapshots table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_snapshots (
            id                  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            installed_app_id    TEXT NOT NULL REFERENCES installed_apps(id) ON DELETE CASCADE,
            template_version_id TEXT,
            config              TEXT NOT NULL DEFAULT '{}',
            ir_hash             TEXT NOT NULL DEFAULT '',
            compose_hash        TEXT NOT NULL DEFAULT '',
            created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_snapshots_app_created
        ON app_snapshots (installed_app_id, created_at DESC)
    """)

    # Recreate jobs with 'rollback' in type CHECK + meta column
    conn.executescript("""
        PRAGMA foreign_keys = OFF;

        CREATE TABLE jobs_new (
            id               TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            installed_app_id TEXT REFERENCES installed_apps(id) ON DELETE SET NULL,
            type             TEXT NOT NULL
                                 CHECK (type IN (
                                     'install','update','remove','reconcile',
                                     'preview','bulk_install','rollback'
                                 )),
            status           TEXT NOT NULL DEFAULT 'pending'
                                 CHECK (status IN (
                                     'pending','running','success','degraded',
                                     'failed','cancelled','obsolete'
                                 )),
            dry_run          INTEGER NOT NULL DEFAULT 0,
            is_reconcile     INTEGER NOT NULL DEFAULT 0,
            bulk_app_ids     TEXT NOT NULL DEFAULT '[]',
            meta             TEXT NOT NULL DEFAULT '{}',
            created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        );

        INSERT INTO jobs_new
            (id, installed_app_id, type, status, dry_run, is_reconcile, bulk_app_ids, meta, created_at, updated_at)
        SELECT
            id, installed_app_id, type, status, dry_run, is_reconcile,
            COALESCE(bulk_app_ids, '[]'), '{}', created_at, updated_at
        FROM jobs;

        DROP TABLE jobs;
        ALTER TABLE jobs_new RENAME TO jobs;

        CREATE INDEX IF NOT EXISTS idx_jobs_app    ON jobs(installed_app_id);
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_one_active_per_app_type
            ON jobs (installed_app_id, type)
            WHERE status IN ('pending', 'running');

        PRAGMA foreign_keys = ON;
    """)
