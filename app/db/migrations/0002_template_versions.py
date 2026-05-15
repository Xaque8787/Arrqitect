def upgrade(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS template_versions (
            id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            template_id     TEXT NOT NULL REFERENCES app_templates(id) ON DELETE CASCADE,
            version         TEXT NOT NULL,
            schema_version  INTEGER NOT NULL DEFAULT 1,
            content_hash    TEXT NOT NULL,
            compose         TEXT NOT NULL DEFAULT '',
            config_schema   TEXT NOT NULL DEFAULT '[]',
            hook_definitions TEXT NOT NULL DEFAULT '{}',
            provides        TEXT NOT NULL DEFAULT '[]',
            consumes        TEXT NOT NULL DEFAULT '[]',
            created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            UNIQUE (template_id, version)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_template_versions_template
        ON template_versions(template_id)
    """)

    # Add template_version_id to installed_apps (nullable for backwards compat)
    try:
        conn.execute("""
            ALTER TABLE installed_apps ADD COLUMN template_version_id
            TEXT REFERENCES template_versions(id) ON DELETE SET NULL
        """)
    except Exception:
        pass

    # Add source_url to app_templates so we know where each template was fetched from
    try:
        conn.execute("""
            ALTER TABLE app_templates ADD COLUMN source_url TEXT NOT NULL DEFAULT ''
        """)
    except Exception:
        pass

    # Add latest_version to app_templates as a convenience pointer
    try:
        conn.execute("""
            ALTER TABLE app_templates ADD COLUMN latest_version TEXT NOT NULL DEFAULT ''
        """)
    except Exception:
        pass
