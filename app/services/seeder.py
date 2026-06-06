"""
Seeds the bundled app templates from the local templates/ directory.

Reads each template.yaml file from disk and ingests it through the same
pipeline as template_sync, so schema_version 2 templates go through the
ECB parser and produce structured service_definitions rather than raw
compose strings.

Idempotent — existing template versions with matching content hashes are
skipped silently.
"""

import json
import secrets
from pathlib import Path

from app.db.client import get_sync_conn
from app.services.ecb.parser import parse_template, PassthroughTemplate, ParseError
from app.services.template_sync import _ingest_template, ImmutabilityViolation

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"


def seed_templates() -> None:
    conn = get_sync_conn()
    checked = 0
    try:
        for template_dir in sorted(TEMPLATES_DIR.iterdir()):
            if not template_dir.is_dir():
                continue
            yaml_file = template_dir / "template.yaml"
            if not yaml_file.exists():
                continue

            raw_text = yaml_file.read_text()
            source_url = str(yaml_file)
            actions_file = template_dir / "actions.yaml"
            actions_text = actions_file.read_text() if actions_file.exists() else ""
            try:
                result = _ingest_template(raw_text, source_url, conn, actions_text)
                checked += 1
                status = result.get("status", "?")
                slug = result.get("slug", template_dir.name)
                if status != "unchanged":
                    print(f"[seeder] {slug}: {status}")
            except ImmutabilityViolation as exc:
                print(f"[seeder] {template_dir.name}: immutability violation — {exc}")
            except Exception as exc:
                print(f"[seeder] {template_dir.name}: error — {exc}")

        conn.commit()
        print(f"[seeder] Templates seeded ({checked} checked)")
    finally:
        conn.close()
