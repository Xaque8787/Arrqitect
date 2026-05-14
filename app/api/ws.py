import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.db.client import get_client
from app.services.job_runner import subscribe, unsubscribe

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/jobs/{job_id}")
async def job_log_ws(websocket: WebSocket, job_id: str):
    await websocket.accept()

    db = get_client()
    job = db.table("jobs").select("*, job_steps(*)").eq("id", job_id).maybeSingle().execute().data
    if not job:
        await websocket.close(code=4004, reason="Job not found")
        return

    # Send existing steps as catch-up
    for step in sorted(job.get("job_steps", []), key=lambda s: s.get("started_at") or ""):
        await websocket.send_text(json.dumps({
            "type": "step",
            "step": step["step"],
            "status": step["status"],
            "log": step["log"],
        }))

    if job["status"] in ("success", "failed", "cancelled"):
        await websocket.send_text(json.dumps({"type": "job_status", "status": job["status"]}))
        await websocket.close()
        return

    queue: asyncio.Queue = asyncio.Queue()

    async def on_message(msg: str):
        await queue.put(msg)

    subscribe(job_id, on_message)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=30)
                await websocket.send_text(msg)
                data = json.loads(msg)
                if data.get("type") == "job_status" and data.get("status") in ("success", "failed", "cancelled"):
                    break
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe(job_id, on_message)
        try:
            await websocket.close()
        except Exception:
            pass
