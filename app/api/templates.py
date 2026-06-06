import json
import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.db.client import get_db
from app.services.template_sync import sync_templates

router = APIRouter(prefix="/api/templates", tags=["templates"])


def _row(row) -> dict:
    d = dict(row)
    for field in ("config_schema", "hook_definitions", "provides"):
        if isinstance(d.get(field), str):
            d[field] = json.loads(d[field])
    return d


def _version_row(row) -> dict:
    d = dict(row)
    for field in ("config_schema", "hook_definitions", "provides", "consumes"):
        if isinstance(d.get(field), str):
            d[field] = json.loads(d[field])
    return d


@router.get("")
async def list_templates():
    async with get_db() as db:
        async with db.execute("""
            SELECT t.*,
                   COUNT(v.id) AS version_count
            FROM app_templates t
            LEFT JOIN template_versions v ON v.template_id = t.id
            GROUP BY t.id
            ORDER BY t.name
        """) as cur:
            rows = await cur.fetchall()
    return [_row(r) for r in rows]


@router.get("/{slug}")
async def get_template(slug: str):
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM app_templates WHERE slug = ?", (slug,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Template not found")
    return _row(row)


@router.get("/{slug}/versions")
async def list_template_versions(slug: str):
    async with get_db() as db:
        async with db.execute(
            "SELECT id FROM app_templates WHERE slug = ?", (slug,)
        ) as cur:
            tmpl = await cur.fetchone()
        if not tmpl:
            raise HTTPException(status_code=404, detail="Template not found")

        async with db.execute("""
            SELECT * FROM template_versions
            WHERE template_id = ?
            ORDER BY created_at DESC
        """, (tmpl["id"],)) as cur:
            rows = await cur.fetchall()

    return [_version_row(r) for r in rows]


class SyncRequest(BaseModel):
    repo_url: str | None = None


@router.post("/sync")
async def trigger_sync(req: SyncRequest = SyncRequest()):
    result = sync_templates(repo_url=req.repo_url)
    if not result.get("ok") and not result.get("results"):
        raise HTTPException(status_code=502, detail=result.get("error", "Sync failed"))
    return result


@router.get("/{slug}/actions")
async def get_template_actions(slug: str):
    async with get_db() as db:
        # Single query: look up the latest version for the slug
        async with db.execute("""
            SELECT v.actions_definitions, v.version, t.latest_version
            FROM app_templates t
            LEFT JOIN template_versions v ON v.template_id = t.id
            WHERE t.slug = ?
            ORDER BY v.created_at DESC
            LIMIT 1
        """, (slug,)) as cur:
            row = await cur.fetchone()

    if not row:
        import logging
        logging.getLogger("arrqitect").warning("actions: template %r not found in DB", slug)
        raise HTTPException(status_code=404, detail="Template not found")

    raw = row[0] or ""
    if not raw:
        import logging
        logging.getLogger("arrqitect").info(
            "actions: template %r has empty actions_definitions (version=%r, latest=%r)",
            slug, row[1], row[2]
        )
        return {"actions": []}

    try:
        parsed = yaml.safe_load(raw)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to parse actions YAML: {exc}")

    if not isinstance(parsed, dict):
        return {"actions": []}

    return parsed
