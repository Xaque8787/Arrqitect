"""
Enumerate-Configure-Build (ECB) service.
Resolves app config, renders Jinja2 compose template, writes output to host compose dir.
"""

import os
import asyncio
from pathlib import Path
from jinja2 import Environment, BaseLoader, StrictUndefined

HOST_COMPOSE_DIR = os.environ.get("HOST_COMPOSE_DIR", "/compose")
CONTAINER_COMPOSE_DIR = "/compose"


def resolve_host_path(relative: str, app_slug: str) -> str:
    """Convert a relative dot-notation path to an absolute host path."""
    base = Path(HOST_COMPOSE_DIR) / app_slug
    p = Path(relative)
    if p.is_absolute():
        return str(p)
    # Strip leading ./ if present
    parts = p.parts
    if parts and parts[0] in (".", "./"):
        p = Path(*parts[1:])
    return str(base / p)


def render_compose(template_str: str, config: dict, app_slug: str) -> str:
    env = Environment(
        loader=BaseLoader(),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    env.globals["resolve_host_path"] = lambda rel: resolve_host_path(rel, app_slug)
    tmpl = env.from_string(template_str)
    return tmpl.render(**config)


def write_compose_file(app_slug: str, content: str) -> str:
    """Write rendered compose file to container path, returns container path."""
    app_dir = Path(CONTAINER_COMPOSE_DIR) / app_slug
    app_dir.mkdir(parents=True, exist_ok=True)
    compose_path = app_dir / "docker-compose.yml"
    compose_path.write_text(content)
    return str(compose_path)


async def preview_app(app_row: dict) -> dict:
    """Return a dry-run preview without writing files or running containers."""
    template = app_row["app_templates"]
    config = app_row.get("config", {})
    slug = app_row["slug"]

    try:
        rendered = render_compose(template["compose_template"], config, slug)
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
        "host_compose_path": str(Path(HOST_COMPOSE_DIR) / slug / "docker-compose.yml"),
    }
