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
            # Resolve the app's slug so bulk job steps can be filtered by prefix
            async with db.execute(
                "SELECT slug FROM installed_apps WHERE id = ?", (app_id,)
            ) as cur:
                app_row = await cur.fetchone()
            app_slug = app_row["slug"] if app_row else None

            async with db.execute(
                "SELECT * FROM jobs WHERE installed_app_id = ? ORDER BY created_at DESC LIMIT 50",
                (app_id,),
            ) as cur:
                jobs = [_job_row(r) for r in await cur.fetchall()]

            # Include bulk_install jobs that contained this app
            if app_slug:
                async with db.execute(
                    "SELECT * FROM jobs WHERE type = 'bulk_install' ORDER BY created_at DESC LIMIT 50"
                ) as cur:
                    bulk_candidates = [_job_row(r) for r in await cur.fetchall()]

                for bulk in bulk_candidates:
                    raw_ids = bulk.get("bulk_app_ids")
                    ids = json.loads(raw_ids) if isinstance(raw_ids, str) else (raw_ids or [])
                    if app_id in ids:
                        jobs.append(bulk)

            jobs.sort(key=lambda j: j.get("created_at") or "", reverse=True)
            jobs = jobs[:50]

            for job in jobs:
                async with db.execute(
                    "SELECT * FROM job_steps WHERE job_id = ? ORDER BY started_at",
                    (job["id"],),
                ) as cur:
                    all_steps = [dict(r) for r in await cur.fetchall()]

                # For bulk jobs, surface only the steps belonging to this app
                if job["type"] == "bulk_install" and app_slug:
                    prefix = f"{app_slug}:"
                    job["job_steps"] = [s for s in all_steps if s["step"].startswith(prefix)]
                else:
                    job["job_steps"] = all_steps
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
