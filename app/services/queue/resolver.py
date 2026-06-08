"""
Queue resolver: derives ordered install plan from staged apps.

Sources for ordering (in priority):
  1. Topological sort from provides/consumes relationships
  2. install_after hints from templates/index.json per-template entries
  3. Stable sort preserving original staging order for ties

Returns the ordered list of app_ids and any detected cycles.
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from pathlib import Path


_INDEX_PATH = Path(__file__).parent.parent.parent.parent / "templates" / "index.json"


def _load_index_hints() -> dict[str, list[str]]:
    """
    Returns slug -> [must_install_after_slug, ...] from templates/index.json.
    install_order field gives a positional fallback; install_after on each entry
    gives explicit precedence edges.
    """
    hints: dict[str, list[str]] = defaultdict(list)
    try:
        if not _INDEX_PATH.exists():
            return hints
        index = json.loads(_INDEX_PATH.read_text())
        # Positional install_order list
        order = index.get("install_order", [])
        for i, slug in enumerate(order):
            if i > 0:
                hints[slug].append(order[i - 1])
        # Per-template explicit install_after
        for entry in index.get("templates", []):
            slug = entry.get("slug", "")
            after = entry.get("install_after", [])
            if slug and after:
                hints[slug].extend(after)
    except Exception:
        pass
    return hints


def resolve_install_order(
    staged_apps: list[dict],
    installed_slugs: set[str],
) -> tuple[list[str], list[str]]:
    """
    Resolve install order for a list of staged app dicts.

    Each staged app dict must have: id, slug, provides (list[dict]), consumes (list[dict]).
    installed_slugs is the set of already-installed app slugs (they satisfy deps but
    are not re-installed).

    Returns:
        (ordered_app_ids, cycle_errors)
        ordered_app_ids: app ids in install order
        cycle_errors: list of human-readable cycle descriptions
    """
    if not staged_apps:
        return [], []

    # Build slug -> app mapping for staged apps
    slug_to_app = {a["slug"]: a for a in staged_apps}
    staged_slugs = set(slug_to_app.keys())

    # Build provides map: registry_key -> slug (across all staged apps)
    provides_map: dict[str, str] = {}
    for app in staged_apps:
        for p in app.get("provides", []):
            key = p.get("key") if isinstance(p, dict) else str(p)
            if key:
                provides_map[key] = app["slug"]

    # Build dependency graph: slug -> set of slugs that must install before it
    deps: dict[str, set[str]] = {a["slug"]: set() for a in staged_apps}

    for app in staged_apps:
        for c in app.get("consumes", []):
            key = c.get("key") if isinstance(c, dict) else str(c)
            if not key:
                continue
            provider_slug = provides_map.get(key)
            if provider_slug and provider_slug != app["slug"] and provider_slug in staged_slugs:
                deps[app["slug"]].add(provider_slug)

    # Apply index.json hints
    index_hints = _load_index_hints()
    for app in staged_apps:
        slug = app["slug"]
        for after_slug in index_hints.get(slug, []):
            if after_slug in staged_slugs:
                deps[slug].add(after_slug)

    # Kahn's topological sort
    in_degree = {slug: 0 for slug in staged_slugs}
    graph: dict[str, list[str]] = defaultdict(list)
    for slug, predecessors in deps.items():
        for pred in predecessors:
            graph[pred].append(slug)
            in_degree[slug] += 1

    # Start with nodes that have no dependencies, preserving original order
    slug_order = [a["slug"] for a in staged_apps]
    queue: deque[str] = deque(
        s for s in slug_order if in_degree[s] == 0
    )
    ordered_slugs: list[str] = []

    while queue:
        slug = queue.popleft()
        ordered_slugs.append(slug)
        # Advance neighbors in original slug_order to preserve stable sort
        for neighbor in sorted(graph[slug], key=lambda s: slug_order.index(s) if s in slug_order else 9999):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    cycle_errors: list[str] = []
    if len(ordered_slugs) < len(staged_slugs):
        remaining = staged_slugs - set(ordered_slugs)
        cycle_errors.append(
            f"Circular dependency detected among: {', '.join(sorted(remaining))}. "
            "These apps cannot be installed."
        )
        # Append remaining in original order so they still appear in results
        for slug in slug_order:
            if slug in remaining:
                ordered_slugs.append(slug)

    ordered_ids = [slug_to_app[s]["id"] for s in ordered_slugs]
    return ordered_ids, cycle_errors
