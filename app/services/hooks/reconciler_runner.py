"""
Reconcile job enqueue and runner.

Separated from reconciler.py to break the import cycle:
  job_runner → reconciler → reconciler_runner → job_runner (would be circular)

This module is the bridge between the event system and the job infrastructure.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime, timezone

from app.db.client import get_db
from app.models.enums import JobStatus


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def enqueue_reconcile_job(
    consumer_app_id: str,
    event_id: str,
    event_type: str,
    event_payload: dict,
) -> str | None:
    """
    Enqueue a reconcile job for a consumer app.
    Returns the job_id if enqueued, None if deduplicated.

    Deduplication: at most one active reconcile job per app at a time.
    If one is already running, the event stays pending and will be
    picked up by the recovery sweep or the next trigger.
    """
    async with get_db() as db:
        # Check for existing active reconcile job
        async with db.execute("""
            SELECT id FROM jobs
            WHERE installed_app_id = ?
              AND type = 'reconcile'
              AND status IN ('pending', 'running')
            LIMIT 1
        """, (consumer_app_id,)) as cur:
            existing = await cur.fetchone()

        if existing:
            return None  # already queued — event will be picked up when it completes

        # Check app still exists and is in a reconcilable state
        async with db.execute("""
            SELECT state FROM installed_apps WHERE id = ?
        """, (consumer_app_id,)) as cur:
            app_row = await cur.fetchone()

        if not app_row or app_row[0] in ("removing",):
            return None

        job_id = secrets.token_hex(16)
        await db.execute("""
            INSERT INTO jobs
                (id, installed_app_id, type, status, dry_run, is_reconcile)
            VALUES (?, ?, 'reconcile', 'pending', 0, 1)
        """, (job_id, consumer_app_id))
        await db.commit()

    # Fire and forget — run in background
    asyncio.create_task(
        _run_reconcile_job_task(job_id, consumer_app_id, event_id, event_type, event_payload)
    )
    return job_id


async def _run_reconcile_job_task(
    job_id: str,
    consumer_app_id: str,
    event_id: str,
    event_type: str,
    event_payload: dict,
) -> None:
    """Background task that executes the reconcile job."""
    from app.services.hooks.reconciler import run_reconcile_job
    from app.services import job_runner as jr

    await jr._set_job_status(job_id, "running")
    try:
        final_status = await run_reconcile_job(
            job_id=job_id,
            consumer_app_id=consumer_app_id,
            event_id=event_id,
            event_type=event_type,
            event_payload=event_payload,
            broadcast=jr._broadcast,
        )
        await jr._set_job_status(job_id, final_status.value)
    except Exception as exc:
        await jr._add_step(job_id, "reconcile_error", "failed", str(exc), finished_at=_now())
        await jr._set_job_status(job_id, "failed")
