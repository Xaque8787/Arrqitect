"""
Job runner: creates job + step records, executes install/update/remove pipelines.
WebSocket broadcast handled via a simple in-memory subscriber map.

Install pipeline (schema_version 2):
  1. Load template TemplateModel from service_definitions in DB
  2. Load global settings and registry entries for this app
  3. Call ecb.compile_app() -> AppIR
  4. Store ir_hash on installed_apps
  5. Call ComposeRenderer(app_ir).render() -> (compose_yaml, env_content)
  6. Store compose_hash on installed_apps
  7. Write files to disk
  8. Run docker compose up -d
  9. Execute post_install hook (real hook executor)
 10. Publish capabilities, fire events for consumers

Install pipeline (schema_version 1 passthrough):
  Legacy Jinja2 render path. Explicitly isolated.
"""

import asyncio
import json
import secrets
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Awaitable

from app.db.client import get_db
from app.models.enums import JobStatus, StepStatus
from app.models.ir import AppIR
from app.services.ecb import compile_app
from app.services.ecb.parser import parse_template, PassthroughTemplate
from app.services.ecb.resolver import get_compose_base
from app.services.renderers.compose import ComposeRenderer
from app.services.hooks.executor import HookContext, execute_hook
from app.services.hooks.reconciler import trigger_reconcile_for_consumers

# Legacy render functions — used only for schema_version 1 passthrough apps
from app.services.ecb_legacy import (
    render_compose as _legacy_render_compose,
    build_env_file_content as _legacy_build_env,
    write_compose_files,
    write_env_only,
)

CONTAINER_COMPOSE_DIR = "/compose"

_subscribers: dict[str, list[Callable[[str], Awaitable[None]]]] = {}


def subscribe(job_id: str, callback: Callable[[str], Awaitable[None]]) -> None:
    _subscribers.setdefault(job_id, []).append(callback)


def unsubscribe(job_id: str, callback: Callable[[str], Awaitable[None]]) -> None:
    lst = _subscribers.get(job_id, [])
    try:
        lst.remove(callback)
    except ValueError:
        pass


async def _broadcast(job_id: str, message: str) -> None:
    for cb in list(_subscribers.get(job_id, [])):
        try:
            await cb(message)
        except Exception:
            pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def enqueue_job(installed_app_id: str, job_type: str, dry_run: bool = False) -> dict:
    job_id = secrets.token_hex(16)
    async with get_db() as db:
        async with db.execute("""
            SELECT id FROM jobs
            WHERE installed_app_id = ?
              AND type = ?
              AND status IN ('pending', 'running')
            LIMIT 1
        """, (installed_app_id, job_type)) as cur:
            existing = await cur.fetchone()

        if existing:
            return {"id": existing[0], "type": job_type, "status": "pending", "dry_run": dry_run, "deduplicated": True}

        await db.execute("""
            INSERT INTO jobs (id, installed_app_id, type, status, dry_run, is_reconcile)
            VALUES (?, ?, ?, 'pending', ?, 0)
        """, (job_id, installed_app_id, job_type, 1 if dry_run else 0))
        await db.commit()

    asyncio.create_task(_run_job(job_id, installed_app_id, job_type, dry_run))
    return {"id": job_id, "type": job_type, "status": "pending", "dry_run": dry_run}


async def _add_step(job_id: str, step: str, status: str, log: str,
                    finished_at: str | None = None) -> None:
    step_id = secrets.token_hex(16)
    now = _now()
    async with get_db() as db:
        await db.execute("""
            INSERT INTO job_steps (id, job_id, step, status, log, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (step_id, job_id, step, status, log, now, finished_at))
        await db.commit()
    await _broadcast(job_id, json.dumps({"type": "step", "step": step, "status": status, "log": log}))


async def _set_job_status(job_id: str, status: str) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), job_id),
        )
        await db.commit()
    await _broadcast(job_id, json.dumps({"type": "job_status", "status": status}))


async def _set_app_state(app_id: str, state: str) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE installed_apps SET state = ?, updated_at = ? WHERE id = ?",
            (state, _now(), app_id),
        )
        await db.commit()


async def _load_app(app_id: str) -> dict | None:
    async with get_db() as db:
        async with db.execute("""
            SELECT a.*,
                   v.compose             AS compose_template,
                   v.config_schema,
                   v.hook_definitions,
                   v.provides,
                   v.consumes,
                   v.service_definitions,
                   v.has_passthrough,
                   v.schema_version      AS template_schema_version
            FROM installed_apps a
            JOIN app_templates t ON t.id = a.template_id
            LEFT JOIN template_versions v ON v.id = a.template_version_id
            WHERE a.id = ?
        """, (app_id,)) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    d = dict(row)
    if isinstance(d.get("config"), str):
        d["config"] = json.loads(d["config"])
    d["hook_definitions"] = json.loads(d["hook_definitions"]) if isinstance(d.get("hook_definitions"), str) else {}
    d["config_schema"] = json.loads(d["config_schema"]) if isinstance(d.get("config_schema"), str) else []
    return d


async def _load_global_settings() -> dict:
    async with get_db() as db:
        async with db.execute("SELECT key, value FROM global_settings") as cur:
            rows = await cur.fetchall()
    s = {r[0]: r[1] for r in rows}
    return {
        "puid": s.get("puid", "1000"),
        "pgid": s.get("pgid", "1000"),
        "timezone": s.get("timezone", "Etc/UTC"),
    }


async def _load_registry_entries(app_id: str, consumes: list) -> list[dict]:
    """Load registry values for all consumed capabilities."""
    if not consumes:
        return []

    async with get_db() as db:
        async with db.execute("""
            SELECT r.key, r.value, r.type, r.sensitive
            FROM app_registry r
            JOIN installed_apps p ON p.id = r.provider_id
            WHERE r.key IN ({})
        """.format(",".join("?" * len(consumes))),
            [c.get("key") if isinstance(c, dict) else str(c) for c in consumes]
        ) as cur:
            rows = await cur.fetchall()

    return [dict(r) for r in rows]


async def _load_installed_providers() -> list[dict]:
    """Load all installed apps with their provides declarations, for network inference."""
    async with get_db() as db:
        async with db.execute("""
            SELECT a.id, a.slug, v.provides
            FROM installed_apps a
            LEFT JOIN template_versions v ON v.id = a.template_version_id
            WHERE a.state IN ('running', 'stopped')
        """) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def _find_connectivity_providers(consumer_app_id: str, consumes: list) -> list[dict]:
    """
    Return installed provider apps that this consumer has connectivity: true against.
    Used to trigger provider recompiles so they create shared networks before the consumer joins.
    """
    connectivity_keys = {
        c.get("key") for c in consumes
        if isinstance(c, dict) and c.get("connectivity")
    }
    if not connectivity_keys:
        return []

    async with get_db() as db:
        async with db.execute("""
            SELECT a.id, a.slug, v.provides
            FROM installed_apps a
            LEFT JOIN template_versions v ON v.id = a.template_version_id
            WHERE a.id != ?
              AND a.state IN ('running', 'stopped')
              AND v.provides IS NOT NULL
              AND v.provides != '[]'
        """, (consumer_app_id,)) as cur:
            rows = await cur.fetchall()

    providers = []
    for row in rows:
        d = dict(row)
        provides_raw = d.get("provides", [])
        if isinstance(provides_raw, str):
            try:
                provides_raw = json.loads(provides_raw)
            except Exception:
                provides_raw = []
        provided_keys = {p.get("key") for p in provides_raw if isinstance(p, dict)}
        if provided_keys.intersection(connectivity_keys):
            providers.append(d)
    return providers


async def _load_installed_consumers(provider_app_id: str) -> list[dict]:
    """
    Load all installed apps that consume any capability from this provider,
    for provider-side network inference.
    """
    async with get_db() as db:
        async with db.execute("""
            SELECT a.id, a.slug, v.consumes
            FROM installed_apps a
            LEFT JOIN template_versions v ON v.id = a.template_version_id
            WHERE a.id != ?
              AND a.state IN ('running', 'stopped', 'installing')
              AND v.consumes IS NOT NULL
              AND v.consumes != '[]'
        """, (provider_app_id,)) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def _run_job(job_id: str, app_id: str, job_type: str, dry_run: bool) -> None:
    await _set_job_status(job_id, JobStatus.RUNNING.value)
    has_degraded = False
    try:
        app = await _load_app(app_id)
        if not app:
            raise RuntimeError(f"App {app_id} not found")

        if job_type == "install":
            has_degraded = await _run_install(job_id, app_id, app, dry_run)
        elif job_type == "update":
            has_degraded = await _run_update(job_id, app_id, app, dry_run)
        elif job_type == "remove":
            await _run_remove(job_id, app_id, app, dry_run)
        else:
            await _add_step(job_id, job_type, StepStatus.SKIPPED.value,
                            f"Job type '{job_type}' not implemented", finished_at=_now())

        final_status = JobStatus.DEGRADED if has_degraded else JobStatus.SUCCESS
        await _set_job_status(job_id, final_status.value)

    except Exception as exc:
        await _add_step(job_id, "error", StepStatus.FAILED.value, str(exc), finished_at=_now())
        await _set_job_status(job_id, JobStatus.FAILED.value)
        await _set_app_state(app_id, "error")


def _is_passthrough(app: dict) -> bool:
    return bool(app.get("has_passthrough", 0))


def _extract_puid_pgid(app_ir: AppIR) -> tuple[str, str] | tuple[None, None]:
    for svc in app_ir.services:
        env_by_name = {e.name: e.value for e in svc.env_vars}
        puid = env_by_name.get("PUID")
        pgid = env_by_name.get("PGID")
        if puid and pgid and puid.isdigit() and pgid.isdigit():
            return puid, pgid
    return None, None


def _to_container_path(host_path: str, compose_base: str) -> str | None:
    try:
        rel = Path(host_path).relative_to(compose_base)
        return str(Path(CONTAINER_COMPOSE_DIR) / rel)
    except ValueError:
        return None


def _prepare_mount_ownership(app_ir: AppIR, puid: str, pgid: str, compose_base: str) -> list[str]:
    log_lines: list[str] = []

    for svc in app_ir.services:
        for mount in svc.storage:
            if mount.persistence != "persistent" or mount.mutability != "read-write":
                continue

            host_path = mount.host_path
            container_path = _to_container_path(host_path, compose_base)

            if container_path is None:
                log_lines.append(
                    f"skip  {host_path} (outside arrqitect compose directory — "
                    f"Docker will create it if needed)"
                )
                continue

            existed = Path(container_path).exists()

            if existed:
                log_lines.append(f"skip  {host_path} (already exists)")
                continue

            try:
                Path(container_path).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                log_lines.append(
                    f"warn  {host_path} — could not create directory ({exc.strerror}); "
                    f"ensure it exists on the host before starting the container"
                )
                continue

            subprocess.run(
                ["chown", "-R", f"{puid}:{pgid}", container_path],
                capture_output=True,
                text=True,
                timeout=30,
            )
            log_lines.append(f"mkdir+chown {puid}:{pgid} {host_path}")

    return log_lines


async def _compile_and_render(job_id: str, app_id: str, app: dict) -> tuple[str, str, str, str, AppIR]:
    service_definitions = app.get("service_definitions", "")
    if not service_definitions:
        raise RuntimeError("No service_definitions found — template may not have been synced as schema_version 2")

    from app.models.template import TemplateModel
    template_model = TemplateModel.model_validate_json(service_definitions)

    global_settings = await _load_global_settings()

    consumes_raw = app.get("consumes", [])
    if isinstance(consumes_raw, str):
        try:
            consumes_raw = json.loads(consumes_raw)
        except Exception:
            consumes_raw = []

    registry_entries = await _load_registry_entries(app_id, consumes_raw)
    installed_providers = await _load_installed_providers()

    # For provider apps, also load consumers so provider-side networks are inferred
    provides_raw = app.get("provides", [])
    if isinstance(provides_raw, str):
        try:
            import json as _json
            provides_raw = _json.loads(provides_raw)
        except Exception:
            provides_raw = []
    installed_consumers = await _load_installed_consumers(app_id) if provides_raw else None

    app_ir = compile_app(
        template=template_model,
        user_config=app.get("config", {}),
        global_settings=global_settings,
        registry_entries=registry_entries,
        installed_providers=installed_providers,
        app_slug=app["slug"],
        installed_consumers=installed_consumers,
    )

    renderer = ComposeRenderer(app_ir)
    compose_yaml, env_content = renderer.render()
    compose_hash = renderer.compose_hash()

    return compose_yaml, env_content, app_ir.ir_hash, compose_hash, app_ir


def _resolve_hook_path(app_slug: str, hook_defs: dict, hook_name: str) -> str | None:
    """Resolve the filesystem path to a hook YAML file."""
    relative = hook_defs.get(hook_name)
    if not relative:
        return None
    templates_base = Path(__file__).parent.parent.parent / "templates" / app_slug
    return str(templates_base / relative)


async def _run_hook(
    job_id: str,
    app_id: str,
    app_slug: str,
    hook_defs: dict,
    hook_name: str,
    is_reconcile: bool = False,
    event_type: str = "",
    provider_slug: str = "",
) -> bool:
    """
    Run a named hook. Returns True if any step reached CONTINUE_SUCCESS (degraded).
    Records nothing and returns False cleanly if hook file is missing.
    """
    hook_path = _resolve_hook_path(app_slug, hook_defs, hook_name)
    if not hook_path:
        return False

    ctx = HookContext(
        app_id=app_id,
        app_slug=app_slug,
        hook_name=hook_name,
        hook_yaml_path=hook_path,
        template_slug=app_slug,
        is_reconcile=is_reconcile,
        event_type=event_type,
        provider_slug=provider_slug,
        job_id=job_id,
    )

    _completed_ok, has_degraded = await execute_hook(
        ctx,
        broadcast=lambda jid, msg: _broadcast(jid, msg),
    )

    if not _completed_ok:
        raise RuntimeError(f"Hook '{hook_name}' failed for {app_slug}")

    return has_degraded


async def _prep_provider_networks(job_id: str, providers: list[dict]) -> None:
    """
    Recompile and re-up each connectivity provider so it creates and joins the
    shared Docker network before the consumer's IR is compiled. Non-fatal —
    a failure here is logged as CONTINUE_SUCCESS and does not abort the install.
    """
    for provider in providers:
        provider_id = provider["id"]
        slug = provider.get("slug", provider_id)
        try:
            provider_app = await _load_app(provider_id)
            if not provider_app or _is_passthrough(provider_app):
                continue

            compose_yaml, env_content, ir_hash, compose_hash, _ = await _compile_and_render(
                job_id, provider_id, provider_app
            )

            if compose_hash == provider_app.get("compose_hash", ""):
                continue  # compose unchanged — provider already on correct networks

            compose_path, _ = write_compose_files(provider_app["slug"], compose_yaml, env_content)
            async with get_db() as db:
                await db.execute(
                    "UPDATE installed_apps SET compose_path = ?, ir_hash = ?, compose_hash = ? WHERE id = ?",
                    (compose_path, ir_hash, compose_hash, provider_id),
                )
                await db.commit()

            result = await _docker_compose(compose_path, ["up", "-d"])
            log = (result.stdout + result.stderr).strip()
            status = StepStatus.SUCCESS.value if result.returncode == 0 else StepStatus.CONTINUE_SUCCESS.value
            await _add_step(job_id, f"prep_provider_{slug}", status,
                            log[:500] or f"Provider {slug} joined shared network",
                            finished_at=_now())
        except Exception as exc:
            await _add_step(job_id, f"prep_provider_{slug}", StepStatus.CONTINUE_SUCCESS.value,
                            f"Provider network prep failed (non-fatal): {exc}", finished_at=_now())


async def _run_install(job_id: str, app_id: str, app: dict, dry_run: bool) -> bool:
    hooks = app.get("hook_definitions", {})
    slug = app["slug"]
    has_degraded = False

    # Before compiling the consumer IR: update each connectivity provider's
    # compose so it creates the shared Docker network. The consumer's IR
    # compile (below) then sees the network as existing and joins it.
    if not dry_run and not _is_passthrough(app):
        consumes_raw = app.get("consumes", [])
        if isinstance(consumes_raw, str):
            try:
                consumes_raw = json.loads(consumes_raw)
            except Exception:
                consumes_raw = []
        connectivity_providers = await _find_connectivity_providers(app_id, consumes_raw)
        if connectivity_providers:
            await _prep_provider_networks(job_id, connectivity_providers)

    app_ir = None
    if _is_passthrough(app):
        await _add_step(job_id, "render_compose", "running",
                        "Rendering docker-compose.yml (legacy passthrough)")
        config = app.get("config", {})
        schema = app.get("config_schema", [])
        rendered = _legacy_render_compose(app["compose_template"], config, schema, slug)
        env_content = _legacy_build_env(config, schema, slug)
        ir_hash = ""
        compose_hash = ""
        await _add_step(job_id, "render_compose", StepStatus.SUCCESS.value,
                        "Compose file rendered (passthrough)", finished_at=_now())
    else:
        await _add_step(job_id, "compile_ir", "running",
                        "Compiling application IR from template")
        compose_yaml, env_content, ir_hash, compose_hash, app_ir = await _compile_and_render(
            job_id, app_id, app
        )
        rendered = compose_yaml
        await _add_step(job_id, "compile_ir", StepStatus.SUCCESS.value,
                        f"IR compiled (hash: {ir_hash[:12]}...)", finished_at=_now())

    if not dry_run:
        await _add_step(job_id, "write_compose", "running",
                        "Writing docker-compose.yml and .env to disk")
        compose_path, env_path = write_compose_files(slug, rendered, env_content)

        async with get_db() as db:
            await db.execute(
                """UPDATE installed_apps
                   SET compose_path = ?, ir_hash = ?, compose_hash = ?
                   WHERE id = ?""",
                (compose_path, ir_hash, compose_hash, app_id),
            )
            await db.commit()

        await _add_step(job_id, "write_compose", StepStatus.SUCCESS.value,
                        f"Written: {compose_path}\nWritten: {env_path}", finished_at=_now())

        if app_ir is not None:
            puid, pgid = _extract_puid_pgid(app_ir)
            if puid and pgid:
                await _add_step(job_id, "chown_dirs", "running",
                                f"Preparing mount ownership (PUID={puid} PGID={pgid})")
                loop = asyncio.get_event_loop()
                compose_base = get_compose_base()
                log_lines = await loop.run_in_executor(
                    None, lambda: _prepare_mount_ownership(app_ir, puid, pgid, compose_base)
                )
                await _add_step(job_id, "chown_dirs", StepStatus.SUCCESS.value,
                                "\n".join(log_lines) or "No mounts required ownership changes",
                                finished_at=_now())

    if not dry_run:
        await _add_step(job_id, "docker_up", "running", "Running docker compose up -d")
        result = await _docker_compose(compose_path, ["up", "-d"])
        status = StepStatus.SUCCESS.value if result.returncode == 0 else StepStatus.FAILED.value
        await _add_step(job_id, "docker_up", status,
                        result.stdout + result.stderr, finished_at=_now())
        if result.returncode != 0:
            raise RuntimeError("docker compose up failed")

    # Run post_install hook
    if hooks.get("post_install"):
        hook_degraded = await _run_hook(job_id, app_id, slug, hooks, "post_install")
        has_degraded = has_degraded or hook_degraded

        # After hook, trigger capability events for consumers
        # (the hook may have written capabilities via registry_write steps)
        await trigger_reconcile_for_consumers(
            provider_app_id=app_id,
            event_type="capability_published",
            payload={"provider_slug": slug},
            is_reconcile=False,
        )

    await _set_app_state(app_id, "running" if not dry_run else "stopped")

    # Trigger update jobs on connected providers so they recompile and create
    # shared Docker networks before this consumer tries to join them.
    if not dry_run and not _is_passthrough(app):
        consumes_raw = app.get("consumes", [])
        if isinstance(consumes_raw, str):
            try:
                consumes_raw = json.loads(consumes_raw)
            except Exception:
                consumes_raw = []
        providers = await _find_connectivity_providers(app_id, consumes_raw)
        for provider in providers:
            await enqueue_job(provider["id"], "update")

    return has_degraded


async def _run_update(job_id: str, app_id: str, app: dict, dry_run: bool) -> bool:
    hooks = app.get("hook_definitions", {})
    slug = app["slug"]
    compose_path = app.get("compose_path", "")
    has_degraded = False

    if _is_passthrough(app):
        config = app.get("config", {})
        schema = app.get("config_schema", [])
        env_content = _legacy_build_env(config, schema, slug)

        if not dry_run:
            await _add_step(job_id, "render_compose", "running",
                            "Re-rendering docker-compose.yml (legacy passthrough)")
            rendered = _legacy_render_compose(app["compose_template"], config, schema, slug)
            await _add_step(job_id, "render_compose", StepStatus.SUCCESS.value,
                            "Compose file rendered", finished_at=_now())

            await _add_step(job_id, "write_compose", "running",
                            "Writing docker-compose.yml and .env")
            compose_path, env_path = write_compose_files(slug, rendered, env_content)
            async with get_db() as db:
                await db.execute(
                    "UPDATE installed_apps SET compose_path = ? WHERE id = ?",
                    (compose_path, app_id),
                )
                await db.commit()
            await _add_step(job_id, "write_compose", StepStatus.SUCCESS.value,
                            f"Written: {compose_path}", finished_at=_now())
    else:
        if not dry_run:
            await _add_step(job_id, "compile_ir", "running",
                            "Re-compiling application IR")
            compose_yaml, env_content, ir_hash, compose_hash, app_ir = await _compile_and_render(
                job_id, app_id, app
            )
            await _add_step(job_id, "compile_ir", StepStatus.SUCCESS.value,
                            f"IR compiled (hash: {ir_hash[:12]}...)", finished_at=_now())

            await _add_step(job_id, "write_compose", "running",
                            "Writing docker-compose.yml and .env")
            compose_path, env_path = write_compose_files(slug, compose_yaml, env_content)
            async with get_db() as db:
                await db.execute(
                    """UPDATE installed_apps
                       SET compose_path = ?, ir_hash = ?, compose_hash = ?
                       WHERE id = ?""",
                    (compose_path, ir_hash, compose_hash, app_id),
                )
                await db.commit()
            await _add_step(job_id, "write_compose", StepStatus.SUCCESS.value,
                            f"Written: {compose_path}", finished_at=_now())

            puid, pgid = _extract_puid_pgid(app_ir)
            if puid and pgid:
                await _add_step(job_id, "chown_dirs", "running",
                                f"Preparing mount ownership (PUID={puid} PGID={pgid})")
                loop = asyncio.get_event_loop()
                compose_base = get_compose_base()
                log_lines = await loop.run_in_executor(
                    None, lambda: _prepare_mount_ownership(app_ir, puid, pgid, compose_base)
                )
                await _add_step(job_id, "chown_dirs", StepStatus.SUCCESS.value,
                                "\n".join(log_lines) or "No mounts required ownership changes",
                                finished_at=_now())

    if not dry_run:
        await _add_step(job_id, "docker_pull", "running", "Pulling latest images")
        result = await _docker_compose(compose_path, ["pull"])
        await _add_step(job_id, "docker_pull",
                        StepStatus.SUCCESS.value if result.returncode == 0 else StepStatus.FAILED.value,
                        result.stdout + result.stderr, finished_at=_now())

        await _add_step(job_id, "docker_up", "running", "Running docker compose up -d")
        result = await _docker_compose(compose_path, ["up", "-d"])
        status = StepStatus.SUCCESS.value if result.returncode == 0 else StepStatus.FAILED.value
        await _add_step(job_id, "docker_up", status,
                        result.stdout + result.stderr, finished_at=_now())
        if result.returncode != 0:
            raise RuntimeError("docker compose up failed during update")

    # Run post_update hook (if defined), falling back to post_install for reconcile trigger
    hook_name = "post_update" if hooks.get("post_update") else None
    if hook_name:
        hook_degraded = await _run_hook(job_id, app_id, slug, hooks, hook_name)
        has_degraded = has_degraded or hook_degraded

    # Fire capability_changed event for all consumers
    await trigger_reconcile_for_consumers(
        provider_app_id=app_id,
        event_type="capability_changed",
        payload={"provider_slug": slug},
        is_reconcile=False,
    )

    await _set_app_state(app_id, "running" if not dry_run else "stopped")
    return has_degraded


async def _run_remove(job_id: str, app_id: str, app: dict, dry_run: bool) -> None:
    compose_path = app.get("compose_path", "")
    slug = app.get("slug", "")
    hooks = app.get("hook_definitions", {})

    # Run pre_remove hook before tearing down
    if hooks.get("pre_remove") and not dry_run:
        await _run_hook(job_id, app_id, slug, hooks, "pre_remove")

    if not dry_run and compose_path and Path(compose_path).exists():
        await _add_step(job_id, "collect_images", "running",
                        "Collecting image IDs for this app")
        img_result = await _docker_compose(compose_path, ["images", "-q"])
        image_ids = [line.strip() for line in img_result.stdout.splitlines() if line.strip()]

        # Fallback: if no containers exist (manually removed), resolve image refs
        # directly from the compose file via docker inspect on the image tag.
        if not image_ids:
            image_refs = _parse_image_refs_from_compose(compose_path)
            if image_refs:
                loop = asyncio.get_event_loop()
                image_ids = await loop.run_in_executor(
                    None, lambda: _resolve_image_ids(image_refs)
                )

        await _add_step(job_id, "collect_images", StepStatus.SUCCESS.value,
                        f"Found {len(image_ids)} image(s): {', '.join(image_ids) or 'none'}",
                        finished_at=_now())

        await _add_step(job_id, "docker_down", "running", "Running docker compose down")
        result = await _docker_compose(compose_path, ["down"])
        status = StepStatus.SUCCESS.value if result.returncode == 0 else StepStatus.FAILED.value
        await _add_step(job_id, "docker_down", status,
                        result.stdout + result.stderr, finished_at=_now())

        if image_ids:
            await _add_step(job_id, "remove_images", "running",
                            f"Removing {len(image_ids)} image(s)")
            rmi_result = await _docker_rmi(image_ids)
            rmi_status = StepStatus.SUCCESS.value if rmi_result.returncode == 0 else StepStatus.FAILED.value
            await _add_step(job_id, "remove_images", rmi_status,
                            rmi_result.stdout + rmi_result.stderr, finished_at=_now())

        app_dir = Path(compose_path).parent
        if slug and app_dir.exists() and app_dir.name == slug:
            await _add_step(job_id, "remove_files", "running",
                            f"Removing project directory: {app_dir}")
            try:
                shutil.rmtree(app_dir)
                await _add_step(job_id, "remove_files", StepStatus.SUCCESS.value,
                                f"Removed: {app_dir}", finished_at=_now())
            except Exception as exc:
                await _add_step(job_id, "remove_files", StepStatus.FAILED.value,
                                str(exc), finished_at=_now())

    # Fire provider_removed event for consumers before deleting app record
    await trigger_reconcile_for_consumers(
        provider_app_id=app_id,
        event_type="provider_removed",
        payload={"provider_slug": slug},
        is_reconcile=False,
    )

    # Collect providers before deleting — we'll trigger their recompile after
    # the record is gone so they see zero consumers and drop shared networks.
    consumes_raw = app.get("consumes", [])
    if isinstance(consumes_raw, str):
        try:
            consumes_raw = json.loads(consumes_raw)
        except Exception:
            consumes_raw = []
    providers_to_update = await _find_connectivity_providers(app_id, consumes_raw)

    await _add_step(job_id, "cleanup_db", "running",
                    "Removing app record from database")
    async with get_db() as db:
        await db.execute("DELETE FROM installed_apps WHERE id = ?", (app_id,))
        await db.commit()
    await _add_step(job_id, "cleanup_db", StepStatus.SUCCESS.value,
                    "App record removed", finished_at=_now())

    # Now that the consumer record is gone, recompile providers so they
    # drop any shared networks no longer needed by remaining consumers.
    for provider in providers_to_update:
        await enqueue_job(provider["id"], "update")


async def _docker_compose(compose_path: str, args: list[str]) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose", "-f", compose_path] + args
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=300),
    )


async def _docker_rmi(image_ids: list[str]) -> subprocess.CompletedProcess:
    cmd = ["docker", "image", "rm"] + image_ids
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=60),
    )


def _parse_image_refs_from_compose(compose_path: str) -> list[str]:
    """
    Extract image references from a compose file by reading lines that start with 'image:'.
    Used as a fallback when containers have already been manually removed.
    """
    try:
        text = Path(compose_path).read_text()
    except OSError:
        return []
    refs = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("image:"):
            ref = stripped[len("image:"):].strip().strip('"').strip("'")
            if ref:
                refs.append(ref)
    return refs


def _resolve_image_ids(image_refs: list[str]) -> list[str]:
    """
    Resolve image references (e.g. 'lscr.io/linuxserver/radarr:latest') to image IDs
    via docker inspect. Only returns IDs for images that are actually present locally.
    """
    ids = []
    for ref in image_refs:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.Id}}", ref],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            image_id = result.stdout.strip()
            if image_id:
                ids.append(image_id)
    return ids
