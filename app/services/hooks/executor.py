"""
Hook executor — Phase 1.

Reads a hook definition YAML, builds a dependency DAG, evaluates step
eligibility, executes steps in topological order, and records job_steps
rows with the frozen StepStatus vocabulary.

Hook definition schema (YAML):
    description: <string>
    steps:
      - id: <string>              # unique within this hook
        type: registry_read | registry_write | http_request | compose_command | log
        when: "<namespace>.<field> (==|!=) '<literal>'"  # optional
        depends_on: [<step_id>, ...]                     # optional
        on_error: fail | continue                        # optional, default: fail
        critical: true | false                           # optional, default: false
        timeout_seconds: <int>                           # optional
        # type-specific fields follow

    registry_read:
        key: <capability_key>
        bind_as: <context_variable_name>   # makes value available as context.<bind_as>

    registry_write:
        key: <capability_key>              # MUST start with own template slug
        value_template: "<string with {context.varname} substitutions>"

    http_request:
        url_template: "<string>"
        method: GET | POST | PUT | DELETE
        body_template: "<string>"          # optional
        headers: {key: value}              # optional

    compose_command:
        command: [<string>, ...]           # passed to docker compose

    log:
        message: "<string>"                # simple log step for testing/debugging

Context available during execution:
    registry.<key_with_dots_replaced_by_dots>: <value>   # from registry_read steps
    reconcile.event_type: <string>                        # if is_reconcile
    reconcile.provider_slug: <string>                     # if is_reconcile
    app.slug: <string>
    app.id: <string>

Cross-capability incoherence contract (canonical):
    Capability reads within a hook execution are independent observations of
    live state. The platform does not guarantee coherence between multiple
    capability reads, even when those capabilities originate from the same
    provider. Reads may observe values that were never simultaneously published
    together.
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Awaitable

import httpx
import yaml

from app.db.client import get_db
from app.models.enums import StepStatus, DEPENDENCY_SATISFYING
from app.services.hooks.when_parser import parse_when, WhenParseError


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class HookContext:
    """
    Carries everything the hook executor needs to run a hook.

    observed_versions tracks the capability_version of every registry
    value read during this execution. This makes cross-capability
    incoherence visible in the audit record.
    """
    app_id: str
    app_slug: str
    hook_name: str
    hook_yaml_path: str          # absolute path to hook .yaml on disk
    template_slug: str           # slug that owns the namespace being written
    is_reconcile: bool = False
    event_type: str = ""         # set when is_reconcile=True
    provider_slug: str = ""      # set when is_reconcile=True
    job_id: str = ""
    observed_versions: dict[str, int] = field(default_factory=dict)


@dataclass
class _StepDef:
    id: str
    step_type: str
    when_expr: str | None
    depends_on: list[str]
    on_error: str          # "fail" | "continue"
    critical: bool
    timeout_seconds: int | None
    params: dict           # type-specific params


async def execute_hook(
    ctx: HookContext,
    broadcast: Callable[[str, str], Awaitable[None]] | None = None,
) -> tuple[bool, bool]:
    """
    Execute a hook definition file.

    Returns (completed_ok, has_degraded):
      completed_ok  — True if the hook ran without a blocking failure
      has_degraded  — True if any step reached CONTINUE_SUCCESS

    Raises nothing — all errors are captured as step records.
    The caller decides how to set the job status.
    """
    hook_path = Path(ctx.hook_yaml_path)
    if not hook_path.exists():
        await _record_step(ctx.job_id, ctx.hook_name, StepStatus.SKIPPED,
                           f"Hook file not found: {ctx.hook_yaml_path}", broadcast)
        return True, False

    try:
        raw = yaml.safe_load(hook_path.read_text())
    except Exception as exc:
        await _record_step(ctx.job_id, ctx.hook_name, StepStatus.FAILED,
                           f"Failed to parse hook YAML: {exc}", broadcast)
        return False, False

    if not isinstance(raw, dict):
        await _record_step(ctx.job_id, ctx.hook_name, StepStatus.FAILED,
                           "Hook YAML must be a mapping", broadcast)
        return False, False

    raw_steps = raw.get("steps", [])
    if not raw_steps:
        # Empty hook — not an error
        return True, False

    steps = _parse_step_defs(raw_steps)
    if isinstance(steps, str):
        # parse error message returned
        await _record_step(ctx.job_id, ctx.hook_name, StepStatus.FAILED,
                           f"Hook definition error: {steps}", broadcast)
        return False, False

    order, cycle = _topological_sort(steps)
    if cycle:
        await _record_step(ctx.job_id, ctx.hook_name, StepStatus.FAILED,
                           f"Hook DAG contains a cycle involving: {cycle}", broadcast)
        return False, False

    # Build initial execution context
    exec_context: dict = {
        "registry": {},
        "reconcile": {
            "event_type": ctx.event_type,
            "provider_slug": ctx.provider_slug,
        },
        "app": {
            "slug": ctx.app_slug,
            "id": ctx.app_id,
        },
    }

    step_map = {s.id: s for s in steps}
    step_results: dict[str, StepStatus] = {}
    has_degraded = False
    blocking_failure = False

    for step_id in order:
        step = step_map[step_id]

        # Eligibility check 1: all dependencies must be DEPENDENCY_SATISFYING
        eligible = True
        for dep_id in step.depends_on:
            dep_status = step_results.get(dep_id, StepStatus.SKIPPED)
            if dep_status not in DEPENDENCY_SATISFYING:
                eligible = False
                break

        if not eligible:
            step_results[step_id] = StepStatus.SKIPPED
            await _record_step(ctx.job_id, step_id, StepStatus.SKIPPED,
                               "Skipped: unsatisfied dependency", broadcast)
            continue

        # Eligibility check 2: when: condition
        if step.when_expr:
            try:
                when_parsed = parse_when(step.when_expr)
                if not when_parsed.evaluate(exec_context):
                    step_results[step_id] = StepStatus.SKIPPED
                    await _record_step(ctx.job_id, step_id, StepStatus.SKIPPED,
                                       f"Skipped: when condition false ({step.when_expr!r})",
                                       broadcast)
                    continue
            except WhenParseError as exc:
                step_results[step_id] = StepStatus.FAILED
                await _record_step(ctx.job_id, step_id, StepStatus.FAILED,
                                   f"when: parse error — {exc}", broadcast)
                blocking_failure = True
                break

        # Execute the step
        step_status, log, side_effects = await _execute_step(
            step, exec_context, ctx
        )

        # Apply side effects (registry reads bind into context)
        for k, v in side_effects.items():
            _set_nested(exec_context, k, v)

        step_results[step_id] = step_status
        await _record_step(ctx.job_id, step_id, step_status, log, broadcast)

        if step_status == StepStatus.CONTINUE_SUCCESS:
            has_degraded = True
        elif step_status == StepStatus.FAILED:
            if step.on_error == "continue":
                # Treat as CONTINUE_SUCCESS — already recorded as such above
                # (executor returns CONTINUE_SUCCESS when on_error=continue)
                # This branch is for a step that returned FAILED with on_error=fail
                blocking_failure = True
                break
            # on_error == "fail" and step failed — stop
            blocking_failure = True
            break

    return not blocking_failure, has_degraded


async def _execute_step(
    step: _StepDef,
    exec_context: dict,
    ctx: HookContext,
) -> tuple[StepStatus, str, dict]:
    """
    Execute a single step. Returns (status, log_message, side_effects).
    side_effects is a dict of context path -> value to merge into exec_context.
    Never raises — captures all errors.
    """
    try:
        timeout = step.timeout_seconds or 30
        if step.step_type == "registry_read":
            return await _step_registry_read(step, exec_context, ctx, timeout)
        elif step.step_type == "registry_write":
            return await _step_registry_write(step, exec_context, ctx, timeout)
        elif step.step_type == "http_request":
            return await _step_http_request(step, exec_context, ctx, timeout)
        elif step.step_type == "compose_command":
            return await _step_compose_command(step, exec_context, ctx, timeout)
        elif step.step_type == "log":
            return await _step_log(step, exec_context)
        else:
            return StepStatus.FAILED, f"Unknown step type: {step.step_type!r}", {}
    except asyncio.TimeoutError:
        return StepStatus.TIMEOUT, f"Step timed out after {step.timeout_seconds}s", {}
    except Exception as exc:
        if step.on_error == "continue":
            return StepStatus.CONTINUE_SUCCESS, f"Step failed (on_error: continue): {exc}", {}
        return StepStatus.FAILED, f"Step error: {exc}", {}


async def _step_registry_read(
    step: _StepDef, exec_context: dict, ctx: HookContext, timeout: int
) -> tuple[StepStatus, str, dict]:
    key = step.params.get("key", "")
    bind_as = step.params.get("bind_as", "")
    if not key:
        return StepStatus.FAILED, "registry_read: missing 'key'", {}

    async with get_db() as db:
        async with db.execute("""
            SELECT r.value, r.sensitive, r.capability_version
            FROM app_registry r
            JOIN installed_apps p ON p.id = r.provider_id
            WHERE r.key = ?
            LIMIT 1
        """, (key,)) as cur:
            row = await cur.fetchone()

    if row is None:
        if step.on_error == "continue":
            log = f"registry_read: key {key!r} not found (on_error: continue)"
            side_effects: dict = {}
            if bind_as:
                side_effects[f"registry.{bind_as}"] = ""
            return StepStatus.CONTINUE_SUCCESS, log, side_effects
        return StepStatus.FAILED, f"registry_read: key {key!r} not found", {}

    value = row[0]
    sensitive = bool(row[1])
    cap_version = row[2]

    # Track observed version for cross-capability incoherence audit
    ctx.observed_versions[key] = cap_version

    side_effects = {}
    if bind_as:
        side_effects[f"registry.{bind_as}"] = value

    display = "***" if sensitive else value
    log = f"registry_read: {key!r} = {display!r} (capability_version={cap_version})"
    return StepStatus.SUCCESS, log, side_effects


async def _step_registry_write(
    step: _StepDef, exec_context: dict, ctx: HookContext, timeout: int
) -> tuple[StepStatus, str, dict]:
    key = step.params.get("key", "")
    value_template = step.params.get("value_template", "")

    if not key:
        return StepStatus.FAILED, "registry_write: missing 'key'", {}

    # Namespace ownership enforcement
    if not key.startswith(f"{ctx.template_slug}."):
        return StepStatus.FAILED, (
            f"registry_write: key {key!r} is outside namespace {ctx.template_slug!r}. "
            f"This template exclusively owns the '{ctx.template_slug}.*' namespace."
        ), {}

    value = _render_template(value_template, exec_context)

    async with get_db() as db:
        # Check if key already exists to determine version
        async with db.execute("""
            SELECT r.id, r.capability_version
            FROM app_registry r
            JOIN installed_apps p ON p.id = r.provider_id
            WHERE r.key = ? AND p.id = ?
        """, (key, ctx.app_id)) as cur:
            existing = await cur.fetchone()

        if existing:
            new_version = existing[1] + 1
            await db.execute("""
                UPDATE app_registry
                SET value = ?, capability_version = ?, published_at = ?
                WHERE id = ?
            """, (value, new_version, _now(), existing[0]))
        else:
            # Determine type from key suffix conventions
            cap_type = _infer_capability_type(key)
            sensitive = cap_type == "credential"
            new_version = 1
            await db.execute("""
                INSERT INTO app_registry
                    (id, provider_id, key, value, type, sensitive, capability_version)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            """, (secrets.token_hex(16), ctx.app_id, key, value, cap_type, int(sensitive)))

        await db.commit()

    log = f"registry_write: {key!r} = {'***' if 'api_key' in key else value!r} (version={new_version})"
    return StepStatus.SUCCESS, log, {}


async def _step_http_request(
    step: _StepDef, exec_context: dict, ctx: HookContext, timeout: int
) -> tuple[StepStatus, str, dict]:
    url_template = step.params.get("url_template", "")
    method = step.params.get("method", "GET").upper()
    body_template = step.params.get("body_template", "")
    headers = step.params.get("headers", {})

    url = _render_template(url_template, exec_context)
    body = _render_template(body_template, exec_context) if body_template else None

    if not url:
        if step.on_error == "continue":
            return StepStatus.CONTINUE_SUCCESS, "http_request: empty URL (on_error: continue)", {}
        return StepStatus.FAILED, "http_request: missing 'url_template'", {}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(
                method, url,
                content=body.encode() if body else None,
                headers=headers,
            )
        if resp.is_success:
            return StepStatus.SUCCESS, f"http_request: {method} {url} → {resp.status_code}", {}
        if step.on_error == "continue":
            return StepStatus.CONTINUE_SUCCESS, (
                f"http_request: {method} {url} → {resp.status_code} "
                f"(on_error: continue) body: {resp.text[:200]}"
            ), {}
        return StepStatus.FAILED, (
            f"http_request: {method} {url} → {resp.status_code}: {resp.text[:200]}"
        ), {}
    except Exception as exc:
        if step.on_error == "continue":
            return StepStatus.CONTINUE_SUCCESS, f"http_request failed (on_error: continue): {exc}", {}
        return StepStatus.FAILED, f"http_request failed: {exc}", {}


async def _step_compose_command(
    step: _StepDef, exec_context: dict, ctx: HookContext, timeout: int
) -> tuple[StepStatus, str, dict]:
    """
    Run a docker compose sub-command against the app's compose file.
    The compose_path must be resolvable from the installed_apps record.
    """
    command = step.params.get("command", [])
    if not command:
        return StepStatus.FAILED, "compose_command: missing 'command'", {}

    # Fetch compose_path for this app
    async with get_db() as db:
        async with db.execute(
            "SELECT compose_path FROM installed_apps WHERE id = ?", (ctx.app_id,)
        ) as cur:
            row = await cur.fetchone()

    if not row or not row[0]:
        if step.on_error == "continue":
            return StepStatus.CONTINUE_SUCCESS, "compose_command: no compose_path found (on_error: continue)", {}
        return StepStatus.FAILED, "compose_command: no compose_path found for app", {}

    compose_path = row[0]
    cmd = ["docker", "compose", "-f", compose_path] + list(command)

    try:
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=timeout),
            ),
            timeout=timeout + 5,
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            return StepStatus.SUCCESS, f"compose_command {command}: {output}", {}
        if step.on_error == "continue":
            return StepStatus.CONTINUE_SUCCESS, (
                f"compose_command {command} failed rc={result.returncode} "
                f"(on_error: continue): {output}"
            ), {}
        return StepStatus.FAILED, f"compose_command {command} failed rc={result.returncode}: {output}", {}
    except asyncio.TimeoutError:
        return StepStatus.TIMEOUT, f"compose_command timed out after {timeout}s", {}


async def _step_log(
    step: _StepDef, exec_context: dict,
) -> tuple[StepStatus, str, dict]:
    message = step.params.get("message", "")
    return StepStatus.SUCCESS, f"log: {message}", {}


# --- parsing helpers ---

def _parse_step_defs(raw_steps: list) -> list[_StepDef] | str:
    """
    Parse raw YAML step list into _StepDef objects.
    Returns error message string on failure.
    """
    steps = []
    seen_ids: set[str] = set()
    for i, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            return f"Step {i} is not a mapping"
        step_id = raw.get("id", "")
        if not step_id:
            return f"Step {i} missing 'id'"
        if step_id in seen_ids:
            return f"Duplicate step id: {step_id!r}"
        seen_ids.add(step_id)

        step_type = raw.get("type", "")
        if not step_type:
            return f"Step {step_id!r} missing 'type'"

        depends_on = raw.get("depends_on", [])
        if isinstance(depends_on, str):
            depends_on = [depends_on]

        steps.append(_StepDef(
            id=step_id,
            step_type=step_type,
            when_expr=raw.get("when"),
            depends_on=list(depends_on),
            on_error=raw.get("on_error", "fail"),
            critical=bool(raw.get("critical", False)),
            timeout_seconds=raw.get("timeout_seconds"),
            params={k: v for k, v in raw.items()
                    if k not in ("id", "type", "when", "depends_on", "on_error", "critical", "timeout_seconds")},
        ))

    # Validate dependency references
    all_ids = {s.id for s in steps}
    for step in steps:
        for dep in step.depends_on:
            if dep not in all_ids:
                return f"Step {step.id!r} depends_on unknown step {dep!r}"

    return steps


def _topological_sort(steps: list[_StepDef]) -> tuple[list[str], str | None]:
    """
    Kahn's algorithm topological sort.
    Returns (order, cycle_description).
    cycle_description is None if no cycle detected.
    """
    graph: dict[str, set[str]] = {s.id: set(s.depends_on) for s in steps}
    in_degree: dict[str, int] = {s.id: len(s.depends_on) for s in steps}
    dependents: dict[str, list[str]] = {s.id: [] for s in steps}

    for step in steps:
        for dep in step.depends_on:
            dependents[dep].append(step.id)

    queue = [s_id for s_id, deg in in_degree.items() if deg == 0]
    order = []

    while queue:
        node = queue.pop(0)
        order.append(node)
        for dep_on_me in dependents[node]:
            in_degree[dep_on_me] -= 1
            if in_degree[dep_on_me] == 0:
                queue.append(dep_on_me)

    if len(order) != len(steps):
        remaining = [s_id for s_id in in_degree if s_id not in order]
        return order, ", ".join(remaining)

    return order, None


# --- context helpers ---

def _set_nested(context: dict, dotpath: str, value: str) -> None:
    """Set a value at a dot-separated path into a nested dict."""
    parts = dotpath.split(".")
    current = context
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def _render_template(template: str, context: dict) -> str:
    """
    Simple {namespace.field} substitution. Not Jinja.
    Unknown references are left as empty string.
    """
    def replace(m: re.Match) -> str:
        path = m.group(1).strip()
        val = _resolve_path(path, context)
        return str(val) if val is not None else ""
    return re.sub(r"\{([^}]+)\}", replace, template)


def _resolve_path(dotpath: str, context: dict) -> str | None:
    parts = dotpath.split(".")
    current = context
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def _infer_capability_type(key: str) -> str:
    if "api_key" in key or "password" in key or "secret" in key or "token" in key:
        return "credential"
    if "url" in key or "host" in key or "port" in key:
        return "endpoint"
    return "metadata"


async def _record_step(
    job_id: str,
    step_name: str,
    status: StepStatus,
    log: str,
    broadcast: Callable[[str, str], Awaitable[None]] | None,
) -> None:
    if not job_id:
        return
    step_id = secrets.token_hex(16)
    now = _now()
    async with get_db() as db:
        await db.execute("""
            INSERT INTO job_steps (id, job_id, step, status, log, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (step_id, job_id, step_name, status.value, log, now, now))
        await db.commit()
    if broadcast:
        await broadcast(job_id, json.dumps({
            "type": "step",
            "step": step_name,
            "status": status.value,
            "log": log,
        }))
