def upgrade(conn):
    # Partial unique index: at most one active (pending|running) job per app per type.
    # The WHERE clause limits enforcement to active rows only, so historical jobs are unaffected.
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_one_active_per_app_type
        ON jobs (installed_app_id, type)
        WHERE status IN ('pending', 'running')
    """)
