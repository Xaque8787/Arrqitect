"""
Enumerate-Configure-Build (ECB) service.

At render time:
  - Global settings (puid, pgid, timezone) are fetched from the DB and always
    written to .env as PUID, PGID, TZ.
  - Each config_schema field may declare an optional `env_key`. If present:
      - The field value is written to .env as ENV_KEY=<resolved_value>.
      - The compose template uses ${ENV_KEY:-default} Docker-native interpolation.
      - For volume_mount fields: the resolved host path is written to .env.
    If absent:
      - The value is rendered directly into the compose file via Jinja2.
      - For volume_mount fields without env_key: {key}_host and {key}_container
        are injected into the Jinja2 context.
  - Relative host paths (e.g. ./config) resolve to compose_base/app_slug/subpath.
"""

import json
import os
import subprocess
from pathlib import Path
from jinja2 import Environment, BaseLoader, StrictUndefined

from app.db.client import get_sync_conn

CONTAINER_COMPOSE_DIR = "/compose"

# Global settings always map to these fixed env var names.
GLOBAL_ENV_MAP = {
    "puid": "PUID",
    "pgid": "PGID",
    "timezone": "TZ",
}


def _get_compose_base() -> str:
    env_override = os.environ.get("HOST_COMPOSE_DIR", "")
    if env_override and os.path.isabs(env_override):
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
    Resolve a host path value.
    Absolute paths pass through unchanged.
    Relative paths resolve to compose_base/app_slug/subpath.
    """
    p = Path(host_path)
    if p.is_absolute():
        return str(p)
    parts = p.parts
    if parts and parts[0] == ".":
        p = Path(*parts[1:]) if len(parts) > 1 else Path("")
    return str(Path(compose_base) / app_slug / p)


def _build_env_vars(config: dict, schema: list, app_slug: str, compose_base: str,
                    global_settings: dict) -> dict[str, str]:
    """
    Build the dict of ENV_KEY -> value for the .env file.
    Includes global settings and any schema field that declares env_key.
    """
    env_vars: dict[str, str] = {}

    for internal_key, env_key in GLOBAL_ENV_MAP.items():
        env_vars[env_key] = str(global_settings[internal_key])

    for field in schema:
        env_key = field.get("env_key")
        if not env_key:
            continue

        key = field["key"]
        ftype = field.get("type")

        if ftype == "volume_mount":
            raw = config.get(key, str(field.get("default", "")))
            env_vars[env_key] = resolve_host_path(raw, app_slug, compose_base)
        else:
            env_vars[env_key] = str(config.get(key, field.get("default", "")))

    return env_vars


def _build_jinja2_context(config: dict, schema: list, app_slug: str,
                          compose_base: str) -> dict:
    """
    Build the Jinja2 render context for fields that do NOT have env_key.
    volume_mount fields without env_key inject {key}_host and {key}_container.
    Other fields without env_key inject the value directly.
    """
    ctx: dict = {}
    for field in schema:
        if field.get("env_key"):
            continue

        key = field["key"]
        ftype = field.get("type")

        if ftype == "volume_mount":
            raw = config.get(key, str(field.get("default", "")))
            ctx[f"{key}_host"] = resolve_host_path(raw, app_slug, compose_base)
            ctx[f"{key}_container"] = field.get("container_path", f"/{key}")
        else:
            ctx[key] = config.get(key, field.get("default", ""))

    return ctx


def needs_compose_rewrite(changed_keys: set[str], schema: list) -> bool:
    """
    Return True if any changed field lacks an env_key (requires compose file rewrite).
    """
    schema_map = {f["key"]: f for f in schema}
    for key in changed_keys:
        field = schema_map.get(key)
        if field and not field.get("env_key"):
            return True
    return False


def render_compose(template_str: str, config: dict, schema: list, app_slug: str) -> str:
    """
    Render the compose template via Jinja2.
    Only fields without env_key are substituted; ${VAR} tokens pass through literally.
    """
    compose_base = _get_compose_base()
    ctx = _build_jinja2_context(config, schema, app_slug, compose_base)

    jinja_env = Environment(
        loader=BaseLoader(),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    return jinja_env.from_string(template_str).render(**ctx)


def build_env_file_content(config: dict, schema: list, app_slug: str,
                           global_settings: dict | None = None) -> str:
    """Build the string content for the .env file."""
    compose_base = _get_compose_base()
    if global_settings is None:
        global_settings = _get_global_settings()

    env_vars = _build_env_vars(config, schema, app_slug, compose_base, global_settings)

    lines = []
    for k, v in env_vars.items():
        if any(c in v for c in (" ", "#", "\n")):
            v = f'"{v}"'
        lines.append(f"{k}={v}")
    return "\n".join(lines) + "\n"


def write_compose_files(app_slug: str, compose_content: str, env_content: str) -> tuple[str, str]:
    """
    Write docker-compose.yml and .env to the app's project directory.
    Returns (compose_path, env_path).
    """
    app_dir = Path(CONTAINER_COMPOSE_DIR) / app_slug
    app_dir.mkdir(parents=True, exist_ok=True)

    compose_path = app_dir / "docker-compose.yml"
    compose_path.write_text(compose_content)

    env_path = app_dir / ".env"
    env_path.write_text(env_content)

    return str(compose_path), str(env_path)


def write_env_only(app_slug: str, env_content: str) -> str:
    """Overwrite only the .env file. Returns the env file path."""
    env_path = Path(CONTAINER_COMPOSE_DIR) / app_slug / ".env"
    env_path.write_text(env_content)
    return str(env_path)


# Legacy shim retained for any callers that haven't been updated yet.
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
    global_settings = _get_global_settings()

    try:
        rendered = render_compose(template["compose_template"], config, schema, slug)
        env_content = build_env_file_content(config, schema, slug, global_settings)
        compose_ok = True
        compose_error = None
    except Exception as exc:
        rendered = ""
        env_content = ""
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
        "env_rendered": env_content,
        "compose_ok": compose_ok,
        "compose_error": compose_error,
        "hook_steps": hook_steps,
        "host_compose_path": str(Path(compose_base) / slug / "docker-compose.yml"),
        "host_env_path": str(Path(compose_base) / slug / ".env"),
        "compose_base": compose_base,
    }
