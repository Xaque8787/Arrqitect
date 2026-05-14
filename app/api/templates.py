from fastapi import APIRouter, HTTPException
from app.db.client import get_client

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("")
async def list_templates():
    db = get_client()
    res = db.table("app_templates").select("*").order("name").execute()
    return res.data


@router.get("/{slug}")
async def get_template(slug: str):
    db = get_client()
    res = db.table("app_templates").select("*").eq("slug", slug).maybeSingle().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Template not found")
    return res.data
