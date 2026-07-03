"""
Template sync service.

Fetches template definitions from a remote repository URL (or local filesystem
fallback), validates them, hashes the canonical payload, and writes immutable
template_versions records into the catalog.

Schema version dispatch:
  - schema_version 2: parsed via ECB parser into a TemplateModel, stored with
    service_definitions populated and has_passthrough=0. The compose column is
    left empty — rendering is done at install time by the ECB + renderer pipeline.
  - schema_version 1 (legacy): stored as compose passthrough. has_passthrough=1.
    The compose column holds the raw compose string for the legacy render path.

Flow per template:
  1. Fetch index.json  → list of slugs + paths
  2. For each slug: fetch template.yaml
  3. Optionally fetch actions.yaml from the same directory (non-fatal if absent)
  4. Validate (schema_version dispatch)
  5. Compute content_hash over canonical payload
  6. Skip if (template_id, version) + same hash already exists (no-op)
  7. Reject overwrite if same (template_id, version) but different hash
  8. Write new template_version row; update app_templates catalog row
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
from app.services.ecb.parser import parse_template, PassthroughTemplate, ParseError

SUPPORTED_SCHEMA_VERSIONS = {1, 2}
DEFAULT_REPO_URL = "/app/templates"
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


def _validate_v1(raw: dict) -> None:
    required = ["schema_version", "slug", "name", "version", "compose", "config_schema"]
    for field in required:
        if field not in raw:
            raise SyncError(f"Missing required field: {field}")
    if not SEMVER_RE.match(str(raw["version"])):
        raise SyncError(f"version must be semver (x.y.z), got: {raw['version']!r}")
    if not isinstance(raw["config_schema"], list):
        raise SyncError("config_schema must be a list")


def _fetch_text(url_or_path: str, client: httpx.Client | None) -> str:
    if url_or_path.startswith("http://") or url_or_path.startswith("https://"):
        resp = client.get(url_or_path, timeout=15)
        resp.raise_for_status()
        return resp.text
    from pathlib import Path
    return Path(url_or_path).read_text()


def _fetch_text_optional(url_or_path: str, client: httpx.Client | None) -> str | None:
    """Fetch text without raising — returns None if not found or any error."""
    try:
        if url_or_path.startswith("http://") or url_or_path.startswith("https://"):
            resp = client.get(url_or_path, timeout=10)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.text
        from pathlib import Path
        p = Path(url_or_path)
        return p.read_text() if p.exists() else None
    except Exception:
        return None


def _actions_url(template_url: str) -> str:
    """Derive the actions.yaml URL/path from the template.yaml URL/path."""
    if template_url.startswith("http://") or template_url.startswith("https://"):
        base = template_url.rsplit("/", 1)[0]
        return f"{base}/actions.yaml"
    from pathlib import Path
    return str(Path(template_url).parent / "actions.yaml")


def _ingest_template(raw_text: str, source_url: str, conn, actions_text: str | None = None) -> dict:
    """
    Validate, hash, and write one template version into the DB.
    Dispatches on schema_version.
    Returns a status dict describing what happened.
    """
    raw = yaml.safe_load(raw_text)
    if not isinstance(raw, dict):
        raise SyncError("Template must be a YAML mapping")

    sv = raw.get("schema_version", 1)

    if sv == 2:
        return _ingest_v2(raw_text, raw, source_url, conn, actions_text or "")
    elif sv == 1:
        return _ingest_v1(raw, source_url, conn, actions_text or "")
    else:
        raise SyncError(f"Unsupported schema_version: {sv!r}")


def _check_pinned_tag_warnings(template_model) -> list[str]:
    """Return warning strings for services using tag: latest."""
    warnings = []
    for svc in template_model.services:
        if svc.image.tag == "latest":
            warnings.append(
                f"Service '{svc.id}' uses tag: latest — updates will not be detectable. "
                "Use a pinned version tag."
            )
    return warnings


def _ingest_v2(raw_text: str, raw: dict, source_url: str, conn, actions_text: str) -> dict:
    """Ingest a schema_version 2 template via ECB parser."""
    try:
        template_model = parse_template(raw_text)
    except ParseError as exc:
        raise SyncError(f"Template parse error: {exc}") from exc

    slug = template_model.app.id
    version = template_model.app.version
    name = template_model.app.name

    if not SEMVER_RE.match(version):
        raise SyncError(f"version must be semver (x.y.z), got: {version!r}")

    service_definitions = template_model.model_dump_json()

    canonical_payload = {
        "slug": slug,
        "version": version,
        "schema_version": 2,
        "service_definitions": service_definitions,
        "provides": [p.model_dump() for p in template_model.provides],
        "consumes": [c.model_dump() for c in template_model.consumes],
    }
    content_hash = _content_hash(canonical_payload)

    provides_json = json.dumps([p.model_dump() for p in template_model.provides])
    consumes_json = json.dumps([c.model_dump() for c in template_model.consumes])
    config_schema_json = json.dumps([f.model_dump() for f in template_model.config_schema])
    hooks_json = json.dumps(template_model.hooks)
    description = raw.get("description", "")
    icon_url = raw.get("icon_url", "")
    validation_warnings_json = json.dumps(_check_pinned_tag_warnings(template_model))

    template_id = _upsert_app_template(
        conn, slug, name, description, icon_url, source_url,
        compose_template="",
        config_schema=config_schema_json,
        hook_definitions=hooks_json,
        provides=provides_json,
        allow_custom_env=template_model.app.allow_custom_env,
        allow_custom_storage=template_model.app.allow_custom_storage,
    )

    existing_ver = conn.execute(
        "SELECT id, content_hash FROM template_versions WHERE template_id = ? AND version = ?",
        (template_id, version),
    ).fetchone()

    if existing_ver:
        if existing_ver[1] == content_hash:
            conn.execute(
                "UPDATE app_templates SET latest_version = ? WHERE id = ?",
                (version, template_id),
            )
            # config_schema and hook_definitions are not part of the content hash
            # but can evolve independently (e.g. sensitive flag, labels, hooks).
            # Always keep template_versions in sync with the current disk state.
            update_fields: list = [config_schema_json, hooks_json]
            update_sql = "UPDATE template_versions SET config_schema = ?, hook_definitions = ?"
            if actions_text:
                update_fields.append(actions_text)
                update_sql += ", actions_definitions = ?"
            update_fields.append(existing_ver[0])
            conn.execute(update_sql + " WHERE id = ?", update_fields)
            return {"slug": slug, "version": version, "status": "unchanged"}
        raise ImmutabilityViolation(
            f"{slug}@{version} already published with a different content hash. "
            "Bump the version number."
        )

    version_id = secrets.token_hex(16)
    conn.execute("""
        INSERT INTO template_versions
            (id, template_id, version, schema_version, content_hash,
             compose, config_schema, hook_definitions, provides, consumes,
             service_definitions, has_passthrough, actions_definitions, validation_warnings)
        VALUES (?, ?, ?, 2, ?, '', ?, ?, ?, ?, ?, 0, ?, ?)
    """, (
        version_id, template_id, version, content_hash,
        config_schema_json, hooks_json, provides_json, consumes_json,
        service_definitions, actions_text, validation_warnings_json,
    ))

    conn.execute(
        "UPDATE app_templates SET latest_version = ? WHERE id = ?",
        (version, template_id),
    )

    return {"slug": slug, "version": version, "status": "added"}


def _ingest_v1(raw: dict, source_url: str, conn, actions_text: str) -> dict:
    """Ingest a schema_version 1 (legacy passthrough) template."""
    _validate_v1(raw)

    slug = raw["slug"]
    version = str(raw["version"])

    canonical_payload = {
        "slug": slug,
        "version": version,
        "schema_version": 1,
        "compose": raw["compose"],
        "config_schema": raw["config_schema"],
        "hook_definitions": raw.get("hooks", {}),
        "provides": raw.get("provides", []),
        "consumes": raw.get("consumes", []),
    }
    content_hash = _content_hash(canonical_payload)

    template_id = _upsert_app_template(
        conn, slug, raw["name"],
        raw.get("description", ""),
        raw.get("icon_url", ""),
        source_url,
        compose_template=raw["compose"],
        config_schema=json.dumps(raw["config_schema"]),
        hook_definitions=json.dumps(raw.get("hooks", {})),
        provides=json.dumps(raw.get("provides", [])),
    )

    existing_ver = conn.execute(
        "SELECT id, content_hash FROM template_versions WHERE template_id = ? AND version = ?",
        (template_id, version),
    ).fetchone()

    if existing_ver:
        if existing_ver[1] == content_hash:
            conn.execute(
                "UPDATE app_templates SET latest_version = ? WHERE id = ?",
                (version, template_id),
            )
            if actions_text:
                conn.execute(
                    "UPDATE template_versions SET actions_definitions = ? WHERE id = ?",
                    (actions_text, existing_ver[0]),
                )
            return {"slug": slug, "version": version, "status": "unchanged"}
        raise ImmutabilityViolation(
            f"{slug}@{version} already published with a different content hash. "
            "Bump the version number."
        )

    version_id = secrets.token_hex(16)
    conn.execute("""
        INSERT INTO template_versions
            (id, template_id, version, schema_version, content_hash,
             compose, config_schema, hook_definitions, provides, consumes,
             service_definitions, has_passthrough, actions_definitions)
        VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, '', 1, ?)
    """, (
        version_id, template_id, version, content_hash,
        raw["compose"],
        json.dumps(raw["config_schema"]),
        json.dumps(raw.get("hooks", {})),
        json.dumps(raw.get("provides", [])),
        json.dumps(raw.get("consumes", [])),
        actions_text,
    ))

    conn.execute(
        "UPDATE app_templates SET latest_version = ? WHERE id = ?",
        (version, template_id),
    )

    return {"slug": slug, "version": version, "status": "added"}


def _upsert_app_template(
    conn, slug: str, name: str, description: str, icon_url: str, source_url: str,
    compose_template: str, config_schema: str, hook_definitions: str, provides: str,
    allow_custom_env: bool = False, allow_custom_storage: bool = False,
) -> str:
    # INSERT OR IGNORE avoids a UNIQUE constraint race when two workers seed concurrently.
    # The UPDATE that follows ensures the row is always current regardless of which
    # worker won the INSERT.
    new_id = secrets.token_hex(16)
    conn.execute("""
        INSERT OR IGNORE INTO app_templates
            (id, slug, name, description, icon_url, source_url,
             compose_template, config_schema, hook_definitions, provides,
             allow_custom_env, allow_custom_storage)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        new_id, slug, name, description, icon_url, source_url,
        compose_template, config_schema, hook_definitions, provides,
        int(allow_custom_env), int(allow_custom_storage),
    ))
    row = conn.execute("SELECT id FROM app_templates WHERE slug = ?", (slug,)).fetchone()
    template_id = row[0]
    conn.execute("""
        UPDATE app_templates SET
            name                 = ?,
            description          = ?,
            icon_url             = ?,
            source_url           = ?,
            compose_template     = ?,
            config_schema        = ?,
            hook_definitions     = ?,
            provides             = ?,
            allow_custom_env     = ?,
            allow_custom_storage = ?,
            updated_at           = ?
        WHERE id = ?
    """, (
        name, description, icon_url, source_url,
        compose_template, config_schema, hook_definitions, provides,
        int(allow_custom_env), int(allow_custom_storage),
        _now(), template_id,
    ))
    return template_id


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

            templates_list = index.get("templates", [])

            conn = get_sync_conn()
            try:
                for entry in templates_list:
                    slug = entry.get("slug", "?")
                    path = entry.get("path", "")
                    template_url = f"{repo_url}/{path}"
                    try:
                        raw_text = _fetch_text(template_url, client)
                        actions_text = _fetch_text_optional(_actions_url(template_url), client)
                        result = _ingest_template(raw_text, template_url, conn, actions_text)
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
