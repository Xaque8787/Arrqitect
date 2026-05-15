import json
import subprocess
from fastapi import APIRouter
from pydantic import BaseModel
from app.db.client import get_db
from app.services.template_sync import DEFAULT_REPO_URL

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
async def get_compose_base():
    """
    Derive the host-side path that maps to /compose inside the arrqitect container
    by running docker inspect on the container named 'arrqitect'.
    Returns the absolute host path so the UI can resolve relative paths live.
    """
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{json .Mounts}}", "arrqitect"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return {"host_path": None, "error": result.stderr.strip() or "docker inspect failed"}

        mounts = json.loads(result.stdout)
        compose_mount = next(
            (m for m in mounts if m.get("Destination") == "/compose"),
            None,
        )
        if compose_mount:
            return {"host_path": compose_mount.get("Source"), "error": None}

        return {"host_path": None, "error": "No /compose bind mount found on arrqitect container"}

    except FileNotFoundError:
        return {"host_path": None, "error": "docker not found — is the socket mounted?"}
    except Exception as exc:
        return {"host_path": None, "error": str(exc)}
