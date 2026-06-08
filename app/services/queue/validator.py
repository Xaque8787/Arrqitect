"""
Queue validator: validates a set of staged apps before bulk install.

Produces ValidationIssue records that the review modal renders.
Returns a QueueValidationResult with valid flag, install order, and issues list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

import yaml

from app.db.client import get_db
from app.services.queue.resolver import resolve_install_order


@dataclass
class ValidationIssue:
    severity: Literal["error", "warning"]
    type: str
    consumer_app_id: str
    consumer_app_name: str
    message: str
    target_app_slug: str | None = None
    field_id: str | None = None
    action_id: str | None = None


@dataclass
class QueueValidationResult:
    valid: bool
    install_order: list[str]
    issues: list[ValidationIssue]

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "install_order": self.install_order,
            "issues": [
                {
                    "severity": i.severity,
                    "type": i.type,
                    "consumer_app_id": i.consumer_app_id,
                    "consumer_app_name": i.consumer_app_name,
                    "message": i.message,
                    "target_app_slug": i.target_app_slug,
                    "field_id": i.field_id,
                    "action_id": i.action_id,
                }
                for i in self.issues
            ],
        }


def _parse_json_field(value, default):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value if value is not None else default


def _field_is_set(value, default) -> bool:
    """True if the config value is non-empty and not equal to the declared default."""
    if value is None:
        return False
    str_val = str(value).strip()
    if not str_val:
        return False
    str_default = str(default).strip() if default is not None else ""
    return str_val != str_default


async def validate_queue() -> QueueValidationResult:
    """
    Load all staged apps, resolve install order, run all validation checks.
    """
    issues: list[ValidationIssue] = []

    async with get_db() as db:
        # Load staged apps
        async with db.execute("""
            SELECT a.id, a.slug, a.name, a.config,
                   v.provides, v.consumes, v.config_schema,
                   v.service_definitions, v.actions_definitions
            FROM installed_apps a
            LEFT JOIN template_versions v ON v.id = a.template_version_id
            WHERE a.state = 'staged'
            ORDER BY a.created_at
        """) as cur:
            staged_rows = await cur.fetchall()

        # Load installed (running/stopped) apps — for satisfying consumes + requires checks
        async with db.execute("""
            SELECT a.id, a.slug, a.name, a.config,
                   v.provides, v.consumes
            FROM installed_apps a
            LEFT JOIN template_versions v ON v.id = a.template_version_id
            WHERE a.state IN ('running', 'stopped')
        """) as cur:
            installed_rows = await cur.fetchall()

        # Load all app_actions for staged apps
        staged_ids = [r["id"] for r in staged_rows]
        all_actions: dict[str, list[dict]] = {app_id: [] for app_id in staged_ids}
        if staged_ids:
            placeholders = ",".join("?" * len(staged_ids))
            async with db.execute(
                f"SELECT app_id, action_id, variant_id, fields FROM app_actions WHERE app_id IN ({placeholders})",
                staged_ids,
            ) as cur:
                action_rows = await cur.fetchall()
            for row in action_rows:
                all_actions[row["app_id"]].append(dict(row))

        # Load app_actions for installed apps (for requires checks)
        installed_ids = [r["id"] for r in installed_rows]
        installed_actions: dict[str, list[dict]] = {app_id: [] for app_id in installed_ids}
        if installed_ids:
            placeholders = ",".join("?" * len(installed_ids))
            async with db.execute(
                f"SELECT app_id, action_id FROM app_actions WHERE app_id IN ({placeholders})",
                installed_ids,
            ) as cur:
                for row in await cur.fetchall():
                    installed_actions[row["app_id"]].append(dict(row))

    staged_apps = [dict(r) for r in staged_rows]
    installed_apps = [dict(r) for r in installed_rows]

    for app in staged_apps:
        app["provides"] = _parse_json_field(app.get("provides"), [])
        app["consumes"] = _parse_json_field(app.get("consumes"), [])
        app["config"] = _parse_json_field(app.get("config"), {})
        app["config_schema"] = _parse_json_field(app.get("config_schema"), [])

    for app in installed_apps:
        app["provides"] = _parse_json_field(app.get("provides"), [])
        app["consumes"] = _parse_json_field(app.get("consumes"), [])
        app["config"] = _parse_json_field(app.get("config"), {})

    installed_slugs = {a["slug"] for a in installed_apps}

    # Build lookup maps
    installed_by_slug: dict[str, dict] = {a["slug"]: a for a in installed_apps}
    staged_by_slug: dict[str, dict] = {a["slug"]: a for a in staged_apps}

    # Build provides map across all apps (staged + installed)
    all_provides: dict[str, str] = {}  # registry_key -> slug
    for app in installed_apps + staged_apps:
        for p in app.get("provides", []):
            key = p.get("key") if isinstance(p, dict) else str(p)
            if key:
                all_provides[key] = app["slug"]

    # --- Check 1: Resolve install order (catches cycles) ---
    ordered_ids, cycle_errors = resolve_install_order(staged_apps, installed_slugs)
    for err in cycle_errors:
        # Assign cycle to first staged app since we don't know exactly which
        if staged_apps:
            issues.append(ValidationIssue(
                severity="error",
                type="dependency_cycle",
                consumer_app_id=staged_apps[0]["id"],
                consumer_app_name=staged_apps[0]["name"],
                message=err,
            ))

    # --- Check 2: Required config fields ---
    for app in staged_apps:
        config = app["config"]
        for field_def in app["config_schema"]:
            if not isinstance(field_def, dict):
                continue
            if field_def.get("visibility") == "hidden":
                continue
            if not field_def.get("required"):
                continue
            fid = field_def.get("id", "")
            val = config.get(fid)
            if not _field_is_set(val, field_def.get("default")):
                issues.append(ValidationIssue(
                    severity="error",
                    type="required_config_unset",
                    consumer_app_id=app["id"],
                    consumer_app_name=app["name"],
                    message=f'"{field_def.get("label", fid)}" is required but not set',
                    field_id=fid,
                ))

    # --- Check 3: consumes satisfaction ---
    for app in staged_apps:
        for c in app.get("consumes", []):
            key = c.get("key") if isinstance(c, dict) else str(c)
            if not key:
                continue
            provider_slug = all_provides.get(key)
            if provider_slug:
                continue
            # No provider found anywhere
            severity = "error" if (c.get("required") if isinstance(c, dict) else False) else "warning"
            issues.append(ValidationIssue(
                severity=severity,
                type="missing_provider",
                consumer_app_id=app["id"],
                consumer_app_name=app["name"],
                message=f'Requires "{key}" but no installed or staged app provides it',
                target_app_slug=None,
            ))

    # --- Check 4: cross-app requires from config fields ---
    for app in staged_apps:
        config = app["config"]
        field_value_is_set = {}
        for field_def in app["config_schema"]:
            if not isinstance(field_def, dict):
                continue
            fid = field_def.get("id", "")
            val = config.get(fid)
            field_value_is_set[fid] = _field_is_set(val, field_def.get("default"))

        for field_def in app["config_schema"]:
            if not isinstance(field_def, dict):
                continue
            if field_def.get("visibility") == "hidden":
                continue
            fid = field_def.get("id", "")
            if not field_value_is_set.get(fid):
                continue  # field itself isn't set; skip cross-app check for it

            for req in field_def.get("requires", []):
                if not isinstance(req, dict):
                    continue
                _check_requires(
                    req, app, fid, None,
                    staged_by_slug, installed_by_slug,
                    all_actions, installed_actions,
                    issues,
                )

    # --- Check 5: cross-app requires from action definitions ---
    for app in staged_apps:
        staged_action_records = all_actions.get(app["id"], [])
        if not staged_action_records:
            continue

        actions_yaml_raw = app.get("actions_definitions") or ""
        if not actions_yaml_raw:
            continue
        try:
            actions_yaml = yaml.safe_load(actions_yaml_raw) or {}
        except Exception:
            continue

        staged_action_ids = {r["action_id"] for r in staged_action_records}

        for action_def in actions_yaml.get("actions", []):
            if not isinstance(action_def, dict):
                continue
            action_id = action_def.get("id", "")
            if action_id not in staged_action_ids:
                continue  # this action not staged; skip

            for req in action_def.get("requires", []):
                if not isinstance(req, dict):
                    continue
                _check_requires(
                    req, app, None, action_id,
                    staged_by_slug, installed_by_slug,
                    all_actions, installed_actions,
                    issues,
                )

    has_errors = any(i.severity == "error" for i in issues)
    return QueueValidationResult(
        valid=not has_errors,
        install_order=ordered_ids,
        issues=issues,
    )


def _check_requires(
    req: dict,
    consumer_app: dict,
    field_id: str | None,
    action_id: str | None,
    staged_by_slug: dict[str, dict],
    installed_by_slug: dict[str, dict],
    staged_actions: dict[str, list[dict]],
    installed_actions: dict[str, list[dict]],
    issues: list[ValidationIssue],
) -> None:
    target_slug = req.get("app", "")
    req_config = req.get("config")
    req_action = req.get("action")
    severity = req.get("severity", "error")
    custom_message = req.get("message")

    context = f'"{field_id}" field' if field_id else f'"{action_id}" action'

    # Locate target app
    target_app = staged_by_slug.get(target_slug) or installed_by_slug.get(target_slug)
    if not target_app:
        message = custom_message or (
            f"{consumer_app['name']} {context} requires {target_slug} to be staged or installed, "
            f"but {target_slug} is not present"
        )
        issues.append(ValidationIssue(
            severity=severity,
            type="required_app_not_present",
            consumer_app_id=consumer_app["id"],
            consumer_app_name=consumer_app["name"],
            message=message,
            target_app_slug=target_slug,
            field_id=field_id,
            action_id=action_id,
        ))
        return

    target_app_id = target_app["id"]
    is_staged = target_slug in staged_by_slug

    if req_config:
        target_config = target_app.get("config", {})
        # Find the field default from schema
        target_schema = _parse_json_field(target_app.get("config_schema"), [])
        default_val = None
        for fd in target_schema:
            if isinstance(fd, dict) and fd.get("id") == req_config:
                default_val = fd.get("default")
                break
        val = target_config.get(req_config)
        if not _field_is_set(val, default_val):
            message = custom_message or (
                f'{consumer_app["name"]} {context} requires {target_slug} '
                f'to have "{req_config}" configured, but it is unset'
            )
            issues.append(ValidationIssue(
                severity=severity,
                type="cross_app_requires_unmet",
                consumer_app_id=consumer_app["id"],
                consumer_app_name=consumer_app["name"],
                message=message,
                target_app_slug=target_slug,
                field_id=field_id,
                action_id=action_id,
            ))

    elif req_action:
        # Check that the target has at least one app_action with this action_id
        if is_staged:
            target_action_list = staged_actions.get(target_app_id, [])
        else:
            target_action_list = installed_actions.get(target_app_id, [])

        has_action = any(r.get("action_id") == req_action for r in target_action_list)
        if not has_action:
            message = custom_message or (
                f'{consumer_app["name"]} {context} requires {target_slug} '
                f'to have action "{req_action}" configured, but it is not set'
            )
            issues.append(ValidationIssue(
                severity=severity,
                type="cross_app_requires_unmet",
                consumer_app_id=consumer_app["id"],
                consumer_app_name=consumer_app["name"],
                message=message,
                target_app_slug=target_slug,
                field_id=field_id,
                action_id=req_action,
            ))


def _parse_json_field(value, default):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value if value is not None else default
