import json
from fastapi import APIRouter, HTTPException
from app.db.client import get_db

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _job_row(row) -> dict:
    d = dict(row)
    d["dry_run"] = bool(d.get("dry_run", 0))
    return d


@router.get("")
async def list_jobs(app_id: str | None = None):
    async with get_db() as db:
        if app_id:
            async with db.execute(
                "SELECT * FROM jobs WHERE installed_app_id = ? ORDER BY created_at DESC LIMIT 50",
                (app_id,),
            ) as cur:
                jobs = [_job_row(r) for r in await cur.fetchall()]
        else:
            async with db.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT 50"
            ) as cur:
                jobs = [_job_row(r) for r in await cur.fetchall()]

        for job in jobs:
            async with db.execute(
                "SELECT * FROM job_steps WHERE job_id = ? ORDER BY started_at",
                (job["id"],),
            ) as cur:
                job["job_steps"] = [dict(r) for r in await cur.fetchall()]

    return jobs


@router.get("/{job_id}")
async def get_job(job_id: str):
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")
        job = _job_row(row)
        async with db.execute(
            "SELECT * FROM job_steps WHERE job_id = ? ORDER BY started_at",
            (job_id,),
        ) as cur:
            job["job_steps"] = [dict(r) for r in await cur.fetchall()]
    return job
