def upgrade(conn):
    # app_registry: capability integration bus
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_registry (
            id           TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            provider_id  TEXT NOT NULL REFERENCES installed_apps(id) ON DELETE CASCADE,
            key          TEXT NOT NULL,
            value        TEXT NOT NULL DEFAULT '',
            type         TEXT NOT NULL DEFAULT 'metadata'
                             CHECK (type IN ('credential','endpoint','metadata','feature-flag')),
            sensitive    INTEGER NOT NULL DEFAULT 0,
            rotates      INTEGER NOT NULL DEFAULT 0,
            published_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            UNIQUE (provider_id, key)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_registry_key
        ON app_registry(key)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_registry_provider
        ON app_registry(provider_id)
    """)

    # ir_hash: canonical desired state hash (computed over AppIR before rendering)
    try:
        conn.execute("""
            ALTER TABLE installed_apps ADD COLUMN ir_hash TEXT NOT NULL DEFAULT ''
        """)
    except Exception:
        pass

    # compose_hash: renderer artifact hash (for file drift detection)
    try:
        conn.execute("""
            ALTER TABLE installed_apps ADD COLUMN compose_hash TEXT NOT NULL DEFAULT ''
        """)
    except Exception:
        pass

    # service_definitions: structured service data for schema_version 2 templates
    try:
        conn.execute("""
            ALTER TABLE template_versions ADD COLUMN service_definitions TEXT NOT NULL DEFAULT ''
        """)
    except Exception:
        pass

    # has_passthrough: marks schema_version 1 templates as legacy passthrough
    try:
        conn.execute("""
            ALTER TABLE template_versions ADD COLUMN has_passthrough INTEGER NOT NULL DEFAULT 0
        """)
    except Exception:
        pass
