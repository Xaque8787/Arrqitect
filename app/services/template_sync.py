"""
Template sync service.

Fetches template definitions from a remote repository URL (or local filesystem
fallback), validates them, hashes the canonical payload, and writes immutable
template_versions records into the catalog.

Flow per template:
  1. Fetch index.json  → list of slugs + paths
  2. For each slug: fetch template.yaml
  3. Structural validation (required fields, known schema_version, semver)
  4. Compute content_hash over canonical payload
  5. Skip if (template_id, version) + same hash already exists (no-op)
  6. Reject overwrite if same (template_id, version) but different hash
  7. Write new template_version row; update app_templates catalog row

The runtime (ECB, job_runner) reads only from template_versions — never from
the raw source again after ingestion.
"""

import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from typing import Any

import httpx
import yaml

from app.db.client import get_sync_conn

SUPPORTED_SCHEMA_VERSIONS = {1}
DEFAULT_REPO_URL = "https://raw.githubusercontent.com/Xaque8787/Arrqitect/dev/templates"
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class SyncError(Exception):
    pass


class ImmutabilityViolation(SyncError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _content_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _validate_template(raw: dict) -> None:
    required = ["schema_version", "slug", "name", "version", "compose", "config_schema"]
    for field in required:
        if field not in raw:
            raise SyncError(f"Missing required field: {field}")

    sv = raw["schema_version"]
    if sv not in SUPPORTED_SCHEMA_VERSIONS:
        raise SyncError(
            f"Unsupported schema_version {sv!r}. "
            f"Supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )

    if not SEMVER_RE.match(str(raw["version"])):
        raise SyncError(f"version must be semver (x.y.z), got: {raw['version']!r}")

    if not isinstance(raw["config_schema"], list):
        raise SyncError("config_schema must be a list")

    for i, field in enumerate(raw["config_schema"]):
        for f in ("key", "label", "type"):
            if f not in field:
                raise SyncError(f"config_schema[{i}] missing field: {f!r}")


def _fetch_text(url_or_path: str, client: httpx.Client | None) -> str:
    if url_or_path.startswith("http://") or url_or_path.startswith("https://"):
        resp = client.get(url_or_path, timeout=15)
        resp.raise_for_status()
        return resp.text
    # local filesystem fallback
    from pathlib import Path
    return Path(url_or_path).read_text()


def _build_hook_definitions(raw_hooks: dict) -> dict:
    """Convert hooks map (event → path) to hook_definitions (event → description).
    Hook YAML files contain a description field. For Phase 1, we store the
    description string. The compiled steps list is stored separately for Phase 2.
    """
    return {event: path for event, path in raw_hooks.items()}


def _ingest_template(raw: dict, source_url: str, conn) -> dict:
    """
    Validate, hash, and write one template version into the DB.
    Returns a status dict describing what happened.
    """
    _validate_template(raw)

    slug = raw["slug"]
    version = str(raw["version"])
    schema_version = int(raw["schema_version"])

    canonical_payload = {
        "slug": slug,
        "version": version,
        "schema_version": schema_version,
        "compose": raw["compose"],
        "config_schema": raw["config_schema"],
        "hook_definitions": raw.get("hooks", {}),
        "provides": raw.get("provides", []),
        "consumes": raw.get("consumes", []),
    }
    content_hash = _content_hash(canonical_payload)

    # Upsert app_templates catalog row (name/description/icon can change freely)
    existing = conn.execute(
        "SELECT id FROM app_templates WHERE slug = ?", (slug,)
    ).fetchone()

    if existing:
        template_id = existing[0]
        conn.execute("""
            UPDATE app_templates SET
                name           = ?,
                description    = ?,
                icon_url       = ?,
                source_url     = ?,
                compose_template = ?,
                config_schema    = ?,
                hook_definitions = ?,
                provides         = ?,
                updated_at       = ?
            WHERE id = ?
        """, (
            raw["name"],
            raw.get("description", ""),
            raw.get("icon_url", ""),
            source_url,
            raw["compose"],
            json.dumps(raw["config_schema"]),
            json.dumps(raw.get("hooks", {})),
            json.dumps(raw.get("provides", [])),
            _now(),
            template_id,
        ))
    else:
        template_id = secrets.token_hex(16)
        conn.execute("""
            INSERT INTO app_templates
                (id, slug, name, description, icon_url, source_url,
                 compose_template, config_schema, hook_definitions, provides)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            template_id,
            slug,
            raw["name"],
            raw.get("description", ""),
            raw.get("icon_url", ""),
            source_url,
            raw["compose"],
            json.dumps(raw["config_schema"]),
            json.dumps(raw.get("hooks", {})),
            json.dumps(raw.get("provides", [])),
        ))

    # Check for existing version record
    existing_ver = conn.execute(
        "SELECT id, content_hash FROM template_versions WHERE template_id = ? AND version = ?",
        (template_id, version),
    ).fetchone()

    if existing_ver:
        if existing_ver[1] == content_hash:
            # Nothing changed — update latest_version pointer and skip
            conn.execute(
                "UPDATE app_templates SET latest_version = ? WHERE id = ?",
                (version, template_id),
            )
            return {"slug": slug, "version": version, "status": "unchanged"}
        else:
            raise ImmutabilityViolation(
                f"{slug}@{version} already published with a different content hash. "
                "Published versions are immutable. Bump the version number."
            )

    # New version — write it
    version_id = secrets.token_hex(16)
    conn.execute("""
        INSERT INTO template_versions
            (id, template_id, version, schema_version, content_hash,
             compose, config_schema, hook_definitions, provides, consumes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        version_id,
        template_id,
        version,
        schema_version,
        content_hash,
        raw["compose"],
        json.dumps(raw["config_schema"]),
        json.dumps(raw.get("hooks", {})),
        json.dumps(raw.get("provides", [])),
        json.dumps(raw.get("consumes", [])),
    ))

    # Update latest_version on the catalog row
    conn.execute(
        "UPDATE app_templates SET latest_version = ? WHERE id = ?",
        (version, template_id),
    )

    return {"slug": slug, "version": version, "status": "added"}


def sync_templates(repo_url: str | None = None) -> dict:
    """
    Main entry point. Fetches and ingests all templates from repo_url.
    Returns a summary dict with per-template results and any errors.
    """
    if not repo_url:
        repo_url = _get_repo_url_from_db()

    repo_url = repo_url.rstrip("/")
    results = []
    errors = []

    try:
        with httpx.Client(follow_redirects=True) as client:
            # Step 1: fetch index
            index_url = f"{repo_url}/index.json"
            try:
                index_text = _fetch_text(index_url, client)
                index = json.loads(index_text)
            except Exception as exc:
                return {
                    "ok": False,
                    "error": f"Failed to fetch index from {index_url}: {exc}",
                    "results": [],
                }

            index_sv = index.get("schema_version", 1)
            if index_sv not in SUPPORTED_SCHEMA_VERSIONS:
                return {
                    "ok": False,
                    "error": f"Unsupported index schema_version: {index_sv}",
                    "results": [],
                }

            templates_list = index.get("templates", [])

            conn = get_sync_conn()
            try:
                for entry in templates_list:
                    slug = entry.get("slug", "?")
                    path = entry.get("path", "")
                    template_url = f"{repo_url}/{path}"
                    try:
                        raw_text = _fetch_text(template_url, client)
                        raw = yaml.safe_load(raw_text)
                        result = _ingest_template(raw, template_url, conn)
                        results.append(result)
                    except ImmutabilityViolation as exc:
                        errors.append({"slug": slug, "error": str(exc)})
                    except Exception as exc:
                        errors.append({"slug": slug, "error": str(exc)})

                conn.commit()
            finally:
                conn.close()

    except Exception as exc:
        return {"ok": False, "error": str(exc), "results": results}

    return {
        "ok": len(errors) == 0,
        "results": results,
        "errors": errors,
        "synced_at": _now(),
        "repo_url": repo_url,
    }


def _get_repo_url_from_db() -> str:
    conn = get_sync_conn()
    try:
        row = conn.execute(
            "SELECT value FROM global_settings WHERE key = 'template_repo_url'"
        ).fetchone()
        return row[0] if row else DEFAULT_REPO_URL
    finally:
        conn.close()
