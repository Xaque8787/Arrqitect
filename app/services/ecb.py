"""
Enumerate-Configure-Build (ECB) service.

At render time:
  - Global settings (puid, pgid, timezone) are fetched from the DB and injected.
  - volume_mount fields store only host_path in the app config (key -> host_path).
    The template uses {{ key_host }} and {{ key_container }} variables.
    key_host comes from config; key_container comes from the schema's container_path.
  - Relative host paths (starting with ./) are resolved against the compose_base,
    which is derived from docker inspect on the arrqitect container.
"""

import json
import os
import subprocess
from pathlib import Path
from jinja2 import Environment, BaseLoader, StrictUndefined

from app.db.client import get_sync_conn

CONTAINER_COMPOSE_DIR = "/compose"


def _get_compose_base() -> str:
    """
    Return the host-side path mapped to /compose in the arrqitect container.
    Falls back to the env var HOST_COMPOSE_DIR, then to /compose as a last resort.
    """
    env_override = os.environ.get("HOST_COMPOSE_DIR", "")
    if env_override:
        return env_override

    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{json .Mounts}}", "arrqitect"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            mounts = json.loads(result.stdout)
            mount = next(
                (m for m in mounts if m.get("Destination") == "/compose"),
                None,
            )
            if mount and mount.get("Source"):
                return mount["Source"]
    except Exception:
        pass

    return CONTAINER_COMPOSE_DIR


def _get_global_settings() -> dict:
    conn = get_sync_conn()
    try:
        rows = conn.execute("SELECT key, value FROM global_settings").fetchall()
        s = {r[0]: r[1] for r in rows}
        return {
            "puid": s.get("puid", "1000"),
            "pgid": s.get("pgid", "1000"),
            "timezone": s.get("timezone", "Etc/UTC"),
        }
    finally:
        conn.close()


def resolve_host_path(host_path: str, app_slug: str, compose_base: str) -> str:
    """
    Resolve a host path value from the user.
    - Absolute paths pass through unchanged.
    - Relative paths (./foo) resolve to compose_base / app_slug / foo.
    """
    p = Path(host_path)
    if p.is_absolute():
        return str(p)
    parts = p.parts
    if parts and parts[0] == ".":
        p = Path(*parts[1:]) if len(parts) > 1 else Path("")
    return str(Path(compose_base) / app_slug / p)


def _build_render_context(config: dict, schema: list, app_slug: str, compose_base: str) -> dict:
    """
    Build the Jinja2 render context from the stored config + schema metadata.
    For volume_mount fields: injects {key}_host (resolved) and {key}_container.
    All other fields are passed through as-is.
    """
    ctx = {}
    schema_map = {f["key"]: f for f in schema}

    for field in schema:
        key = field["key"]
        ftype = field.get("type")

        if ftype == "volume_mount":
            raw_host = config.get(key, str(field.get("default", "")))
            ctx[f"{key}_host"] = resolve_host_path(raw_host, app_slug, compose_base)
            ctx[f"{key}_container"] = field.get("container_path", f"/{key}")
        else:
            ctx[key] = config.get(key, field.get("default", ""))

    return ctx


def render_compose(template_str: str, config: dict, schema: list, app_slug: str) -> str:
    compose_base = _get_compose_base()
    global_settings = _get_global_settings()

    ctx = _build_render_context(config, schema, app_slug, compose_base)
    ctx.update(global_settings)

    env = Environment(
        loader=BaseLoader(),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    return env.from_string(template_str).render(**ctx)


def write_compose_file(app_slug: str, content: str) -> str:
    app_dir = Path(CONTAINER_COMPOSE_DIR) / app_slug
    app_dir.mkdir(parents=True, exist_ok=True)
    compose_path = app_dir / "docker-compose.yml"
    compose_path.write_text(content)
    return str(compose_path)


async def preview_app(app_row: dict) -> dict:
    template = app_row["app_templates"]
    config = app_row.get("config", {})
    schema = template.get("config_schema", [])
    slug = app_row["slug"]

    compose_base = _get_compose_base()

    try:
        rendered = render_compose(template["compose_template"], config, schema, slug)
        compose_ok = True
        compose_error = None
    except Exception as exc:
        rendered = ""
        compose_ok = False
        compose_error = str(exc)

    hooks = template.get("hook_definitions", {})
    hook_steps = [
        {"hook": name, "action": "[DRY/DUMMY] would execute (no-op in v1)"}
        for name in hooks
    ]

    return {
        "app_id": app_row["id"],
        "slug": slug,
        "config": config,
        "compose_rendered": rendered,
        "compose_ok": compose_ok,
        "compose_error": compose_error,
        "hook_steps": hook_steps,
        "host_compose_path": str(Path(compose_base) / slug / "docker-compose.yml"),
        "compose_base": compose_base,
    }
