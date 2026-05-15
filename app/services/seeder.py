"""
Seeds the three v1 app templates (Prowlarr, Radarr, Sonarr).
Idempotent — INSERT OR REPLACE on slug preserving existing IDs.

Volume mounts use type "volume_mount" with a fixed container_path defined
in the schema. The user provides host_path at install time. PUID, PGID,
and TZ come from global_settings at render time — not stored per-app.
"""

import json
from app.db.client import get_sync_conn

PROWLARR_COMPOSE = """\
services:
  prowlarr:
    image: lscr.io/linuxserver/prowlarr:latest
    container_name: prowlarr
    environment:
      - PUID={{ puid }}
      - PGID={{ pgid }}
      - TZ={{ timezone }}
    volumes:
      - {{ config_host }}:{{ config_container }}
    ports:
      - {{ host_port }}:9696
    restart: unless-stopped
"""

RADARR_COMPOSE = """\
services:
  radarr:
    image: lscr.io/linuxserver/radarr:latest
    container_name: radarr
    environment:
      - PUID={{ puid }}
      - PGID={{ pgid }}
      - TZ={{ timezone }}
    volumes:
      - {{ config_host }}:{{ config_container }}
      - {{ movies_host }}:{{ movies_container }}
      - {{ downloads_host }}:{{ downloads_container }}
    ports:
      - {{ host_port }}:7878
    restart: unless-stopped
"""

SONARR_COMPOSE = """\
services:
  sonarr:
    image: lscr.io/linuxserver/sonarr:latest
    container_name: sonarr
    environment:
      - PUID={{ puid }}
      - PGID={{ pgid }}
      - TZ={{ timezone }}
    volumes:
      - {{ config_host }}:{{ config_container }}
      - {{ tv_host }}:{{ tv_container }}
      - {{ downloads_host }}:{{ downloads_container }}
    ports:
      - {{ host_port }}:8989
    restart: unless-stopped
"""

# volume_mount fields: user edits host_path, container_path is fixed display-only.
# The template variable name is derived from key: "{key}_host" and "{key}_container".

TEMPLATES = [
    {
        "slug": "prowlarr",
        "name": "Prowlarr",
        "description": "Indexer manager and proxy for Radarr, Sonarr and other *arr apps.",
        "icon_url": "https://raw.githubusercontent.com/Prowlarr/Prowlarr/develop/Logo/256.png",
        "compose_template": PROWLARR_COMPOSE,
        "provides": ["indexer"],
        "config_schema": [
            {
                "key": "host_port",
                "label": "Host Port",
                "type": "number",
                "default": 9696,
                "required": True,
            },
            {
                "key": "config",
                "label": "Config",
                "type": "volume_mount",
                "default": "./config",
                "container_path": "/config",
                "required": True,
            },
        ],
        "hook_definitions": {
            "post_install": "Register with Radarr/Sonarr via API",
            "pre_remove": "Deregister from downstream apps",
        },
    },
    {
        "slug": "radarr",
        "name": "Radarr",
        "description": "Movie collection manager. CONSUMES: Prowlarr (indexer).",
        "icon_url": "https://raw.githubusercontent.com/Radarr/Radarr/develop/Logo/256.png",
        "compose_template": RADARR_COMPOSE,
        "provides": [],
        "config_schema": [
            {
                "key": "host_port",
                "label": "Host Port",
                "type": "number",
                "default": 7878,
                "required": True,
            },
            {
                "key": "config",
                "label": "Config",
                "type": "volume_mount",
                "default": "./config",
                "container_path": "/config",
                "required": True,
            },
            {
                "key": "movies",
                "label": "Movies",
                "type": "volume_mount",
                "default": "/data/movies",
                "container_path": "/movies",
                "required": True,
            },
            {
                "key": "downloads",
                "label": "Downloads",
                "type": "volume_mount",
                "default": "/data/downloads",
                "container_path": "/downloads",
                "required": True,
            },
        ],
        "hook_definitions": {
            "post_install": "Add Prowlarr as indexer via API",
            "pre_remove": "Remove from Prowlarr",
        },
    },
    {
        "slug": "sonarr",
        "name": "Sonarr",
        "description": "TV series collection manager. CONSUMES: Prowlarr (indexer).",
        "icon_url": "https://raw.githubusercontent.com/Sonarr/Sonarr/develop/Logo/256.png",
        "compose_template": SONARR_COMPOSE,
        "provides": [],
        "config_schema": [
            {
                "key": "host_port",
                "label": "Host Port",
                "type": "number",
                "default": 8989,
                "required": True,
            },
            {
                "key": "config",
                "label": "Config",
                "type": "volume_mount",
                "default": "./config",
                "container_path": "/config",
                "required": True,
            },
            {
                "key": "tv",
                "label": "TV",
                "type": "volume_mount",
                "default": "/data/tv",
                "container_path": "/tv",
                "required": True,
            },
            {
                "key": "downloads",
                "label": "Downloads",
                "type": "volume_mount",
                "default": "/data/downloads",
                "container_path": "/downloads",
                "required": True,
            },
        ],
        "hook_definitions": {
            "post_install": "Add Prowlarr as indexer via API",
            "pre_remove": "Remove from Prowlarr",
        },
    },
]


def seed_templates() -> None:
    conn = get_sync_conn()
    try:
        for tmpl in TEMPLATES:
            # Preserve existing ID so installed_apps FK references survive restarts
            conn.execute("""
                INSERT INTO app_templates
                    (id, slug, name, description, icon_url, compose_template,
                     config_schema, hook_definitions, provides)
                VALUES (
                    COALESCE(
                        (SELECT id FROM app_templates WHERE slug = ?),
                        lower(hex(randomblob(16)))
                    ),
                    ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(slug) DO UPDATE SET
                    name             = excluded.name,
                    description      = excluded.description,
                    icon_url         = excluded.icon_url,
                    compose_template = excluded.compose_template,
                    config_schema    = excluded.config_schema,
                    hook_definitions = excluded.hook_definitions,
                    provides         = excluded.provides,
                    updated_at       = strftime('%Y-%m-%dT%H:%M:%SZ','now')
            """, (
                tmpl["slug"],
                tmpl["slug"],
                tmpl["name"],
                tmpl["description"],
                tmpl["icon_url"],
                tmpl["compose_template"],
                json.dumps(tmpl["config_schema"]),
                json.dumps(tmpl["hook_definitions"]),
                json.dumps(tmpl["provides"]),
            ))
        conn.commit()
        print(f"[seeder] Templates seeded ({len(TEMPLATES)} checked)")
    finally:
        conn.close()
