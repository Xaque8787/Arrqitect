import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.db.client import get_db
from app.services.job_runner import enqueue_job
from app.services.ecb import preview_app

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


class InstallRequest(BaseModel):
    template_slug: str
    name: str
    config: dict


class UpdateConfigRequest(BaseModel):
    config: dict


@router.get("")
async def list_installed():
    async with get_db() as db:
        async with db.execute("""
            SELECT a.*, t.slug AS t_slug, t.name AS t_name, t.icon_url AS t_icon_url,
                   t.config_schema, t.hook_definitions, t.provides
            FROM installed_apps a
            JOIN app_templates t ON t.id = a.template_id
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
            SELECT a.*, t.slug AS t_slug, t.name AS t_name, t.icon_url AS t_icon_url,
                   t.config_schema, t.hook_definitions, t.provides,
                   t.compose_template
            FROM installed_apps a
            JOIN app_templates t ON t.id = a.template_id
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

        app_id = _new_id()
        await db.execute("""
            INSERT INTO installed_apps (id, template_id, slug, name, config, state)
            VALUES (?, ?, ?, ?, ?, 'installing')
        """, (app_id, tmpl["id"], req.template_slug, req.name, json.dumps(req.config)))
        await db.commit()

    job = await enqueue_job(app_id, "install")
    return {"app": {"id": app_id, "slug": req.template_slug, "name": req.name}, "job": job}


@router.put("/{app_id}/config")
async def update_config(app_id: str, req: UpdateConfigRequest):
    async with get_db() as db:
        async with db.execute("SELECT id FROM installed_apps WHERE id = ?", (app_id,)) as cur:
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="App not found")
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


@router.post("/{app_id}/preview")
async def preview(app_id: str):
    async with get_db() as db:
        async with db.execute("""
            SELECT a.*, t.compose_template, t.config_schema, t.hook_definitions, t.provides,
                   t.slug AS t_slug
            FROM installed_apps a
            JOIN app_templates t ON t.id = a.template_id
            WHERE a.id = ?
        """, (app_id,)) as cur:
            row = await cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="App not found")

    d = _app_row(row)
    d["app_templates"] = {
        "compose_template": d.pop("compose_template", ""),
        "config_schema": json.loads(d.pop("config_schema")) if isinstance(d.get("config_schema"), str) else d.pop("config_schema", []),
        "hook_definitions": json.loads(d.pop("hook_definitions")) if isinstance(d.get("hook_definitions"), str) else d.pop("hook_definitions", {}),
        "provides": json.loads(d.pop("provides")) if isinstance(d.get("provides"), str) else d.pop("provides", []),
    }
    return await preview_app(d)


def _new_id() -> str:
    import secrets
    return secrets.token_hex(16)
