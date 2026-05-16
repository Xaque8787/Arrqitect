def upgrade(conn):
    # allow_custom_env: template declares users may add arbitrary env vars
    try:
        conn.execute("""
            ALTER TABLE app_templates ADD COLUMN allow_custom_env INTEGER NOT NULL DEFAULT 0
        """)
    except Exception:
        pass

    # allow_custom_storage: template declares users may add arbitrary volume mounts
    try:
        conn.execute("""
            ALTER TABLE app_templates ADD COLUMN allow_custom_storage INTEGER NOT NULL DEFAULT 0
        """)
    except Exception:
        pass
