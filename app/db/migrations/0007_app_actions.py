"""
Phase 3 schema additions.

Changes:
  template_versions:
    - actions_definitions TEXT NOT NULL DEFAULT ''
      Stores the raw YAML content of actions.yaml for the template version.
      Empty string means no actions defined for this template.

  NEW: app_actions table
    - id, app_id, action_id, variant_id, fields, created_at
    - app_id references installed_apps(id) ON DELETE CASCADE
    - fields stores JSON of user-provided field values
"""


def upgrade(conn):
    # template_versions.actions_definitions
    try:
        conn.execute(
            "ALTER TABLE template_versions ADD COLUMN actions_definitions TEXT NOT NULL DEFAULT ''"
        )
    except Exception:
        pass

    # app_actions table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_actions (
            id         TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            app_id     TEXT NOT NULL REFERENCES installed_apps(id) ON DELETE CASCADE,
            action_id  TEXT NOT NULL,
            variant_id TEXT NOT NULL,
            fields     TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_app_actions_app ON app_actions (app_id)
    """)
