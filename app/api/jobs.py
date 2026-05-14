from fastapi import APIRouter, HTTPException
from app.db.client import get_client

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
async def list_jobs(app_id: str | None = None):
    db = get_client()
    q = db.table("jobs").select("*, job_steps(*)").order("created_at", desc=True)
    if app_id:
        q = q.eq("installed_app_id", app_id)
    res = q.limit(50).execute()
    return res.data


@router.get("/{job_id}")
async def get_job(job_id: str):
    db = get_client()
    res = db.table("jobs").select("*, job_steps(*)").eq("id", job_id).maybeSingle().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Job not found")
    return res.data
