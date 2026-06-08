"""
Queue API endpoints for staged app management and bulk install.

Endpoints:
  POST   /api/queue/stage                — stage a new app (no deploy)
  GET    /api/queue                      — list staged apps in install order
  PUT    /api/queue/{app_id}             — update staged app config/actions
  DELETE /api/queue/{app_id}             — remove staged app from queue
  POST   /api/queue/validate             — run validation pass (dry, no side effects)
  POST   /api/queue/install              — commit: validate + enqueue bulk install job
"""

import json
import secrets
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.db.client import get_db
from app.services.queue.resolver import resolve_install_order
from app.services.queue.validator import validate_queue

router = APIRouter(prefix="/api/queue", tags=["queue"])


def _parse_json(value, default):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value if value is not None else default


def _staged_row(row) -> dict:
    d = dict(row)
    d["config"] = _parse_json(d.get("config"), {})
    d["config_schema"] = _parse_json(d.get("config_schema"), [])
    d["provides"] = _parse_json(d.get("provides"), [])
    d["hook_definitions"] = _parse_json(d.get("hook_definitions"), {})
    d["app_templates"] = {
        "slug": d.pop("t_slug", d.get("slug")),
        "name": d.pop("t_name", d.get("name")),
        "icon_url": d.pop("t_icon_url", ""),
        "latest_version": d.pop("t_latest_version", ""),
        "allow_custom_env": bool(d.pop("t_allow_custom_env", 0)),
        "allow_custom_storage": bool(d.pop("t_allow_custom_storage", 0)),
        "config_schema": d.get("config_schema", []),
        "provides": d.get("provides", []),
        "hook_definitions": d.get("hook_definitions", {}),
    }
    return d


class ActionConfig(BaseModel):
    action_id: str
    variant_id: str
    fields: dict = {}


class StageRequest(BaseModel):
    template_slug: str
    name: str
    config: dict
    version: str | None = None
    actions: list[ActionConfig] = []


class UpdateStagedRequest(BaseModel):
    config: dict
    actions: list[ActionConfig] = []


class InstallQueueRequest(BaseModel):
    force: bool = False


@router.post("/stage")
async def stage_app(req: StageRequest):
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM app_templates WHERE slug = ?", (req.template_slug,)
        ) as cur:
            tmpl_row = await cur.fetchone()

        if not tmpl_row:
            raise HTTPException(status_code=404, detail="Template not found")
        tmpl = dict(tmpl_row)

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
                    detail=f"Template version {target_version!r} not found",
                )
            version_id = ver_row["id"]

        app_id = secrets.token_hex(16)
        await db.execute("""
            INSERT INTO installed_apps
                (id, template_id, template_version_id, slug, name, config, state)
            VALUES (?, ?, ?, ?, ?, ?, 'staged')
        """, (app_id, tmpl["id"], version_id, req.template_slug, req.name, json.dumps(req.config)))

        for action in req.actions:
            await db.execute("""
                INSERT INTO app_actions (id, app_id, action_id, variant_id, fields)
                VALUES (?, ?, ?, ?, ?)
            """, (secrets.token_hex(16), app_id, action.action_id, action.variant_id,
                  json.dumps(action.fields)))

        await db.commit()

    return {"id": app_id, "slug": req.template_slug, "name": req.name, "state": "staged"}


@router.get("")
async def list_queue():
    async with get_db() as db:
        async with db.execute("""
            SELECT a.*,
                   t.slug AS t_slug, t.name AS t_name, t.icon_url AS t_icon_url,
                   t.latest_version AS t_latest_version,
                   t.allow_custom_env AS t_allow_custom_env,
                   t.allow_custom_storage AS t_allow_custom_storage,
                   v.config_schema, v.hook_definitions, v.provides,
                   v.consumes
            FROM installed_apps a
            JOIN app_templates t ON t.id = a.template_id
            LEFT JOIN template_versions v ON v.id = a.template_version_id
            WHERE a.state = 'staged'
            ORDER BY a.created_at
        """) as cur:
            rows = await cur.fetchall()

    apps = [_staged_row(r) for r in rows]

    # Resolve install order
    installed_slugs = await _get_installed_slugs()
    if apps:
        ordered_ids, _ = resolve_install_order(
            [{"id": a["id"], "slug": a["slug"], "provides": a.get("provides", []),
              "consumes": _parse_json(dict(rows[i]).get("consumes"), [])}
             for i, a in enumerate(apps)],
            installed_slugs,
        )
        id_to_order = {app_id: idx for idx, app_id in enumerate(ordered_ids)}
        apps.sort(key=lambda a: id_to_order.get(a["id"], 9999))

    # Attach actions for each app
    for app in apps:
        app["actions"] = await _load_app_actions(app["id"])

    return apps


@router.put("/{app_id}")
async def update_staged(app_id: str, req: UpdateStagedRequest):
    async with get_db() as db:
        async with db.execute(
            "SELECT id, state FROM installed_apps WHERE id = ?", (app_id,)
        ) as cur:
            row = await cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="App not found")
        if dict(row)["state"] != "staged":
            raise HTTPException(status_code=409, detail="App is not staged")

        await db.execute(
            "UPDATE installed_apps SET config = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = ?",
            (json.dumps(req.config), app_id),
        )
        await db.execute("DELETE FROM app_actions WHERE app_id = ?", (app_id,))
        for action in req.actions:
            await db.execute("""
                INSERT INTO app_actions (id, app_id, action_id, variant_id, fields)
                VALUES (?, ?, ?, ?, ?)
            """, (secrets.token_hex(16), app_id, action.action_id, action.variant_id,
                  json.dumps(action.fields)))
        await db.commit()

    return {"ok": True}


@router.delete("/{app_id}")
async def remove_staged(app_id: str):
    async with get_db() as db:
        async with db.execute(
            "SELECT id, state FROM installed_apps WHERE id = ?", (app_id,)
        ) as cur:
            row = await cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="App not found")
        if dict(row)["state"] != "staged":
            raise HTTPException(status_code=409, detail="App is not staged")

        await db.execute("DELETE FROM installed_apps WHERE id = ?", (app_id,))
        await db.commit()

    return {"ok": True}


@router.post("/validate")
async def validate_queue_endpoint():
    result = await validate_queue()
    return result.to_dict()


@router.post("/install")
async def install_queue(req: InstallQueueRequest = InstallQueueRequest()):
    from app.services.job_runner import enqueue_bulk_install

    result = await validate_queue()

    if not result.valid and not req.force:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Queue has validation errors. Resolve them or pass force=true to proceed past warnings only.",
                "validation": result.to_dict(),
            },
        )

    if not result.install_order:
        raise HTTPException(status_code=400, detail="No apps staged for installation")

    job = await enqueue_bulk_install(result.install_order)
    return {"job": job, "install_order": result.install_order}


# --- Template update endpoints ---

@router.get("/app-update/{app_id}/preview")
async def preview_template_update(app_id: str):
    async with get_db() as db:
        async with db.execute("""
            SELECT a.id, a.slug, a.name,
                   v.version AS installed_version,
                   t.latest_version,
                   v.config_schema AS current_config_schema,
                   nv.config_schema AS new_config_schema,
                   nv.id AS new_version_id
            FROM installed_apps a
            JOIN app_templates t ON t.id = a.template_id
            LEFT JOIN template_versions v ON v.id = a.template_version_id
            LEFT JOIN template_versions nv ON nv.template_id = t.id AND nv.version = t.latest_version
            WHERE a.id = ?
        """, (app_id,)) as cur:
            row = await cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="App not found")
    d = dict(row)

    if d["installed_version"] == d["latest_version"]:
        return {"up_to_date": True, "from_version": d["installed_version"], "to_version": d["latest_version"]}

    current_schema = _parse_json(d.get("current_config_schema"), [])
    new_schema = _parse_json(d.get("new_config_schema"), [])

    current_ids = {f["id"] for f in current_schema if isinstance(f, dict)}
    new_ids = {f["id"] for f in new_schema if isinstance(f, dict)}

    new_required = [
        f for f in new_schema
        if isinstance(f, dict) and f.get("id") not in current_ids
        and f.get("required") and f.get("visibility") != "hidden"
    ]
    removed = [f for f in current_schema if isinstance(f, dict) and f.get("id") not in new_ids]

    return {
        "up_to_date": False,
        "from_version": d["installed_version"],
        "to_version": d["latest_version"],
        "new_required_fields": new_required,
        "removed_fields": [f.get("id") for f in removed],
        "new_version_id": d["new_version_id"],
    }


class CommitUpdateRequest(BaseModel):
    extra_config: dict = {}


@router.post("/app-update/{app_id}/commit")
async def commit_template_update(app_id: str, req: CommitUpdateRequest = CommitUpdateRequest()):
    from app.services.job_runner import enqueue_job

    async with get_db() as db:
        async with db.execute("""
            SELECT a.id, a.config,
                   t.latest_version,
                   nv.id AS new_version_id
            FROM installed_apps a
            JOIN app_templates t ON t.id = a.template_id
            LEFT JOIN template_versions nv ON nv.template_id = t.id AND nv.version = t.latest_version
            WHERE a.id = ?
        """, (app_id,)) as cur:
            row = await cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="App not found")
    d = dict(row)
    if not d.get("new_version_id"):
        raise HTTPException(status_code=400, detail="No newer template version found")

    current_config = _parse_json(d.get("config"), {})
    merged_config = {**current_config, **req.extra_config}

    async with get_db() as db:
        await db.execute(
            "UPDATE installed_apps SET template_version_id = ?, config = ? WHERE id = ?",
            (d["new_version_id"], json.dumps(merged_config), app_id),
        )
        await db.commit()

    job = await enqueue_job(app_id, "update")
    return {"job": job}


async def _get_installed_slugs() -> set[str]:
    async with get_db() as db:
        async with db.execute(
            "SELECT slug FROM installed_apps WHERE state IN ('running', 'stopped')"
        ) as cur:
            rows = await cur.fetchall()
    return {r["slug"] for r in rows}


async def _load_app_actions(app_id: str) -> list[dict]:
    async with get_db() as db:
        async with db.execute(
            "SELECT id, action_id, variant_id, fields FROM app_actions WHERE app_id = ? ORDER BY created_at",
            (app_id,),
        ) as cur:
            rows = await cur.fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["fields"] = _parse_json(d.get("fields"), {})
        d["app_id"] = app_id
        result.append(d)
    return result
