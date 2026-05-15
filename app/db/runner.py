"""
Migration runner.

How it works
------------
1. Ensures a `migrations` table exists (idempotent).
2. Scans app/db/migrations/ for files matching NNNN_*.py in sorted order.
3. Skips any filename already recorded in the `migrations` table.
4. Imports and calls upgrade(conn) on each unapplied migration.
5. Records the filename on success.

Writing a migration
-------------------
Create app/db/migrations/NNNN_short_description.py with:

    def upgrade(conn):
        conn.execute(\"\"\"
            ALTER TABLE foo ADD COLUMN bar TEXT NOT NULL DEFAULT ''
        \"\"\")
        # Use IF NOT EXISTS / column existence checks for all DDL so the
        # migration is safe to run against a fresh DB that already has the
        # column from init.py (though the runner won't call it on fresh DBs
        # since the migrations table starts empty and the column already exists).

ALSO update app/db/init.py so new installs get the correct schema without
needing to run this migration.
"""

import importlib.util
import os
import sqlite3
from pathlib import Path

from app.db.client import get_sync_conn

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS migrations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    filename   TEXT UNIQUE NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""


def _applied(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT filename FROM migrations").fetchall()
    return {r[0] for r in rows}


def _migration_files() -> list[Path]:
    files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.py"))
    return files


def run_migrations() -> None:
    conn = get_sync_conn()
    try:
        conn.execute(CREATE_MIGRATIONS_TABLE)
        conn.commit()

        applied = _applied(conn)
        pending = [f for f in _migration_files() if f.name not in applied]

        if not pending:
            print("[migrations] All up to date")
            return

        for path in pending:
            print(f"[migrations] Applying {path.name} ...")
            spec = importlib.util.spec_from_file_location(path.stem, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.upgrade(conn)
            conn.execute(
                "INSERT OR IGNORE INTO migrations (filename) VALUES (?)", (path.name,)
            )
            conn.commit()
            print(f"[migrations] Applied  {path.name}")

    finally:
        conn.close()
