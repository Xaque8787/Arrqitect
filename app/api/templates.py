import json
from fastapi import APIRouter, HTTPException
from app.db.client import get_db

router = APIRouter(prefix="/api/templates", tags=["templates"])


def _row(row) -> dict:
    d = dict(row)
    for field in ("config_schema", "hook_definitions", "provides"):
        if isinstance(d.get(field), str):
            d[field] = json.loads(d[field])
    return d


@router.get("")
async def list_templates():
    async with get_db() as db:
        async with db.execute("SELECT * FROM app_templates ORDER BY name") as cur:
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
