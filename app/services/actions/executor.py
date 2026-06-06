"""
Action executor: executes configured app_actions for an installed app.

Each action is a template-defined HTTP call with:
  - Idempotency check: GET the list endpoint and skip if already present
  - Field substitution: <<field.xxx>> from user-provided fields
  - Registry substitution: <<registry.xxx>> from app_registry (same as hooks)

Steps appear in the job log as "action:{action_id}:{variant_id}".
"""

from __future__ import annotations

import json
from typing import Callable, Awaitable

import httpx

from app.db.client import get_db
from app.models.enums import StepStatus
from app.services.hooks.helpers import render_template, record_step
from app.services.actions.loader import load_actions_yaml, find_action, find_variant


async def _build_exec_context(app_id: str) -> dict:
    """Build registry context for template substitution, same shape as hook executor."""
    exec_context: dict = {"registry": {}, "field": {}}

    async with get_db() as db:
        async with db.execute("""
            SELECT key, value FROM app_registry r
            JOIN installed_apps p ON p.id = r.provider_id
            WHERE r.provider_id = ?
        """, (app_id,)) as cur:
            rows = await cur.fetchall()

    for row in rows:
        key = row[0]
        value = row[1]
        # Store full key and also the leaf part for convenience
        parts = key.split(".", 1)
        if len(parts) == 2:
            exec_context["registry"][parts[1]] = value
        exec_context["registry"][key] = value
        # Also store with dots replaced by underscores so templates can use
        # <<registry.prowlarr_url_external>> to reference prowlarr.url_external
        exec_context["registry"][key.replace(".", "_")] = value

    # Also load consumed registry values (prowlarr.api_key etc.)
    async with get_db() as db:
        async with db.execute("""
            SELECT a.template_version_id FROM installed_apps a WHERE a.id = ?
        """, (app_id,)) as cur:
            row = await cur.fetchone()

    if row and row[0]:
        async with get_db() as db:
            async with db.execute("""
                SELECT consumes FROM template_versions WHERE id = ?
            """, (row[0],)) as cur:
                ver_row = await cur.fetchone()

        if ver_row and ver_row[0]:
            try:
                consumes = json.loads(ver_row[0]) if isinstance(ver_row[0], str) else ver_row[0]
            except Exception:
                consumes = []

            consume_keys = [
                c.get("key") if isinstance(c, dict) else str(c)
                for c in (consumes or [])
            ]
            if consume_keys:
                async with get_db() as db:
                    async with db.execute("""
                        SELECT r.key, r.value FROM app_registry r
                        JOIN installed_apps p ON p.id = r.provider_id
                        WHERE r.key IN ({})
                    """.format(",".join("?" * len(consume_keys))), consume_keys) as cur:
                        rows = await cur.fetchall()

                for row in rows:
                    key = row[0]
                    value = row[1]
                    parts = key.split(".", 1)
                    if len(parts) == 2:
                        exec_context["registry"][parts[1]] = value
                    exec_context["registry"][key] = value
                    exec_context["registry"][key.replace(".", "_")] = value

    return exec_context


async def _idempotency_check(
    action_def: dict,
    variant_def: dict,
    exec_context: dict,
    timeout: int,
) -> bool:
    """
    Returns True if the action should be skipped (already exists).
    Returns False if the action should proceed.
    """
    check = action_def.get("idempotency_check")
    if not check:
        return False

    url_template = check.get("url_template", "")
    headers_def = check.get("headers", {})
    match_field = check.get("match_field", "")
    idempotency_value = variant_def.get("idempotency_value", "")

    if not url_template or not match_field or not idempotency_value:
        return False

    url = render_template(url_template, exec_context)
    headers = {k: render_template(str(v), exec_context) for k, v in headers_def.items()}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
        if not resp.is_success:
            return False
        items = resp.json()
        if not isinstance(items, list):
            return False
        for item in items:
            if isinstance(item, dict) and str(item.get(match_field, "")) == idempotency_value:
                return True
    except Exception:
        pass

    return False


async def run_action(
    app_id: str,
    action_record: dict,
    action_def: dict,
    variant_def: dict,
    job_id: str,
    broadcast: Callable[[str, str], Awaitable[None]] | None,
) -> bool:
    """
    Execute one configured action. Returns True if degraded (non-fatal failure).
    Records a job_step for visibility in the job log.
    """
    step_name = f"action:{action_def['id']}:{variant_def['id']}"
    timeout = 30

    exec_context = await _build_exec_context(app_id)

    # Merge user field values into context
    try:
        fields = json.loads(action_record.get("fields", "{}"))
    except Exception:
        fields = {}
    exec_context["field"] = {str(k): str(v) for k, v in fields.items()}

    # Idempotency check
    try:
        already_exists = await _idempotency_check(action_def, variant_def, exec_context, timeout)
    except Exception:
        already_exists = False

    if already_exists:
        await record_step(job_id, step_name, StepStatus.SKIPPED,
                          f"Skipped: {variant_def.get('label', variant_def['id'])} already registered",
                          broadcast)
        return False

    # Render and fire
    url_template = action_def.get("url_template", "")
    method = action_def.get("method", "POST").upper()
    headers_def = action_def.get("headers", {})
    body_template = variant_def.get("body_template", "")

    url = render_template(url_template, exec_context)
    headers = {k: render_template(str(v), exec_context) for k, v in headers_def.items()}
    body = render_template(body_template, exec_context) if body_template else None

    if not url:
        await record_step(job_id, step_name, StepStatus.CONTINUE_SUCCESS,
                          "action: url_template resolved to empty string", broadcast)
        return True

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(
                method, url,
                content=body.encode() if body else None,
                headers=headers,
            )

        if resp.is_success:
            await record_step(job_id, step_name, StepStatus.SUCCESS,
                              f"action: {method} {url} -> {resp.status_code}", broadcast)
            return False

        await record_step(job_id, step_name, StepStatus.CONTINUE_SUCCESS,
                          f"action: {method} {url} -> {resp.status_code}: {resp.text[:200]}",
                          broadcast)
        return True

    except Exception as exc:
        await record_step(job_id, step_name, StepStatus.CONTINUE_SUCCESS,
                          f"action: request failed (non-fatal): {exc}", broadcast)
        return True


async def run_app_actions(
    app_id: str,
    job_id: str,
    broadcast: Callable[[str, str], Awaitable[None]] | None,
) -> bool:
    """
    Run all configured app_actions for the given installed app.
    Called as the post_actions phase from job_runner after post_install completes.
    Returns True if any action produced a degraded result.
    """
    async with get_db() as db:
        async with db.execute(
            "SELECT id, action_id, variant_id, fields FROM app_actions WHERE app_id = ? ORDER BY created_at",
            (app_id,)
        ) as cur:
            action_rows = await cur.fetchall()

    if not action_rows:
        return False

    actions_yaml = await load_actions_yaml(app_id)
    if not actions_yaml:
        return False

    has_degraded = False
    for row in action_rows:
        record = dict(row)
        action_def = find_action(actions_yaml, record["action_id"])
        if not action_def:
            continue
        variant_def = find_variant(action_def, record["variant_id"])
        if not variant_def:
            continue

        degraded = await run_action(app_id, record, action_def, variant_def, job_id, broadcast)
        has_degraded = has_degraded or degraded

    return has_degraded
