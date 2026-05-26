"""
App event model — Phase 1.

State machine: pending → claimed → processed | failed_permanent

Events are fired when a capability changes. Consumers (apps that declared
consumes entries) receive an event and a reconcile job is queued for them.

Recovery sweep:
  On startup and periodically, any event stuck in 'claimed' state
  (the job that claimed it is no longer active) is reset to 'pending'
  so it can be re-processed.

Loop prevention:
  The is_reconcile flag on jobs prevents reconcile-triggered writes from
  firing further events. When a reconcile job executes a registry_write,
  no new event is emitted for the writer's own consumers.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime, timezone

from app.db.client import get_db


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def fire_capability_event(
    provider_app_id: str,
    event_type: str,  # 'capability_changed' | 'capability_published' | 'provider_removed'
    payload: dict,
    is_reconcile: bool = False,
) -> None:
    """
    Fire a capability event for all consumers of the provider.

    If is_reconcile=True, no events are emitted (loop prevention).
    The reconcile flag silences events but does NOT suppress version/job_step writes.
    """
    if is_reconcile:
        return

    async with get_db() as db:
        # Find all apps that consume any capability from this provider
        async with db.execute("""
            SELECT DISTINCT a.id, a.slug
            FROM installed_apps a
            JOIN template_versions v ON v.id = a.template_version_id
            WHERE a.id != ?
              AND a.state IN ('running', 'stopped')
              AND v.consumes != '[]'
        """, (provider_app_id,)) as cur:
            potential_consumers = await cur.fetchall()

        # For each potential consumer, check if they actually consume
        # a capability from this provider
        async with db.execute("""
            SELECT key FROM app_registry WHERE provider_id = ?
        """, (provider_app_id,)) as cur:
            provider_keys = {row[0] for row in await cur.fetchall()}

        if not provider_keys:
            return

        payload_json = json.dumps(payload)

        for consumer_row in potential_consumers:
            consumer_id = consumer_row[0]

            # Check if this consumer has declared consumes for any of the provider's keys
            async with db.execute("""
                SELECT v.consumes
                FROM installed_apps a
                JOIN template_versions v ON v.id = a.template_version_id
                WHERE a.id = ?
            """, (consumer_id,)) as cur:
                ver_row = await cur.fetchone()

            if not ver_row:
                continue

            consumes_raw = ver_row[0]
            try:
                consumes = json.loads(consumes_raw) if isinstance(consumes_raw, str) else consumes_raw
            except Exception:
                continue

            consumed_keys = set()
            for c in consumes:
                if isinstance(c, dict):
                    consumed_keys.add(c.get("key", ""))
                elif isinstance(c, str):
                    consumed_keys.add(c)

            if not consumed_keys.intersection(provider_keys):
                continue

            # Check for existing pending event of same type for this consumer
            # to avoid duplicate events
            async with db.execute("""
                SELECT id FROM app_events
                WHERE installed_app_id = ?
                  AND event_type = ?
                  AND status IN ('pending', 'claimed')
                LIMIT 1
            """, (consumer_id, event_type)) as cur:
                existing = await cur.fetchone()

            if existing:
                # Update payload on existing pending event (fresher data)
                await db.execute("""
                    UPDATE app_events SET payload = ? WHERE id = ?
                """, (payload_json, existing[0]))
            else:
                event_id = secrets.token_hex(16)
                await db.execute("""
                    INSERT INTO app_events
                        (id, installed_app_id, event_type, payload, status)
                    VALUES (?, ?, ?, ?, 'pending')
                """, (event_id, consumer_id, event_type, payload_json))

        await db.commit()


async def claim_event(event_id: str, job_id: str) -> bool:
    """
    Attempt to claim an event for processing by a job.
    Returns True if successfully claimed, False if already claimed/processed.
    """
    async with get_db() as db:
        async with db.execute(
            "SELECT status FROM app_events WHERE id = ?", (event_id,)
        ) as cur:
            row = await cur.fetchone()

        if not row or row[0] != "pending":
            return False

        await db.execute("""
            UPDATE app_events
            SET status = 'claimed', claimed_by_job_id = ?, claimed_at = ?
            WHERE id = ? AND status = 'pending'
        """, (job_id, _now(), event_id))
        await db.commit()

        # Verify we actually claimed it (race condition guard)
        async with db.execute(
            "SELECT claimed_by_job_id FROM app_events WHERE id = ?", (event_id,)
        ) as cur:
            check = await cur.fetchone()

    return check is not None and check[0] == job_id


async def mark_event_processed(event_id: str) -> None:
    async with get_db() as db:
        await db.execute("""
            UPDATE app_events
            SET status = 'processed', processed_at = ?
            WHERE id = ?
        """, (_now(), event_id))
        await db.commit()


async def mark_event_failed(event_id: str) -> None:
    async with get_db() as db:
        await db.execute("""
            UPDATE app_events
            SET status = 'failed_permanent', processed_at = ?
            WHERE id = ?
        """, (_now(), event_id))
        await db.commit()


async def get_pending_events() -> list[dict]:
    """Return all pending events ordered by created_at."""
    async with get_db() as db:
        async with db.execute("""
            SELECT id, installed_app_id, event_type, payload, created_at
            FROM app_events
            WHERE status = 'pending'
            ORDER BY created_at
        """) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def recovery_sweep() -> int:
    """
    Reset 'claimed' events whose claiming job is no longer active.
    Returns the number of events recovered.

    This handles the case where a job crashed mid-execution without
    marking its claimed events as processed.
    """
    async with get_db() as db:
        async with db.execute("""
            SELECT e.id
            FROM app_events e
            LEFT JOIN jobs j ON j.id = e.claimed_by_job_id
            WHERE e.status = 'claimed'
              AND (j.id IS NULL OR j.status NOT IN ('pending', 'running'))
        """) as cur:
            stale = await cur.fetchall()

        count = 0
        for row in stale:
            await db.execute("""
                UPDATE app_events
                SET status = 'pending', claimed_by_job_id = NULL, claimed_at = NULL
                WHERE id = ?
            """, (row[0],))
            count += 1

        if count:
            await db.commit()

    return count
