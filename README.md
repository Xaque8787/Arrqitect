# Arrqitect

Arrqitect is a self-hosted app manager for Docker Compose stacks. It lets you browse a template library, configure apps through a guided UI, stage them in an install queue, and deploy them — all without writing a single line of YAML by hand.

It is built for media server enthusiasts who run *arr stacks (Radarr, Sonarr, Prowlarr) and similar services, and want those apps to self-wire their integrations automatically after install.

---

## How It Works

### Templates

Every app in the library is described by a **template** — a YAML file that declares what the app is, what it needs, what it provides to other apps, and how its Docker Compose service should be structured. Templates live in a repository and are synced into Arrqitect on demand.

Templates are intentionally **Docker-agnostic**. They describe intent (`this service needs a persistent config volume`, `this port is externally reachable`) rather than Docker specifics. A compilation pipeline called the ECB (Expression Compiler and Binder) translates that intent into a rendered `docker-compose.yml`.

See [AUTHORS.md](AUTHORS.md) for a full guide to writing templates.

### Template Repositories

A template repository is a directory (local or remote) containing:

```
index.json
prowlarr/
  template.yaml
  actions.yaml          # optional
  hooks/
    post_install.yaml   # optional
    pre_remove.yaml     # optional
radarr/
  template.yaml
  ...
```

`index.json` lists all available templates and their paths:

```json
{
  "schema_version": 1,
  "templates": [
    { "slug": "prowlarr", "path": "prowlarr/template.yaml" },
    { "slug": "radarr",   "path": "radarr/template.yaml"  }
  ]
}
```

Arrqitect fetches this index, then fetches each template file, validates and hashes it, and stores it in the local database. Template versions are **immutable** — once a `(slug, version)` pair is stored, its content cannot change. Attempting to re-sync a modified template at the same version number is rejected.

### The ECB Pipeline

When a user configures and installs an app, the ECB pipeline runs in several stages:

1. **Parse** — the template YAML is validated against the schema and loaded into typed models.
2. **Resolve** — user-supplied config values are merged with schema defaults; host paths are resolved to absolute paths; environment variables, ports, and storage mounts are bound to their targets.
3. **Compile** — a renderer-agnostic Intermediate Representation (IR) is assembled and hashed. The IR hash detects configuration drift across installs.
4. **Render** — the IR is lowered into a `docker-compose.yml` by the only file in the codebase that knows Docker Compose syntax. Values are embedded directly; no `.env` file is used.

This separation means the same template could theoretically target a different orchestrator by swapping only the renderer.

### Capabilities: Provides and Consumes

Apps can expose **capabilities** (API keys, internal URLs, external URLs) and declare that they **consume** capabilities from other apps. This is how automatic cross-app integration works.

When Prowlarr installs, its `post_install` hook reads the generated API key from the config file and writes it into a shared **registry** alongside its internal and external URLs. When Radarr installs, its own hook reads those registry values and calls Prowlarr's API to register itself — automatically, without user involvement.

When a capability changes (e.g., Prowlarr's API key rotates), a **reconcile job** fires automatically for every consumer that declared it consumes that capability. The consumer's `post_install` hook re-runs with `is_reconcile: true`, picks up the new values, and re-registers. This keeps multi-app stacks in sync continuously.

### Hooks

Hooks are YAML-defined step sequences that run at lifecycle events:

- **`post_install`** — runs after the Compose stack is brought up. Used to read generated credentials, publish capabilities, and register with other apps.
- **`pre_remove`** — runs before the Compose stack is torn down. Used to deregister from other apps and clean up.

Each hook is a DAG of steps. Steps can depend on other steps, carry conditional `when:` guards, and declare whether failures are blocking (`on_error: fail`) or graceful (`on_error: continue`). Step types include HTTP requests, registry reads/writes, file reads, file polling, and Compose commands.

### Actions

Actions are user-configurable operations that run after a successful install. They are defined in `actions.yaml` alongside a template. Each action has one or more **variants** — for example, an `add_indexer` action on Prowlarr might offer YTS, Nyaa.si, and The Pirate Bay as variants. Users select which variants to add during the configuration wizard, optionally customizing field values.

Actions support **idempotency checks** — before executing, they query the target API and skip if the resource already exists.

### The Queue

Apps are staged in a **queue** before installation. The queue allows multiple apps to be configured together and installed as a batch, respecting dependency order automatically. The queue validator checks for missing required config, unsatisfied capability dependencies, and circular dependency cycles before install begins.

---

## UI Overview

| View | Purpose |
|------|---------|
| **Dashboard** | System overview, quick status |
| **Library** | Browse templates, open staging wizard |
| **Queue** | Review and install staged apps |
| **Installed Apps** | Manage running apps, trigger actions |
| **App Detail** | Per-app config, actions, snapshots, logs |
| **Job Log** | Live job step output via WebSocket |
| **Settings** | Global PUID/PGID/timezone, template repo URL |

---

## Architecture

```
frontend (React/Vite)
    │
    └── REST API (FastAPI)
            │
            ├── ECB Pipeline (parse → resolve → compile → render)
            ├── Hook Executor (DAG runner, registry, reconciler)
            ├── Action Executor (idempotent HTTP actions)
            └── SQLite DB (templates, apps, jobs, registry, events)
```

The backend is a single FastAPI process. The frontend is a compiled Vite SPA served from `frontend/dist`. A WebSocket endpoint (`/ws`) pushes real-time job step updates to the UI.

---

## Template Authoring

For a full reference on writing templates — including every key, all step types, capability modeling, hook design patterns, and worked examples — see [AUTHORS.md](AUTHORS.md).
