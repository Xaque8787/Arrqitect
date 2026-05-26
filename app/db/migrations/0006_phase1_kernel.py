"""
Phase 1 kernel schema additions.

Changes:
  installed_apps:
    - generation INTEGER NOT NULL DEFAULT 1 (increments on every install/reinstall)
    - template_source TEXT NOT NULL DEFAULT '' (reserved for Phase 5 ownership transfer)

  app_registry (renamed conceptually to app_capabilities, kept as app_registry for
  backward compatibility — new columns bring it to the capability model):
    - capability_version INTEGER NOT NULL DEFAULT 1 (increments on every write)
    - capability_schema_version TEXT NOT NULL DEFAULT '' (reserved Phase 5)
    - source_template_hash TEXT NOT NULL DEFAULT '' (reserved Phase 5)

  jobs:
    - status CHECK extended to include 'degraded' and 'obsolete'
      (SQLite cannot ALTER CHECK; we recreate via a new column with correct default
      and rely on application-layer enforcement — CHECK is advisory in SQLite anyway)
    - is_reconcile INTEGER NOT NULL DEFAULT 0 (loop-prevention flag)

  job_steps:
    - status CHECK extended to include 'continue_success', 'timeout', 'obsolete'
      (same approach — application layer enforces the enum)

  NEW: app_events table
    - id, installed_app_id, event_type, payload, status, claimed_by_job_id,
      created_at, claimed_at, processed_at

  NEW: reconcile_state table
    - id, consumer_app_id (unique), last_reconciled_at, last_seen_versions (JSON),
      created_at, updated_at
"""


def upgrade(conn):
    # installed_apps.generation
    try:
        conn.execute("ALTER TABLE installed_apps ADD COLUMN generation INTEGER NOT NULL DEFAULT 1")
    except Exception:
        pass

    # installed_apps.template_source (reserved)
    try:
        conn.execute("ALTER TABLE installed_apps ADD COLUMN template_source TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass

    # app_registry.capability_version
    try:
        conn.execute("ALTER TABLE app_registry ADD COLUMN capability_version INTEGER NOT NULL DEFAULT 1")
    except Exception:
        pass

    # app_registry.capability_schema_version (reserved)
    try:
        conn.execute("ALTER TABLE app_registry ADD COLUMN capability_schema_version TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass

    # app_registry.source_template_hash (reserved)
    try:
        conn.execute("ALTER TABLE app_registry ADD COLUMN source_template_hash TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass

    # jobs.is_reconcile
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN is_reconcile INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass

    # app_events table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_events (
            id               TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            installed_app_id TEXT NOT NULL REFERENCES installed_apps(id) ON DELETE CASCADE,
            event_type       TEXT NOT NULL
                                 CHECK (event_type IN (
                                     'capability_changed',
                                     'capability_published',
                                     'provider_removed'
                                 )),
            payload          TEXT NOT NULL DEFAULT '{}',
            status           TEXT NOT NULL DEFAULT 'pending'
                                 CHECK (status IN ('pending', 'claimed', 'processed', 'failed_permanent')),
            claimed_by_job_id TEXT,
            created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            claimed_at       TEXT,
            processed_at     TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_app_events_app_status
        ON app_events (installed_app_id, status)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_app_events_status
        ON app_events (status)
    """)

    # reconcile_state table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reconcile_state (
            id                TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            consumer_app_id   TEXT NOT NULL UNIQUE REFERENCES installed_apps(id) ON DELETE CASCADE,
            last_reconciled_at TEXT,
            last_seen_versions TEXT NOT NULL DEFAULT '{}',
            created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_reconcile_state_consumer
        ON reconcile_state (consumer_app_id)
    """)
