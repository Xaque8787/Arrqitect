"""
Job runner: creates job + step records, executes install/update/remove pipelines.
WebSocket broadcast handled via a simple in-memory subscriber map.
"""

import asyncio
import json
import secrets
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Awaitable

from app.db.client import get_db
from app.services.ecb import (
    render_compose,
    build_env_file_content,
    write_compose_files,
    write_env_only,
)

_subscribers: dict[str, list[Callable[[str], Awaitable[None]]]] = {}


def subscribe(job_id: str, callback: Callable[[str], Awaitable[None]]) -> None:
    _subscribers.setdefault(job_id, []).append(callback)


def unsubscribe(job_id: str, callback: Callable[[str], Awaitable[None]]) -> None:
    lst = _subscribers.get(job_id, [])
    try:
        lst.remove(callback)
    except ValueError:
        pass


async def _broadcast(job_id: str, message: str) -> None:
    for cb in list(_subscribers.get(job_id, [])):
        try:
            await cb(message)
        except Exception:
            pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def enqueue_job(installed_app_id: str, job_type: str, dry_run: bool = False) -> dict:
    job_id = secrets.token_hex(16)
    async with get_db() as db:
        await db.execute("""
            INSERT INTO jobs (id, installed_app_id, type, status, dry_run)
            VALUES (?, ?, ?, 'pending', ?)
        """, (job_id, installed_app_id, job_type, 1 if dry_run else 0))
        await db.commit()

    asyncio.create_task(_run_job(job_id, installed_app_id, job_type, dry_run))
    return {"id": job_id, "type": job_type, "status": "pending", "dry_run": dry_run}


async def _add_step(job_id: str, step: str, status: str, log: str,
                    finished_at: str | None = None) -> None:
    step_id = secrets.token_hex(16)
    now = _now()
    async with get_db() as db:
        await db.execute("""
            INSERT INTO job_steps (id, job_id, step, status, log, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (step_id, job_id, step, status, log, now, finished_at))
        await db.commit()
    await _broadcast(job_id, json.dumps({"type": "step", "step": step, "status": status, "log": log}))


async def _set_job_status(job_id: str, status: str) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), job_id),
        )
        await db.commit()
    await _broadcast(job_id, json.dumps({"type": "job_status", "status": status}))


async def _set_app_state(app_id: str, state: str) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE installed_apps SET state = ?, updated_at = ? WHERE id = ?",
            (state, _now(), app_id),
        )
        await db.commit()


async def _load_app(app_id: str) -> dict | None:
    import json as _json
    async with get_db() as db:
        async with db.execute("""
            SELECT a.*,
                   v.compose        AS compose_template,
                   v.config_schema,
                   v.hook_definitions,
                   v.provides
            FROM installed_apps a
            JOIN app_templates t ON t.id = a.template_id
            LEFT JOIN template_versions v ON v.id = a.template_version_id
            WHERE a.id = ?
        """, (app_id,)) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    d = dict(row)
    if isinstance(d.get("config"), str):
        d["config"] = _json.loads(d["config"])
    d["hook_definitions"] = _json.loads(d["hook_definitions"]) if isinstance(d.get("hook_definitions"), str) else {}
    d["config_schema"] = _json.loads(d["config_schema"]) if isinstance(d.get("config_schema"), str) else []
    return d


async def _run_job(job_id: str, app_id: str, job_type: str, dry_run: bool) -> None:
    await _set_job_status(job_id, "running")
    try:
        app = await _load_app(app_id)
        if not app:
            raise RuntimeError(f"App {app_id} not found")

        if job_type == "install":
            await _run_install(job_id, app_id, app, dry_run)
        elif job_type == "update":
            await _run_update(job_id, app_id, app, dry_run)
        elif job_type == "remove":
            await _run_remove(job_id, app_id, app, dry_run)
        else:
            await _add_step(job_id, job_type, "skipped",
                            f"Job type '{job_type}' not implemented in v1", finished_at=_now())

        await _set_job_status(job_id, "success")

    except Exception as exc:
        await _add_step(job_id, "error", "failed", str(exc), finished_at=_now())
        await _set_job_status(job_id, "failed")
        await _set_app_state(app_id, "error")


async def _run_hooks(job_id: str, hooks: dict, event: str, dry_run: bool) -> None:
    if event not in hooks:
        return
    await _add_step(job_id, f"hook:{event}", "success",
                    f"[DRY/DUMMY] hook '{event}' — no-op in v1", finished_at=_now())


async def _run_install(job_id: str, app_id: str, app: dict, dry_run: bool) -> None:
    hooks = app.get("hook_definitions", {})
    slug = app["slug"]
    config = app.get("config", {})
    schema = app.get("config_schema", [])

    await _add_step(job_id, "render_compose", "running", "Rendering docker-compose.yml from template")
    rendered = render_compose(app["compose_template"], config, schema, slug)
    env_content = build_env_file_content(config, schema, slug)
    await _add_step(job_id, "render_compose", "success", "Compose file rendered", finished_at=_now())

    if not dry_run:
        await _add_step(job_id, "write_compose", "running", "Writing docker-compose.yml and .env to disk")
        compose_path, env_path = write_compose_files(slug, rendered, env_content)
        async with get_db() as db:
            await db.execute(
                "UPDATE installed_apps SET compose_path = ? WHERE id = ?",
                (compose_path, app_id),
            )
            await db.commit()
        await _add_step(job_id, "write_compose", "success",
                        f"Written: {compose_path}\nWritten: {env_path}", finished_at=_now())

    await _run_hooks(job_id, hooks, "pre_install", dry_run)

    if not dry_run:
        await _add_step(job_id, "docker_up", "running", "Running docker compose up -d")
        result = await _docker_compose(compose_path, ["up", "-d"])
        status = "success" if result.returncode == 0 else "failed"
        await _add_step(job_id, "docker_up", status, result.stdout + result.stderr, finished_at=_now())
        if result.returncode != 0:
            raise RuntimeError("docker compose up failed")

    await _run_hooks(job_id, hooks, "post_install", dry_run)
    await _set_app_state(app_id, "running" if not dry_run else "stopped")


async def _run_update(job_id: str, app_id: str, app: dict, dry_run: bool) -> None:
    hooks = app.get("hook_definitions", {})
    slug = app["slug"]
    config = app.get("config", {})
    schema = app.get("config_schema", [])
    compose_path = app.get("compose_path", "")

    await _run_hooks(job_id, hooks, "pre_update", dry_run)

    env_content = build_env_file_content(config, schema, slug)
    non_env_fields = {f["key"] for f in schema if not f.get("env_key")}
    require_rewrite = bool(non_env_fields) or not compose_path or not Path(compose_path).exists()

    if not dry_run:
        if require_rewrite:
            await _add_step(job_id, "render_compose", "running", "Re-rendering docker-compose.yml")
            rendered = render_compose(app["compose_template"], config, schema, slug)
            await _add_step(job_id, "render_compose", "success", "Compose file rendered", finished_at=_now())

            await _add_step(job_id, "write_compose", "running", "Writing docker-compose.yml and .env")
            compose_path, env_path = write_compose_files(slug, rendered, env_content)
            async with get_db() as db:
                await db.execute(
                    "UPDATE installed_apps SET compose_path = ? WHERE id = ?",
                    (compose_path, app_id),
                )
                await db.commit()
            await _add_step(job_id, "write_compose", "success",
                            f"Written: {compose_path}\nWritten: {env_path}", finished_at=_now())
        else:
            await _add_step(job_id, "write_env", "running",
                            "Updating .env (all fields are env-interpolated)")
            env_path = write_env_only(slug, env_content)
            await _add_step(job_id, "write_env", "success", f"Written: {env_path}", finished_at=_now())

        await _add_step(job_id, "docker_pull", "running", "Pulling latest images")
        result = await _docker_compose(compose_path, ["pull"])
        await _add_step(job_id, "docker_pull", "success" if result.returncode == 0 else "failed",
                        result.stdout + result.stderr, finished_at=_now())

        await _add_step(job_id, "docker_up", "running", "Running docker compose up -d")
        result = await _docker_compose(compose_path, ["up", "-d"])
        status = "success" if result.returncode == 0 else "failed"
        await _add_step(job_id, "docker_up", status, result.stdout + result.stderr, finished_at=_now())
        if result.returncode != 0:
            raise RuntimeError("docker compose up failed during update")

    await _run_hooks(job_id, hooks, "post_update", dry_run)
    await _set_app_state(app_id, "running" if not dry_run else "stopped")


async def _run_remove(job_id: str, app_id: str, app: dict, dry_run: bool) -> None:
    compose_path = app.get("compose_path", "")
    slug = app.get("slug", "")

    if not dry_run and compose_path and Path(compose_path).exists():
        # Collect image IDs before stopping so we can remove them precisely.
        await _add_step(job_id, "collect_images", "running", "Collecting image IDs for this app")
        img_result = await _docker_compose(compose_path, ["images", "-q"])
        image_ids = [line.strip() for line in img_result.stdout.splitlines() if line.strip()]
        await _add_step(job_id, "collect_images", "success",
                        f"Found {len(image_ids)} image(s): {', '.join(image_ids) or 'none'}",
                        finished_at=_now())

        await _add_step(job_id, "docker_down", "running", "Running docker compose down")
        result = await _docker_compose(compose_path, ["down"])
        status = "success" if result.returncode == 0 else "failed"
        await _add_step(job_id, "docker_down", status, result.stdout + result.stderr, finished_at=_now())

        if image_ids:
            await _add_step(job_id, "remove_images", "running",
                            f"Removing {len(image_ids)} image(s)")
            rmi_result = await _docker_rmi(image_ids)
            rmi_status = "success" if rmi_result.returncode == 0 else "failed"
            await _add_step(job_id, "remove_images", rmi_status,
                            rmi_result.stdout + rmi_result.stderr, finished_at=_now())

        app_dir = Path(compose_path).parent
        if slug and app_dir.exists() and app_dir.name == slug:
            await _add_step(job_id, "remove_files", "running",
                            f"Removing project directory: {app_dir}")
            try:
                shutil.rmtree(app_dir)
                await _add_step(job_id, "remove_files", "success",
                                f"Removed: {app_dir}", finished_at=_now())
            except Exception as exc:
                await _add_step(job_id, "remove_files", "failed", str(exc), finished_at=_now())

    await _add_step(job_id, "cleanup_db", "running", "Removing app record from database")
    async with get_db() as db:
        await db.execute("DELETE FROM installed_apps WHERE id = ?", (app_id,))
        await db.commit()
    await _add_step(job_id, "cleanup_db", "success", "App record removed", finished_at=_now())


async def _docker_compose(compose_path: str, args: list[str]) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose", "-f", compose_path] + args
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=120),
    )


async def _docker_rmi(image_ids: list[str]) -> subprocess.CompletedProcess:
    cmd = ["docker", "image", "rm"] + image_ids
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=60),
    )
