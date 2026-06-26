"""
Shared utilities used by both the hook executor and the action executor.
Extracted to avoid circular imports and duplication.
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from typing import Callable, Awaitable

from app.db.client import get_db
from app.models.enums import StepStatus


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def render_template(template: str, context: dict) -> str:
    def replace(m: re.Match) -> str:
        path = m.group(1).strip()
        val = resolve_path(path, context)
        return str(val) if val is not None else ""
    return re.sub(r"<<([^>]+)>>", replace, template)


def resolve_path(dotpath: str, context: dict):
    parts = dotpath.split(".")
    current = context
    for part in parts:
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current


def set_nested(context: dict, dotpath: str, value: str) -> None:
    parts = dotpath.split(".")
    current = context
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


async def record_step(
    job_id: str,
    step_name: str,
    status: StepStatus,
    log: str,
    broadcast: Callable[[str, str], Awaitable[None]] | None,
) -> None:
    if not job_id:
        return
    step_id = secrets.token_hex(16)
    ts = now()
    async with get_db() as db:
        await db.execute("""
            INSERT INTO job_steps (id, job_id, step, status, log, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (step_id, job_id, step_name, status.value, log, ts, ts))
        await db.commit()
    if broadcast:
        await broadcast(job_id, json.dumps({
            "type": "step",
            "step": step_name,
            "status": status.value,
            "log": log,
        }))
