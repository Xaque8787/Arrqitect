"""
Reconciler — Phase 1.

Responsibilities:
  1. After a capability write completes, fire events for consumers.
  2. When a pending event exists for a consumer, enqueue a reconcile job.
  3. The reconcile job runs the consumer's hooks with a HookContext that
     carries is_reconcile=True, preventing further event cascades.
  4. After hooks complete, update reconcile_state with last_seen_versions.

Four-step commit order (per blueprint):
  hook success → reconcile_state update → runtime_deps update → events processed

This module provides the reconcile job runner that job_runner.py calls.
The capability write trigger is called directly from job_runner after
registry_write operations complete.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Awaitable

from app.db.client import get_db
from app.models.enums import JobStatus, StepStatus
from app.services.hooks.events import (
    claim_event,
    mark_event_processed,
    mark_event_failed,
    get_pending_events,
    fire_capability_event,
)
from app.services.hooks.executor import HookContext, execute_hook


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def trigger_reconcile_for_consumers(
    provider_app_id: str,
    event_type: str,
    payload: dict,
    is_reconcile: bool = False,
) -> None:
    """
    Called after a capability write (or provider removal) completes.
    Fires events then immediately dispatches reconcile jobs for pending consumers.
    The job enqueueing is fire-and-forget (no await on the job itself).
    """
    await fire_capability_event(
        provider_app_id=provider_app_id,
        event_type=event_type,
        payload=payload,
        is_reconcile=is_reconcile,
    )

    if is_reconcile:
        return

    # Immediately dispatch reconcile jobs for all pending events
    # (fire_capability_event may have just created them)
    import asyncio
    asyncio.create_task(_dispatch_pending_reconciles())


async def _dispatch_pending_reconciles() -> None:
    """
    Enqueue reconcile jobs for all pending events.
    Called as a background task immediately after events are fired.
    """
    # Import here to avoid circular imports with job_runner
    from app.services.hooks.reconciler_runner import enqueue_reconcile_job

    pending = await get_pending_events()
    for event in pending:
        consumer_id = event["installed_app_id"]
        event_id = event["id"]
        event_type = event["event_type"]
        try:
            payload = json.loads(event["payload"]) if isinstance(event["payload"], str) else event["payload"]
        except Exception:
            payload = {}

        await enqueue_reconcile_job(consumer_id, event_id, event_type, payload)


async def run_reconcile_job(
    job_id: str,
    consumer_app_id: str,
    event_id: str,
    event_type: str,
    event_payload: dict,
    broadcast: Callable[[str, str], Awaitable[None]] | None = None,
) -> JobStatus:
    """
    Execute a reconcile job for a consumer app.

    Returns the final JobStatus for the job.
    Follows four-step commit order:
      1. hooks execute
      2. reconcile_state updated
      3. runtime_deps updated
      4. event marked processed
    """
    # Claim the event
    claimed = await claim_event(event_id, job_id)
    if not claimed:
        # Event was already processed — this is a no-op reconcile
        return JobStatus.SUCCESS

    async with get_db() as db:
        async with db.execute("""
            SELECT a.id, a.slug, v.hook_definitions, v.consumes, a.template_version_id
            FROM installed_apps a
            LEFT JOIN template_versions v ON v.id = a.template_version_id
            WHERE a.id = ?
        """, (consumer_app_id,)) as cur:
            app_row = await cur.fetchone()

    if not app_row:
        await mark_event_failed(event_id)
        return JobStatus.FAILED

    app_id = app_row[0]
    app_slug = app_row[1]
    hook_defs_raw = app_row[2] or "{}"
    try:
        hook_defs = json.loads(hook_defs_raw) if isinstance(hook_defs_raw, str) else hook_defs_raw
    except Exception:
        hook_defs = {}

    # Determine provider_slug from payload or event
    provider_slug = event_payload.get("provider_slug", "")

    # Build HookContext for the reconcile run
    hook_path = _resolve_hook_path(app_slug, hook_defs, "post_install")
    if not hook_path:
        # No post_install hook to reconcile with — mark processed and succeed
        await _update_reconcile_state(consumer_app_id, {})
        await mark_event_processed(event_id)
        return JobStatus.SUCCESS

    ctx = HookContext(
        app_id=app_id,
        app_slug=app_slug,
        hook_name="reconcile:post_install",
        hook_yaml_path=hook_path,
        template_slug=app_slug,
        is_reconcile=True,
        event_type=event_type,
        provider_slug=provider_slug,
        job_id=job_id,
    )

    completed_ok, has_degraded = await execute_hook(ctx, broadcast)

    # Step 1: hooks done
    # Step 2: update reconcile_state
    await _update_reconcile_state(consumer_app_id, ctx.observed_versions)

    # Step 3: update runtime_dependencies
    await _update_runtime_deps(consumer_app_id, ctx.observed_versions)

    # Step 4: mark event processed (or failed if hook failed)
    if completed_ok:
        await mark_event_processed(event_id)

        # After any capability event, recompile and redeploy the consumer so it
        # joins (or leaves) shared networks that the provider may have created/removed.
        if event_type in ("capability_published", "capability_changed"):
            from app.services.job_runner import enqueue_job
            import asyncio as _asyncio
            _asyncio.create_task(enqueue_job(consumer_app_id, "update"))

        return JobStatus.DEGRADED if has_degraded else JobStatus.SUCCESS
    else:
        await mark_event_failed(event_id)
        return JobStatus.FAILED


async def _update_reconcile_state(consumer_app_id: str, observed_versions: dict) -> None:
    versions_json = json.dumps(observed_versions)
    async with get_db() as db:
        async with db.execute(
            "SELECT id FROM reconcile_state WHERE consumer_app_id = ?", (consumer_app_id,)
        ) as cur:
            existing = await cur.fetchone()

        now = _now()
        if existing:
            await db.execute("""
                UPDATE reconcile_state
                SET last_reconciled_at = ?, last_seen_versions = ?, updated_at = ?
                WHERE consumer_app_id = ?
            """, (now, versions_json, now, consumer_app_id))
        else:
            await db.execute("""
                INSERT INTO reconcile_state
                    (id, consumer_app_id, last_reconciled_at, last_seen_versions)
                VALUES (?, ?, ?, ?)
            """, (secrets.token_hex(16), consumer_app_id, now, versions_json))
        await db.commit()


async def _update_runtime_deps(consumer_app_id: str, observed_versions: dict) -> None:
    """
    Update runtime_dependencies based on which capabilities were observed.
    Each observed capability key maps to its provider.
    """
    if not observed_versions:
        return

    async with get_db() as db:
        for cap_key in observed_versions.keys():
            # Find the provider of this capability
            async with db.execute("""
                SELECT provider_id FROM app_registry WHERE key = ? LIMIT 1
            """, (cap_key,)) as cur:
                reg_row = await cur.fetchone()

            if not reg_row:
                continue

            provider_id = reg_row[0]
            slug_prefix = cap_key.split(".")[0]

            # Upsert the runtime dependency
            async with db.execute("""
                SELECT id FROM runtime_dependencies
                WHERE consumer_id = ? AND provider_id = ? AND dependency_type = ?
            """, (consumer_app_id, provider_id, slug_prefix)) as cur:
                dep_existing = await cur.fetchone()

            if not dep_existing:
                await db.execute("""
                    INSERT OR IGNORE INTO runtime_dependencies
                        (id, consumer_id, provider_id, dependency_type)
                    VALUES (?, ?, ?, ?)
                """, (secrets.token_hex(16), consumer_app_id, provider_id, slug_prefix))

        await db.commit()


def _resolve_hook_path(app_slug: str, hook_defs: dict, hook_name: str) -> str | None:
    """
    Resolve the filesystem path to a hook YAML file.
    hook_defs maps hook_name -> relative path (e.g. "hooks/post_install.yaml").
    """
    relative = hook_defs.get(hook_name)
    if not relative:
        return None

    # Templates are at project_root/templates/<slug>/
    templates_base = Path(__file__).parent.parent.parent.parent / "templates" / app_slug
    full_path = templates_base / relative
    return str(full_path)
