from fastapi import APIRouter
from pydantic import BaseModel
from app.db.client import get_db
from app.services.template_sync import DEFAULT_REPO_URL
from app.services.ecb.resolver import get_compose_base, get_media_base, CONTAINER_COMPOSE_DIR, CONTAINER_MEDIA_DIR

router = APIRouter(prefix="/api/settings", tags=["settings"])

DEFAULTS = {
    "timezone": "Etc/UTC",
    "puid": "1000",
    "pgid": "1000",
    "template_repo_url": DEFAULT_REPO_URL,
}


async def _get_all(db) -> dict:
    async with db.execute("SELECT key, value FROM global_settings") as cur:
        rows = await cur.fetchall()
    result = dict(DEFAULTS)
    for row in rows:
        result[row["key"]] = row["value"]
    return result


@router.get("")
async def get_settings():
    async with get_db() as db:
        return await _get_all(db)


class SettingsUpdate(BaseModel):
    settings: dict


@router.put("")
async def update_settings(req: SettingsUpdate):
    async with get_db() as db:
        for key, value in req.settings.items():
            await db.execute("""
                INSERT INTO global_settings (key, value, updated_at)
                VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%SZ','now'))
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
            """, (key, str(value)))
        await db.commit()
        return await _get_all(db)


@router.get("/compose-base")
async def get_compose_base_route():
    """
    Returns the host-side path mapped to /compose in the arrqitect container.
    The UI uses this to resolve relative storage paths live.
    """
    path = get_compose_base()
    if path == CONTAINER_COMPOSE_DIR:
        return {"host_path": None, "error": "No /compose bind mount found on arrqitect container"}
    return {"host_path": path, "error": None}


@router.get("/media-base")
async def get_media_base_route():
    """
    Returns the host-side path mapped to /media in the arrqitect container.
    The UI uses this to pre-populate platform_path config fields.
    """
    path = get_media_base()
    if path == CONTAINER_MEDIA_DIR:
        return {"host_path": None, "error": "No /media bind mount found on arrqitect container"}
    return {"host_path": path, "error": None}
