"""
Phase 4 schema additions.

Changes:
  installed_apps:
    - index on state for efficient queue queries

  jobs:
    - bulk_app_ids TEXT NOT NULL DEFAULT '[]'
      Stores JSON-ordered list of app_ids for bulk_install jobs.
      NULL installed_app_id is already supported (no NOT NULL constraint exists).

  template_versions:
    - validation_warnings TEXT NOT NULL DEFAULT '[]'
      Schema-time warnings stored at sync time (pinned tag, circular requires, etc.)
"""


def upgrade(conn):
    # Index for queue queries
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_installed_apps_state
        ON installed_apps (state)
    """)

    # Bulk job app ids
    try:
        conn.execute(
            "ALTER TABLE jobs ADD COLUMN bulk_app_ids TEXT NOT NULL DEFAULT '[]'"
        )
    except Exception:
        pass

    # Template validation warnings
    try:
        conn.execute(
            "ALTER TABLE template_versions ADD COLUMN validation_warnings TEXT NOT NULL DEFAULT '[]'"
        )
    except Exception:
        pass
