from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.db.client import get_client
from app.services.job_runner import enqueue_job
from app.services.ecb import preview_app

router = APIRouter(prefix="/api/apps", tags=["apps"])


class InstallRequest(BaseModel):
    template_slug: str
    name: str
    config: dict


class UpdateConfigRequest(BaseModel):
    config: dict


@router.get("")
async def list_installed():
    db = get_client()
    res = db.table("installed_apps").select("*, app_templates(slug, name, icon_url)").order("name").execute()
    return res.data


@router.get("/{app_id}")
async def get_installed(app_id: str):
    db = get_client()
    res = db.table("installed_apps").select("*, app_templates(*)").eq("id", app_id).maybeSingle().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="App not found")
    return res.data


@router.post("")
async def install_app(req: InstallRequest):
    db = get_client()
    tmpl = db.table("app_templates").select("*").eq("slug", req.template_slug).maybeSingle().execute()
    if not tmpl.data:
        raise HTTPException(status_code=404, detail="Template not found")

    app_row = db.table("installed_apps").insert({
        "template_id": tmpl.data["id"],
        "slug": req.template_slug,
        "name": req.name,
        "config": req.config,
        "state": "installing",
    }).execute()

    installed = app_row.data[0]
    job = await enqueue_job(installed["id"], "install")
    return {"app": installed, "job": job}


@router.put("/{app_id}/config")
async def update_config(app_id: str, req: UpdateConfigRequest):
    db = get_client()
    existing = db.table("installed_apps").select("id").eq("id", app_id).maybeSingle().execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="App not found")

    db.table("installed_apps").update({"config": req.config, "updated_at": "now()"}).eq("id", app_id).execute()
    job = await enqueue_job(app_id, "update")
    return {"job": job}


@router.delete("/{app_id}")
async def remove_app(app_id: str):
    db = get_client()
    existing = db.table("installed_apps").select("id").eq("id", app_id).maybeSingle().execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="App not found")

    db.table("installed_apps").update({"state": "removing"}).eq("id", app_id).execute()
    job = await enqueue_job(app_id, "remove")
    return {"job": job}


@router.post("/{app_id}/preview")
async def preview(app_id: str):
    db = get_client()
    app = db.table("installed_apps").select("*, app_templates(*)").eq("id", app_id).maybeSingle().execute()
    if not app.data:
        raise HTTPException(status_code=404, detail="App not found")
    return await preview_app(app.data)
