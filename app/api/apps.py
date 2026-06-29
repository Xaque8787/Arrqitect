import asyncio
import json
import secrets
import subprocess
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.db.client import get_db
from app.services.job_runner import enqueue_job, snapshot_app, enqueue_rollback

router = APIRouter(prefix="/api/apps", tags=["apps"])


def _app_row(row) -> dict:
    d = dict(row)
    if isinstance(d.get("config"), str):
        d["config"] = json.loads(d["config"])
    return d


def _tmpl_row(row) -> dict:
    d = dict(row)
    for field in ("config_schema", "hook_definitions", "provides"):
        if isinstance(d.get(field), str):
            d[field] = json.loads(d[field])
    return d


class ActionConfig(BaseModel):
    action_id: str
    variant_id: str
    fields: dict = {}


class InstallRequest(BaseModel):
    template_slug: str
    name: str
    config: dict
    version: str | None = None
    actions: list[ActionConfig] = []


class UpdateConfigRequest(BaseModel):
    config: dict


@router.get("")
async def list_installed():
    async with get_db() as db:
        async with db.execute("""
            SELECT a.*,
                   t.slug AS t_slug, t.name AS t_name, t.icon_url AS t_icon_url,
                   t.latest_version,
                   t.allow_custom_env, t.allow_custom_storage,
                   v.version AS installed_version,
                   v.config_schema, v.hook_definitions, v.provides
            FROM installed_apps a
            JOIN app_templates t ON t.id = a.template_id
            LEFT JOIN template_versions v ON v.id = a.template_version_id
            ORDER BY a.name
        """) as cur:
            rows = await cur.fetchall()

    result = []
    for row in rows:
        d = _app_row(row)
        d["app_templates"] = {
            "slug": d.pop("t_slug"),
            "name": d.pop("t_name"),
            "icon_url": d.pop("t_icon_url"),
            "latest_version": d.pop("latest_version", ""),
            "installed_version": d.pop("installed_version", None),
            "allow_custom_env": bool(d.pop("allow_custom_env", 0)),
            "allow_custom_storage": bool(d.pop("allow_custom_storage", 0)),
            "config_schema": json.loads(d.pop("config_schema")) if isinstance(d.get("config_schema"), str) else d.pop("config_schema", []),
            "hook_definitions": json.loads(d.pop("hook_definitions")) if isinstance(d.get("hook_definitions"), str) else d.pop("hook_definitions", {}),
            "provides": json.loads(d.pop("provides")) if isinstance(d.get("provides"), str) else d.pop("provides", []),
        }
        result.append(d)
    return result


@router.get("/{app_id}")
async def get_installed(app_id: str):
    async with get_db() as db:
        async with db.execute("""
            SELECT a.*,
                   t.slug AS t_slug, t.name AS t_name, t.icon_url AS t_icon_url,
                   t.latest_version,
                   t.allow_custom_env, t.allow_custom_storage,
                   v.version AS installed_version,
                   v.config_schema, v.hook_definitions, v.provides,
                   v.compose AS compose_template
            FROM installed_apps a
            JOIN app_templates t ON t.id = a.template_id
            LEFT JOIN template_versions v ON v.id = a.template_version_id
            WHERE a.id = ?
        """, (app_id,)) as cur:
            row = await cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="App not found")

    d = _app_row(row)
    d["app_templates"] = {
        "slug": d.pop("t_slug"),
        "name": d.pop("t_name"),
        "icon_url": d.pop("t_icon_url"),
        "latest_version": d.pop("latest_version", ""),
        "installed_version": d.pop("installed_version", None),
        "allow_custom_env": bool(d.pop("allow_custom_env", 0)),
        "allow_custom_storage": bool(d.pop("allow_custom_storage", 0)),
        "config_schema": json.loads(d.pop("config_schema")) if isinstance(d.get("config_schema"), str) else d.pop("config_schema", []),
        "hook_definitions": json.loads(d.pop("hook_definitions")) if isinstance(d.get("hook_definitions"), str) else d.pop("hook_definitions", {}),
        "provides": json.loads(d.pop("provides")) if isinstance(d.get("provides"), str) else d.pop("provides", []),
        "compose_template": d.pop("compose_template", ""),
    }
    return d


@router.post("")
async def install_app(req: InstallRequest):
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM app_templates WHERE slug = ?", (req.template_slug,)
        ) as cur:
            tmpl_row = await cur.fetchone()

        if not tmpl_row:
            raise HTTPException(status_code=404, detail="Template not found")
        tmpl = _tmpl_row(tmpl_row)

        target_version = req.version or tmpl.get("latest_version") or None
        version_id = None
        if target_version:
            async with db.execute(
                "SELECT id FROM template_versions WHERE template_id = ? AND version = ?",
                (tmpl["id"], target_version),
            ) as cur:
                ver_row = await cur.fetchone()
            if not ver_row:
                raise HTTPException(
                    status_code=404,
                    detail=f"Template version {target_version!r} not found for {req.template_slug!r}",
                )
            version_id = ver_row["id"]

        app_id = secrets.token_hex(16)
        await db.execute("""
            INSERT INTO installed_apps
                (id, template_id, template_version_id, slug, name, config, state)
            VALUES (?, ?, ?, ?, ?, ?, 'installing')
        """, (app_id, tmpl["id"], version_id, req.template_slug, req.name, json.dumps(req.config)))

        for action in req.actions:
            await db.execute("""
                INSERT INTO app_actions (id, app_id, action_id, variant_id, fields)
                VALUES (?, ?, ?, ?, ?)
            """, (secrets.token_hex(16), app_id, action.action_id, action.variant_id,
                  json.dumps(action.fields)))

        await db.commit()

    job = await enqueue_job(app_id, "install")
    return {"app": {"id": app_id, "slug": req.template_slug, "name": req.name, "version": target_version}, "job": job}


@router.put("/{app_id}/config")
async def update_config(app_id: str, req: UpdateConfigRequest):
    async with get_db() as db:
        async with db.execute("SELECT id FROM installed_apps WHERE id = ?", (app_id,)) as cur:
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="App not found")

    # Snapshot current state before mutating
    await snapshot_app(app_id)

    async with get_db() as db:
        await db.execute(
            "UPDATE installed_apps SET config = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = ?",
            (json.dumps(req.config), app_id),
        )
        await db.commit()

    job = await enqueue_job(app_id, "update")
    return {"job": job}


@router.delete("/{app_id}")
async def remove_app(app_id: str):
    async with get_db() as db:
        async with db.execute("SELECT id FROM installed_apps WHERE id = ?", (app_id,)) as cur:
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="App not found")
        await db.execute(
            "UPDATE installed_apps SET state = 'removing' WHERE id = ?", (app_id,)
        )
        await db.commit()

    job = await enqueue_job(app_id, "remove")
    return {"job": job}


@router.post("/{app_id}/repair")
async def repair_app(app_id: str):
    async with get_db() as db:
        async with db.execute(
            "SELECT id, state FROM installed_apps WHERE id = ?", (app_id,)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="App not found")

    d = dict(row)
    if d["state"] not in ("error", "running", "stopped"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot repair app in state '{d['state']}'"
        )

    job = await enqueue_job(app_id, "repair")
    return {"job": job}


@router.post("/{app_id}/preview")
async def preview(app_id: str):
    from pathlib import Path
    async with get_db() as db:
        async with db.execute(
            "SELECT id, slug, config, compose_path FROM installed_apps WHERE id = ?",
            (app_id,),
        ) as cur:
            row = await cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="App not found")

    d = dict(row)
    config = json.loads(d["config"]) if isinstance(d["config"], str) else (d["config"] or {})
    compose_path = d.get("compose_path") or ""

    compose_rendered = ""
    compose_ok = False
    compose_error: str | None = None

    if not compose_path:
        compose_error = "No compose file recorded — app may still be installing."
    else:
        try:
            compose_rendered = Path(compose_path).read_text()
            compose_ok = True
        except FileNotFoundError:
            compose_error = f"Compose file not found at {compose_path}"
        except Exception as exc:
            compose_error = str(exc)

    return {
        "app_id": app_id,
        "slug": d["slug"],
        "config": config,
        "compose_rendered": compose_rendered,
        "compose_ok": compose_ok,
        "compose_error": compose_error,
        "hook_steps": [],
        "host_compose_path": compose_path,
        "compose_base": "",
    }


# --- Action CRUD ---

@router.get("/{app_id}/actions")
async def list_app_actions(app_id: str):
    async with get_db() as db:
        async with db.execute("SELECT id FROM installed_apps WHERE id = ?", (app_id,)) as cur:
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="App not found")
        async with db.execute(
            "SELECT id, action_id, variant_id, fields, created_at FROM app_actions WHERE app_id = ? ORDER BY created_at",
            (app_id,)
        ) as cur:
            rows = await cur.fetchall()

    result = []
    for row in rows:
        d = dict(row)
        if isinstance(d.get("fields"), str):
            d["fields"] = json.loads(d["fields"])
        d["app_id"] = app_id
        result.append(d)
    return result


@router.post("/{app_id}/actions")
async def create_app_action(app_id: str, action: ActionConfig):
    async with get_db() as db:
        async with db.execute("SELECT id FROM installed_apps WHERE id = ?", (app_id,)) as cur:
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="App not found")

        action_id = secrets.token_hex(16)
        await db.execute("""
            INSERT INTO app_actions (id, app_id, action_id, variant_id, fields)
            VALUES (?, ?, ?, ?, ?)
        """, (action_id, app_id, action.action_id, action.variant_id, json.dumps(action.fields)))
        await db.commit()

    return {
        "id": action_id,
        "app_id": app_id,
        "action_id": action.action_id,
        "variant_id": action.variant_id,
        "fields": action.fields,
    }


@router.delete("/{app_id}/actions/{action_record_id}")
async def delete_app_action(app_id: str, action_record_id: str):
    async with get_db() as db:
        async with db.execute(
            "SELECT id FROM app_actions WHERE id = ? AND app_id = ?",
            (action_record_id, app_id)
        ) as cur:
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Action not found")
        await db.execute("DELETE FROM app_actions WHERE id = ?", (action_record_id,))
        await db.commit()
    return {"ok": True}


@router.post("/{app_id}/actions/{action_record_id}/run")
async def run_app_action(app_id: str, action_record_id: str):
    """Manually re-run a single configured action outside of an install job."""
    from app.services.actions.loader import load_actions_yaml, find_action, find_variant
    from app.services.actions.executor import run_action

    async with get_db() as db:
        async with db.execute(
            "SELECT id, action_id, variant_id, fields FROM app_actions WHERE id = ? AND app_id = ?",
            (action_record_id, app_id)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Action not found")

    record = dict(row)
    if isinstance(record.get("fields"), str):
        record["fields"] = record["fields"]

    actions_yaml = await load_actions_yaml(app_id)
    if not actions_yaml:
        raise HTTPException(status_code=422, detail="No actions defined for this app's template")

    action_def = find_action(actions_yaml, record["action_id"])
    if not action_def:
        raise HTTPException(status_code=422, detail=f"Action {record['action_id']!r} not found in template")

    variant_def = find_variant(action_def, record["variant_id"])
    if not variant_def:
        raise HTTPException(status_code=422, detail=f"Variant {record['variant_id']!r} not found")

    degraded = await run_action(app_id, record, action_def, variant_def, "", None)
    return {"ok": not degraded, "degraded": degraded}


# --- Snapshots & Rollback ---

@router.get("/{app_id}/snapshots")
async def list_snapshots(app_id: str):
    async with get_db() as db:
        async with db.execute("SELECT id FROM installed_apps WHERE id = ?", (app_id,)) as cur:
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="App not found")
        async with db.execute(
            """SELECT s.id, s.installed_app_id, s.template_version_id,
                      s.config, s.ir_hash, s.compose_hash, s.created_at,
                      v.version AS version_label
               FROM app_snapshots s
               LEFT JOIN template_versions v ON v.id = s.template_version_id
               WHERE s.installed_app_id = ?
               ORDER BY s.created_at DESC""",
            (app_id,),
        ) as cur:
            rows = await cur.fetchall()

    result = []
    for row in rows:
        d = dict(row)
        if isinstance(d.get("config"), str):
            try:
                d["config"] = json.loads(d["config"])
            except Exception:
                d["config"] = {}
        result.append(d)
    return result


@router.post("/{app_id}/rollback/{snapshot_id}")
async def rollback_to_snapshot(app_id: str, snapshot_id: str):
    async with get_db() as db:
        async with db.execute("SELECT id FROM installed_apps WHERE id = ?", (app_id,)) as cur:
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="App not found")
        async with db.execute(
            "SELECT id FROM app_snapshots WHERE id = ? AND installed_app_id = ?",
            (snapshot_id, app_id),
        ) as cur:
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Snapshot not found")

    try:
        job = await enqueue_rollback(app_id, snapshot_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"job": job}


# --- Container observability ---

def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("/{app_id}/status")
async def container_status(app_id: str):
    async with get_db() as db:
        async with db.execute(
            "SELECT compose_path, state FROM installed_apps WHERE id = ?", (app_id,)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="App not found")

    d = dict(row)
    compose_path = d.get("compose_path", "")

    if not compose_path or d["state"] in ("staged", "installing", "removing"):
        return {"services": [], "available": False}

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            ["docker", "compose", "-f", compose_path, "ps", "--format", "json", "-a"],
            capture_output=True, text=True, timeout=30,
        ),
    )

    if result.returncode != 0:
        return {"services": [], "available": False, "error": result.stderr.strip() or "docker compose ps failed"}

    services = []
    raw = result.stdout.strip()
    if raw.startswith("["):
        # Some Docker versions return a JSON array
        try:
            items = json.loads(raw)
        except Exception:
            items = []
        for svc in items:
            services.append(_parse_service(svc))
    else:
        # Newer Docker versions return one JSON object per line
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                services.append(_parse_service(json.loads(line)))
            except Exception:
                pass

    return {"services": services, "available": True}


def _parse_service(svc: dict) -> dict:
    return {
        "name": svc.get("Service") or svc.get("Name", ""),
        "state": svc.get("State", ""),
        "status": svc.get("Status", ""),
        "image": svc.get("Image", ""),
        "ports": svc.get("Publishers", []),
    }


@router.get("/{app_id}/logs")
async def container_logs(
    app_id: str,
    service: str | None = Query(default=None),
    lines: int = Query(default=200, ge=1, le=2000),
):
    async with get_db() as db:
        async with db.execute(
            "SELECT compose_path FROM installed_apps WHERE id = ?", (app_id,)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="App not found")

    compose_path = dict(row).get("compose_path", "")
    if not compose_path:
        return {"lines": [], "service": service, "fetched_at": _utcnow()}

    cmd = ["docker", "compose", "-f", compose_path, "logs", f"--tail={lines}"]
    if service:
        cmd.append(service)

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=30),
    )

    output = (result.stdout + result.stderr).strip()
    log_lines = output.splitlines() if output else []

    return {"lines": log_lines, "service": service, "fetched_at": _utcnow()}
