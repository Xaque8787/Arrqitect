"""
Action loader: reads and parses actions_definitions (YAML) from the DB
for a given installed app's template version, and looks up specific
action + variant definitions by ID.
"""

from __future__ import annotations

import yaml

from app.db.client import get_db


async def load_actions_yaml(app_id: str) -> dict | None:
    """
    Load parsed actions.yaml content for the installed app's template version.
    Returns None if the app has no template version or no actions defined.
    """
    async with get_db() as db:
        async with db.execute("""
            SELECT v.actions_definitions
            FROM installed_apps a
            LEFT JOIN template_versions v ON v.id = a.template_version_id
            WHERE a.id = ?
        """, (app_id,)) as cur:
            row = await cur.fetchone()

    if not row or not row[0]:
        return None

    try:
        parsed = yaml.safe_load(row[0])
    except Exception:
        return None

    if not isinstance(parsed, dict):
        return None

    return parsed


def find_action(actions_yaml: dict, action_id: str) -> dict | None:
    for action in actions_yaml.get("actions", []):
        if action.get("id") == action_id:
            return action
    return None


def find_variant(action_def: dict, variant_id: str) -> dict | None:
    for variant in action_def.get("variants", []):
        if variant.get("id") == variant_id:
            return variant
    return None


async def load_actions_yaml_for_slug(slug: str) -> dict | None:
    """
    Load parsed actions.yaml content by template slug (latest version).
    Used by the API endpoint before an app is installed.
    """
    async with get_db() as db:
        async with db.execute("""
            SELECT v.actions_definitions
            FROM app_templates t
            JOIN template_versions v ON v.template_id = t.id AND v.version = t.latest_version
            WHERE t.slug = ?
        """, (slug,)) as cur:
            row = await cur.fetchone()

    if not row or not row[0]:
        return None

    try:
        parsed = yaml.safe_load(row[0])
    except Exception:
        return None

    return parsed if isinstance(parsed, dict) else None
