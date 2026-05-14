"""
Job runner: creates job + step records, executes install/update/remove/reconcile pipelines.
WebSocket broadcast handled via a simple in-memory subscriber map.
"""

import asyncio
import subprocess
import json
from datetime import datetime, timezone
from typing import Callable, Awaitable
from pathlib import Path

from app.db.client import get_client
from app.services.ecb import render_compose, write_compose_file

# job_id -> list of async callables that receive a log line
_subscribers: dict[str, list[Callable[[str], Awaitable[None]]]] = {}


def subscribe(job_id: str, callback: Callable[[str], Awaitable[None]]):
    _subscribers.setdefault(job_id, []).append(callback)


def unsubscribe(job_id: str, callback: Callable[[str], Awaitable[None]]):
    if job_id in _subscribers:
        _subscribers[job_id].discard(callback) if hasattr(_subscribers[job_id], "discard") else None
        try:
            _subscribers[job_id].remove(callback)
        except ValueError:
            pass


async def _broadcast(job_id: str, message: str):
    for cb in list(_subscribers.get(job_id, [])):
        try:
            await cb(message)
        except Exception:
            pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def enqueue_job(installed_app_id: str, job_type: str, dry_run: bool = False) -> dict:
    db = get_client()
    job = db.table("jobs").insert({
        "installed_app_id": installed_app_id,
        "type": job_type,
        "status": "pending",
        "dry_run": dry_run,
    }).execute().data[0]

    asyncio.create_task(_run_job(job["id"], installed_app_id, job_type, dry_run))
    return job


async def _add_step(job_id: str, step: str, status: str, log: str, started_at: str = None, finished_at: str = None):
    db = get_client()
    row = db.table("job_steps").insert({
        "job_id": job_id,
        "step": step,
        "status": status,
        "log": log,
        "started_at": started_at or _now(),
        "finished_at": finished_at,
    }).execute().data[0]
    msg = json.dumps({"type": "step", "step": step, "status": status, "log": log})
    await _broadcast(job_id, msg)
    return row


async def _update_job_status(job_id: str, status: str):
    db = get_client()
    db.table("jobs").update({"status": status, "updated_at": _now()}).eq("id", job_id).execute()
    await _broadcast(job_id, json.dumps({"type": "job_status", "status": status}))


async def _run_job(job_id: str, app_id: str, job_type: str, dry_run: bool):
    db = get_client()
    await _update_job_status(job_id, "running")

    try:
        app = db.table("installed_apps").select("*, app_templates(*)").eq("id", app_id).maybeSingle().execute().data
        if not app:
            raise RuntimeError(f"App {app_id} not found")

        template = app["app_templates"]
        config = app.get("config", {})
        slug = app["slug"]

        if job_type == "install":
            await _run_install(job_id, app_id, slug, template, config, dry_run)
        elif job_type == "update":
            await _run_update(job_id, app_id, slug, template, config, dry_run)
        elif job_type == "remove":
            await _run_remove(job_id, app_id, slug, app.get("compose_path", ""), dry_run)
        else:
            await _add_step(job_id, job_type, "skipped", f"Job type '{job_type}' not implemented in v1", finished_at=_now())

        await _update_job_status(job_id, "success")

    except Exception as exc:
        await _add_step(job_id, "error", "failed", str(exc), finished_at=_now())
        await _update_job_status(job_id, "failed")
        db.table("installed_apps").update({"state": "error"}).eq("id", app_id).execute()


async def _run_hooks(job_id: str, hooks: dict, event: str, dry_run: bool):
    hook = hooks.get(event)
    if not hook:
        return
    label = f"hook:{event}"
    log = f"[DRY/DUMMY] hook '{event}' — no-op in v1"
    await _add_step(job_id, label, "success", log, finished_at=_now())


async def _run_install(job_id, app_id, slug, template, config, dry_run):
    db = get_client()
    hooks = template.get("hook_definitions", {})

    await _add_step(job_id, "render_compose", "running", "Rendering docker-compose.yml from template", finished_at=None)
    rendered = render_compose(template["compose_template"], config, slug)
    await _add_step(job_id, "render_compose", "success", "Compose file rendered successfully", finished_at=_now())

    if not dry_run:
        await _add_step(job_id, "write_compose", "running", "Writing compose file to disk", finished_at=None)
        compose_path = write_compose_file(slug, rendered)
        db.table("installed_apps").update({"compose_path": compose_path}).eq("id", app_id).execute()
        await _add_step(job_id, "write_compose", "success", f"Compose file written: {compose_path}", finished_at=_now())

    await _run_hooks(job_id, hooks, "pre_install", dry_run)

    if not dry_run:
        await _add_step(job_id, "docker_up", "running", "Running docker compose up -d", finished_at=None)
        app_row = db.table("installed_apps").select("compose_path").eq("id", app_id).maybeSingle().execute().data
        result = await _docker_compose(app_row["compose_path"], ["up", "-d"])
        status = "success" if result.returncode == 0 else "failed"
        log = result.stdout + result.stderr
        await _add_step(job_id, "docker_up", status, log, finished_at=_now())
        if result.returncode != 0:
            raise RuntimeError("docker compose up failed")

    await _run_hooks(job_id, hooks, "post_install", dry_run)

    db.table("installed_apps").update({"state": "running" if not dry_run else "stopped"}).eq("id", app_id).execute()


async def _run_update(job_id, app_id, slug, template, config, dry_run):
    db = get_client()
    hooks = template.get("hook_definitions", {})

    await _run_hooks(job_id, hooks, "pre_update", dry_run)

    await _add_step(job_id, "render_compose", "running", "Re-rendering docker-compose.yml", finished_at=None)
    rendered = render_compose(template["compose_template"], config, slug)
    await _add_step(job_id, "render_compose", "success", "Compose file rendered", finished_at=_now())

    if not dry_run:
        compose_path = write_compose_file(slug, rendered)
        db.table("installed_apps").update({"compose_path": compose_path}).eq("id", app_id).execute()

        await _add_step(job_id, "docker_pull", "running", "Pulling latest images", finished_at=None)
        result = await _docker_compose(compose_path, ["pull"])
        await _add_step(job_id, "docker_pull", "success" if result.returncode == 0 else "failed",
                        result.stdout + result.stderr, finished_at=_now())

        await _add_step(job_id, "docker_up", "running", "Running docker compose up -d", finished_at=None)
        result = await _docker_compose(compose_path, ["up", "-d"])
        status = "success" if result.returncode == 0 else "failed"
        await _add_step(job_id, "docker_up", status, result.stdout + result.stderr, finished_at=_now())
        if result.returncode != 0:
            raise RuntimeError("docker compose up failed during update")

    await _run_hooks(job_id, hooks, "post_update", dry_run)
    db.table("installed_apps").update({"state": "running" if not dry_run else "stopped"}).eq("id", app_id).execute()


async def _run_remove(job_id, app_id, slug, compose_path, dry_run):
    db = get_client()

    if not dry_run and compose_path and Path(compose_path).exists():
        await _add_step(job_id, "docker_down", "running", "Running docker compose down", finished_at=None)
        result = await _docker_compose(compose_path, ["down"])
        status = "success" if result.returncode == 0 else "failed"
        await _add_step(job_id, "docker_down", status, result.stdout + result.stderr, finished_at=_now())

    await _add_step(job_id, "cleanup_db", "running", "Removing app record from database", finished_at=None)
    db.table("installed_apps").delete().eq("id", app_id).execute()
    await _add_step(job_id, "cleanup_db", "success", "App record removed", finished_at=_now())


async def _docker_compose(compose_path: str, args: list[str]) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose", "-f", compose_path] + args
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    )
    return result
