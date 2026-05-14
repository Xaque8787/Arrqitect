"""
Seeds the three v1 app templates (Prowlarr, Radarr, Sonarr) into app_templates.
Idempotent — uses upsert on slug.
"""

from app.db.client import get_client

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
      - {{ resolve_host_path('./config') }}:/config
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
      - {{ resolve_host_path('./config') }}:/config
      - {{ movies_path }}:/movies
      - {{ downloads_path }}:/downloads
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
      - {{ resolve_host_path('./config') }}:/config
      - {{ tv_path }}:/tv
      - {{ downloads_path }}:/downloads
    ports:
      - {{ host_port }}:8989
    restart: unless-stopped
"""

TEMPLATES = [
    {
        "slug": "prowlarr",
        "name": "Prowlarr",
        "description": "Indexer manager and proxy for Radarr, Sonarr and other *arr apps.",
        "icon_url": "https://raw.githubusercontent.com/Prowlarr/Prowlarr/develop/Logo/256.png",
        "compose_template": PROWLARR_COMPOSE,
        "provides": ["indexer"],
        "config_schema": [
            {"key": "puid", "label": "PUID", "type": "number", "default": 1000, "required": True},
            {"key": "pgid", "label": "PGID", "type": "number", "default": 1000, "required": True},
            {"key": "timezone", "label": "Timezone", "type": "string", "default": "Etc/UTC", "required": True},
            {"key": "host_port", "label": "Host Port", "type": "number", "default": 9696, "required": True},
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
            {"key": "puid", "label": "PUID", "type": "number", "default": 1000, "required": True},
            {"key": "pgid", "label": "PGID", "type": "number", "default": 1000, "required": True},
            {"key": "timezone", "label": "Timezone", "type": "string", "default": "Etc/UTC", "required": True},
            {"key": "host_port", "label": "Host Port", "type": "number", "default": 7878, "required": True},
            {"key": "movies_path", "label": "Movies Path", "type": "string", "default": "/data/movies", "required": True},
            {"key": "downloads_path", "label": "Downloads Path", "type": "string", "default": "/data/downloads", "required": True},
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
            {"key": "puid", "label": "PUID", "type": "number", "default": 1000, "required": True},
            {"key": "pgid", "label": "PGID", "type": "number", "default": 1000, "required": True},
            {"key": "timezone", "label": "Timezone", "type": "string", "default": "Etc/UTC", "required": True},
            {"key": "host_port", "label": "Host Port", "type": "number", "default": 8989, "required": True},
            {"key": "tv_path", "label": "TV Path", "type": "string", "default": "/data/tv", "required": True},
            {"key": "downloads_path", "label": "Downloads Path", "type": "string", "default": "/data/downloads", "required": True},
        ],
        "hook_definitions": {
            "post_install": "Add Prowlarr as indexer via API",
            "pre_remove": "Remove from Prowlarr",
        },
    },
]


def seed_templates():
    db = get_client()
    for tmpl in TEMPLATES:
        db.table("app_templates").upsert(tmpl, on_conflict="slug").execute()
    print(f"[seeder] {len(TEMPLATES)} templates seeded")
