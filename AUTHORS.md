# Template Authoring Guide

This guide covers everything you need to write app templates for Arrqitect. It assumes familiarity with Docker Compose concepts but no prior knowledge of Arrqitect internals.

---

## Table of Contents

1. [Repository Structure](#1-repository-structure)
2. [template.yaml Reference](#2-templateyaml-reference)
   - [Top-level fields](#21-top-level-fields)
   - [app block](#22-app-block)
   - [services block](#23-services-block)
   - [config_schema block](#24-config_schema-block)
   - [provides block](#25-provides-block)
   - [consumes block](#26-consumes-block)
   - [hooks block](#27-hooks-block)
3. [Hooks Reference](#3-hooks-reference)
   - [Step types](#31-step-types)
   - [Common step fields](#32-common-step-fields)
   - [Dependency graph](#33-dependency-graph)
   - [when: conditions](#34-when-conditions)
   - [Template expressions](#35-template-expressions)
   - [Context namespaces](#36-context-namespaces)
4. [Actions Reference](#4-actions-reference)
   - [Action fields](#41-action-fields)
   - [Variant fields](#42-variant-fields)
   - [Field types](#43-field-types)
   - [Idempotency](#44-idempotency)
5. [The Registry](#5-the-registry)
6. [Reconciliation](#6-reconciliation)
7. [Validation Rules](#7-validation-rules)
8. [Complete Examples](#8-complete-examples)
9. [Design Patterns](#9-design-patterns)

---

## 1. Repository Structure

A template repository is a directory with this layout:

```
index.json
<slug>/
  template.yaml
  actions.yaml          # optional — only if the app has configurable actions
  hooks/
    post_install.yaml   # optional — runs after stack is brought up
    pre_remove.yaml     # optional — runs before stack is torn down
```

### index.json

```json
{
  "schema_version": 1,
  "templates": [
    { "slug": "prowlarr", "path": "prowlarr/template.yaml" },
    { "slug": "radarr",   "path": "radarr/template.yaml"  },
    { "slug": "sonarr",   "path": "sonarr/template.yaml"  }
  ]
}
```

The `slug` becomes the app's identifier throughout the system. It must be lowercase, alphanumeric, and hyphen-safe. The `path` is relative to the repository root.

---

## 2. template.yaml Reference

### 2.1 Top-level fields

```yaml
schema_version: 2      # always 2 for modern templates
app: { ... }
services: [ ... ]
config_schema: [ ... ]
provides: [ ... ]      # optional
consumes: [ ... ]      # optional
hooks:                 # optional
  post_install: hooks/post_install.yaml
  pre_remove:   hooks/pre_remove.yaml
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema_version` | int | yes | Must be `2`. |
| `app` | object | yes | App identity metadata. |
| `services` | list | yes | One or more service declarations. |
| `config_schema` | list | yes | User-configurable fields. |
| `provides` | list | no | Capabilities this app publishes to the registry. |
| `consumes` | list | no | Capabilities this app reads from the registry. |
| `hooks` | object | no | Lifecycle hook file paths. |

---

### 2.2 app block

```yaml
app:
  id: radarr
  name: Radarr
  version: "1.4.0"
  flavor: linuxserver
  allow_custom_env: false
  allow_custom_storage: false
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Matches the slug in `index.json`. Must be unique. |
| `name` | string | yes | Human-readable display name. |
| `version` | string | yes | Semantic version string. Immutable once published. |
| `flavor` | string | yes | `linuxserver` or `generic`. Controls PUID/PGID/TZ injection. |
| `allow_custom_env` | bool | no | Allow users to add arbitrary env vars. Default `false`. |
| `allow_custom_storage` | bool | no | Allow users to add arbitrary volume mounts. Default `false`. |

**Flavor behavior**: When `flavor: linuxserver`, the compiler automatically injects `PUID`, `PGID`, and `TZ` environment variables from the global settings into every service. You do not declare these in `config_schema`.

---

### 2.3 services block

Each entry describes one Docker service. A template must have at least one service.

```yaml
services:
  - id: radarr
    image:
      repository: lscr.io/linuxserver/radarr
      tag: latest
    networking:
      ports:
        - id: web_ui
          listen_port: 7878
          protocol: http
          reachability: external
    storage:
      - id: config
        container_path: /config
        persistence: persistent
        propagation: private
        mutability: read-write
        durability: configuration
      - id: movies
        container_path: /movies
        persistence: persistent
        propagation: shared
        mutability: read-write
        durability: user-data
    lifecycle:
      restart:
        behavior: persistent
```

#### image

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `repository` | string | yes | Image name without tag. |
| `tag` | string | yes | Image tag. Use pinned versions for stability. |

#### networking.ports

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Identifier used to bind a config field to this port. |
| `listen_port` | int | yes | Port the container listens on. |
| `protocol` | string | yes | `http`, `https`, `tcp`, or `udp`. |
| `reachability` | string | yes | `external` (host port mapping), `internal` (container-only), or `none` (omit). |

Only ports with `reachability: external` get a `ports:` entry in the rendered Compose file. The published (host) port comes from the bound config field.

#### storage entries

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Identifier used to bind a config field to this mount. |
| `container_path` | string | yes | Absolute path inside the container. Must be unique per service. |
| `persistence` | string | yes | `persistent` (survives removal) or `ephemeral` (destroyed on stop). |
| `propagation` | string | yes | `private`, `shared`, `slave`, or `rslave`. See table below. |
| `mutability` | string | yes | `read-write` or `read-only`. |
| `durability` | string | yes | Advisory label: `configuration`, `user-data`, or `transient`. Does not affect runtime behavior. |

**Propagation semantics**:

| Template value | Docker bind-mount flag | Meaning |
|----------------|------------------------|---------|
| `private` | `rprivate` | No mount propagation in either direction |
| `shared` | `rshared` | Mounts in both host and container are visible to each other |
| `slave` | `rslave` | Host mounts visible inside container only |
| `rslave` | `slave` | Container mounts visible on host only |

Use `shared` for directories that multiple services share (e.g., `/downloads`), and `private` for app-specific config directories.

#### lifecycle.restart

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `behavior` | string | yes | `persistent` (unless-stopped), `on-failure`, or `never` (no). |

---

### 2.4 config_schema block

Config fields are the user-configurable inputs shown in the install wizard.

```yaml
config_schema:
  - id: web_ui_port
    label: Web UI Port
    type: port
    default: 7878
    binds_to: services.radarr.ports.web_ui.published_port
    required: false
    visibility: visible
    source: user

  - id: config_path
    label: Config Path
    type: storage_path
    default: ./config
    binds_to: services.radarr.storage.config.host_path
    required: false
    visibility: visible
    source: user

  - id: movies_path
    label: Movies Path
    type: storage_path
    default: ""
    binds_to: services.radarr.storage.movies.host_path
    required: true
    visibility: visible
    source: user
    requires:
      - app: prowlarr
        action: yts
        severity: warning
        message: "Install Prowlarr with the YTS indexer for automatic movie discovery"

  - id: web_ui_port_env
    label: Web UI Port (env)
    type: port
    default: 7878
    binds_to: services.radarr.env.RADARR__SERVER__PORT
    required: false
    visibility: hidden
    source: platform
```

#### Field reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Unique identifier within the template. |
| `label` | string | yes | Human-readable label shown in the UI. |
| `type` | string | yes | Data type. See types table below. |
| `default` | any | no | Default value pre-filled in the wizard. |
| `binds_to` | string | yes | Dot-path of the service attribute this field controls. |
| `required` | bool | yes | Whether the field must have a non-empty value before install. |
| `visibility` | string | yes | `visible`, `advanced`, or `hidden`. |
| `source` | string | yes | `user`, `platform`, or `derived`. |
| `allowed_values` | list | no | Restricts to an enumerated set of values. |
| `ui_widget` | string | no | `input` or `select`. Only relevant when `allowed_values` is set. |
| `editable` | bool | no | If `false`, the field is read-only in the edit wizard. Default `true`. |
| `requires` | list | no | Cross-app preconditions for this field. See below. |

#### Field types

| Type | Description |
|------|-------------|
| `port` | Integer port number. |
| `storage_path` | Host filesystem path. Relative paths (e.g. `./config`) are resolved to absolute paths under the app's compose directory. |
| `string` | Arbitrary text. |
| `number` | Numeric value. |
| `boolean` | `true` or `false`. |

#### binds_to paths

The `binds_to` field links a config value to a specific attribute of a specific service:

| binds_to pattern | Effect |
|------------------|--------|
| `services.<id>.ports.<port_id>.published_port` | Sets the host-side published port. |
| `services.<id>.storage.<storage_id>.host_path` | Sets the host-side mount path. |
| `services.<id>.env.<ENV_NAME>` | Sets an environment variable on the service. |

#### visibility

- `visible` — shown prominently in the wizard.
- `advanced` — hidden behind an "Advanced" disclosure toggle.
- `hidden` — never shown; value comes from `default` or is injected by the platform.

#### source

- `user` — value entered by the user.
- `platform` — injected automatically (e.g., a port also needed as an env var).
- `derived` — computed from other config values (reserved, currently informational).

#### requires (cross-app preconditions)

A `requires` entry on a config field allows you to declare that a certain config field only makes full sense when another app is installed and/or has a specific action configured.

```yaml
requires:
  - app: prowlarr             # slug of the required app
    config: config_path       # optional: required config field on that app
    action: yts               # optional: required action variant on that app
    severity: warning         # "error" blocks install; "warning" shows advisory
    message: "Custom message shown in the UI"
```

Exactly one of `config` or `action` must be set, not both. Severity `error` prevents the queue from validating; `warning` is advisory only.

---

### 2.5 provides block

`provides` declares capabilities this app publishes to the registry after installation. These become available to other apps via `consumes`.

```yaml
provides:
  - key: prowlarr.api_key
    type: credential
    sensitive: true
    rotates: true

  - key: prowlarr.url_internal
    type: endpoint
    sensitive: false
    rotates: false

  - key: prowlarr.url_external
    type: endpoint
    sensitive: false
    rotates: false
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `key` | string | yes | Registry key. Must start with the app slug and a dot. |
| `type` | string | yes | `credential`, `endpoint`, `metadata`, or `feature-flag`. |
| `sensitive` | bool | yes | Whether to redact the value in logs and UI. |
| `rotates` | bool | yes | Whether the value can change after initial publish. Used for planning reconciliation. |

**Key naming convention**: Always prefix with your app slug: `prowlarr.api_key`, not just `api_key`. This prevents collisions and makes dependency graphs readable.

The actual values are written by `registry_write` steps in `post_install.yaml`. Declaring a capability in `provides` is a schema contract; the hook is what actually populates the registry.

---

### 2.6 consumes block

`consumes` declares capabilities this app reads from other apps. This drives reconciliation: when a consumed capability changes, the consumer's `post_install` hook is re-run automatically.

```yaml
consumes:
  - key: prowlarr.api_key
    required: false
    connectivity: true

  - key: prowlarr.url_internal
    required: false
    connectivity: false

  - key: prowlarr.url_external
    required: false
    connectivity: false
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `key` | string | yes | Registry key to consume. Must match a `provides.key` from another template. |
| `required` | bool | yes | If `true`, install is blocked unless the provider is installed. |
| `connectivity` | bool | yes | If `true`, a network route is established between this app and the provider (reserved for future use; declare accurately). |

**Optional dependencies**: Setting `required: false` allows graceful degradation. The consumer's hook must use `on_error: continue` on steps that read the provider's registry values, so the install succeeds even if the provider is absent.

---

### 2.7 hooks block

```yaml
hooks:
  post_install: hooks/post_install.yaml
  pre_remove:   hooks/pre_remove.yaml
```

Paths are relative to the template directory. Both hooks are optional. If a hook file is absent, that lifecycle event is a no-op.

---

## 3. Hooks Reference

Hooks are YAML files defining a list of steps. Steps form a DAG (directed acyclic graph) — each step can declare dependencies on other steps, and the executor runs them in topological order.

### Basic structure

```yaml
steps:
  - id: wait_for_config
    type: wait_for_file
    params:
      path: /host-compose/myapp/config/config.xml
      poll_interval_seconds: 5
      timeout_seconds: 180

  - id: read_api_key
    type: file_read
    depends_on: [wait_for_config]
    params:
      path: /host-compose/myapp/config/config.xml
      regex: '<ApiKey>(.*?)</ApiKey>'
      bind_as: myapp_api_key

  - id: publish_api_key
    type: registry_write
    depends_on: [read_api_key]
    params:
      key: myapp.api_key
      value: "<<registry_context.myapp_api_key>>"
```

---

### 3.1 Step types

#### `registry_read`

Read a value from the capability registry and bind it to the step context.

```yaml
- id: read_prowlarr_key
  type: registry_read
  on_error: continue
  params:
    key: prowlarr.api_key
    bind_as: prowlarr_api_key
```

| Param | Required | Description |
|-------|----------|-------------|
| `key` | yes | Registry key to read. |
| `bind_as` | yes | Variable name to store the value under in the step context. |

If the key does not exist in the registry and `on_error: continue` is set, the step completes with a CONTINUE_SUCCESS status and binds an empty string. If `on_error: fail` (the default), a missing key fails the hook.

---

#### `registry_write`

Write a value to the capability registry. Increments the capability's version, which triggers reconcile jobs for all consumers.

```yaml
- id: publish_api_key
  type: registry_write
  depends_on: [read_api_key]
  params:
    key: prowlarr.api_key
    value: "<<registry_context.prowlarr_api_key>>"
```

| Param | Required | Description |
|-------|----------|-------------|
| `key` | yes | Registry key to write. Must start with the app's own slug and a dot. |
| `value` | yes | Value to store. Supports template expressions. |

**Namespace enforcement**: A `registry_write` step in a Prowlarr hook may only write keys beginning with `prowlarr.`. Writing to another app's namespace is rejected at validation time.

**No template expressions in `key`**: The key must be a literal string. Only the `value` may contain template expressions.

---

#### `http_request`

Make an HTTP request to an internal or external service.

```yaml
- id: register_with_prowlarr
  type: http_request
  depends_on: [read_prowlarr_key, read_prowlarr_url]
  when: "registry.prowlarr_api_key != '' and registry.existing_app_id == ''"
  on_error: continue
  params:
    method: POST
    url: "http://<<registry.prowlarr_url_internal>>/api/v1/applications"
    headers:
      Content-Type: application/json
      X-Api-Key: "<<registry.prowlarr_api_key>>"
    body: >-
      {"name":"Radarr","syncLevel":"fullSync","appProfileId":1,
       "prowlarrUrl":"http://prowlarr:9696",
       "baseUrl":"http://radarr:7878",
       "apiKey":"<<registry.radarr_api_key>>",
       "syncCategories":[2000,2010,2020,2030,2040,2050,2060,2070,2080]}
    bind_response_json: id
    bind_as: radarr_prowlarr_app_id
```

| Param | Required | Description |
|-------|----------|-------------|
| `method` | yes | HTTP method: `GET`, `POST`, `PUT`, `DELETE`. |
| `url` | yes | Target URL. Supports template expressions. |
| `headers` | no | Key-value map of headers. Values support template expressions. |
| `body` | no | Request body string. Supports template expressions. |
| `bind_response_json` | no | JSON field name to extract from the response body. |
| `bind_as` | no | Variable name to store the extracted response value. Required if `bind_response_json` is set. |

When `on_error: continue`, a non-2xx response does not fail the hook — the step completes with CONTINUE_SUCCESS (degraded), and `bind_as` is bound to an empty string.

---

#### `wait_for_file`

Poll a file path until it exists, then proceed.

```yaml
- id: wait_for_config
  type: wait_for_file
  params:
    path: /host-compose/prowlarr/config/config.xml
    poll_interval_seconds: 5
    timeout_seconds: 180
```

| Param | Required | Description |
|-------|----------|-------------|
| `path` | yes | Absolute host path to poll. |
| `poll_interval_seconds` | no | How often to check. Default 5. |
| `timeout_seconds` | no | Maximum wait time. Default 60. Overrides the step-level timeout. |

The step succeeds as soon as the file exists. If `timeout_seconds` elapses, the step status is TIMEOUT, which behaves like a failure unless `on_error: continue` is set.

---

#### `file_read`

Read a file from the host filesystem and optionally extract a value via regex.

```yaml
- id: read_api_key
  type: file_read
  depends_on: [wait_for_config]
  params:
    path: /host-compose/prowlarr/config/config.xml
    regex: '<ApiKey>(.*?)</ApiKey>'
    bind_as: prowlarr_real_api_key
```

| Param | Required | Description |
|-------|----------|-------------|
| `path` | yes | Absolute host path to read. Supports template expressions. |
| `regex` | no | Python regex pattern. Capture group 1 is extracted. |
| `bind_as` | yes | Variable name to store the result. |

If `regex` is provided and no match is found, the step fails (or CONTINUE_SUCCESS with empty string if `on_error: continue`). If no `regex` is provided, the entire file content is bound.

---

#### `compose_command`

Run a Docker Compose command for this app's stack.

```yaml
- id: stop_service
  type: compose_command
  params:
    command: stop
```

| Param | Required | Description |
|-------|----------|-------------|
| `command` | yes | Compose subcommand and any arguments (e.g., `stop`, `restart`, `pull`). |

**Use sparingly.** Compose commands that modify state (start/stop/restart) are powerful and potentially disruptive. The validator emits a warning for unguarded compose commands (those without a `when:` condition or explicit `critical: true`). In most cases, hooks should use HTTP requests or registry operations rather than compose commands.

---

#### `log`

Emit a log message. Useful for marking phases in complex hooks.

```yaml
- id: log_complete
  type: log
  depends_on: [publish_api_key]
  params:
    message: "Prowlarr setup complete"
```

| Param | Required | Description |
|-------|----------|-------------|
| `message` | yes | Log message string. Supports template expressions. |

---

### 3.2 Common step fields

These fields apply to all step types:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | string | required | Unique identifier within the hook. Used in `depends_on`. |
| `type` | string | required | Step type. See above. |
| `depends_on` | list | `[]` | List of step IDs that must complete before this step runs. |
| `when` | string | (always run) | Conditional expression. Step is skipped if false. |
| `on_error` | string | `fail` | `fail` (block hook) or `continue` (degrade gracefully). |
| `critical` | bool | `true` | Whether this step's failure affects overall job status. Mainly relevant with `on_error: continue`. |
| `timeout_seconds` | int | 30 | Maximum step execution time. |

---

### 3.3 Dependency graph

Steps run in topological order based on `depends_on`. The executor validates:
- All referenced step IDs exist.
- The dependency graph has no cycles.
- A step only runs after all its dependencies have reached a satisfying status.

If a dependency fails (and did not use `on_error: continue`), all downstream steps that depend on it are skipped.

```yaml
steps:
  - id: a
    type: log
    params: { message: "step a" }

  - id: b
    type: log
    depends_on: [a]
    params: { message: "step b, runs after a" }

  - id: c
    type: log
    depends_on: [a]
    params: { message: "step c, also runs after a" }

  - id: d
    type: log
    depends_on: [b, c]
    params: { message: "step d, runs after both b and c" }
```

---

### 3.4 when: conditions

The `when:` field guards a step with a boolean condition. The step is skipped (not failed) if the condition evaluates to false.

```yaml
when: "registry.prowlarr_api_key != ''"
when: "registry.prowlarr_api_key != '' and registry.existing_app_id == ''"
```

**Grammar rules** (strictly enforced):

- Simple form: `<dot.path> <op> '<literal>'`
- Compound form: `<simple> and <simple>` (exactly one `and`, no `or`, no parentheses)
- Operators: `==` and `!=` only
- Literals must be single-quoted strings
- No Jinja syntax (`{%`, `{{`) — these are rejected at validation time
- No numeric comparisons

The left-hand side is a dot-path resolved against the step context (see [Context namespaces](#36-context-namespaces)).

**Common patterns**:

```yaml
# Only run if Prowlarr is available
when: "registry.prowlarr_api_key != ''"

# Only register if not already registered
when: "registry.existing_app_id == ''"

# Only run during a reconcile event
when: "reconcile.event_type == 'capability_changed'"

# Combine both conditions
when: "registry.prowlarr_api_key != '' and registry.existing_app_id == ''"
```

---

### 3.5 Template expressions

Any string param value (URL, body, header, message, registry value) can embed context variables using double angle-bracket syntax:

```
<<namespace.dotpath>>
```

Examples:

```yaml
url: "http://<<registry.prowlarr_url_internal>>/api/v1/applications"
value: "<<registry_context.prowlarr_real_api_key>>"
message: "Registered with app ID <<registry_context.radarr_prowlarr_app_id>>"
body: >-
  {"apiKey":"<<registry.radarr_api_key>>","baseUrl":"http://radarr:<<inputs.web_ui_port>>"}
```

If a path cannot be resolved, an empty string is substituted. Expressions in `registry_write.key` are not allowed — the key must be a literal.

---

### 3.6 Context namespaces

The step context is a nested dictionary built from several sources:

| Namespace | Contents | Example |
|-----------|----------|---------|
| `registry` | All values read via `registry_read` steps in this hook run | `<<registry.prowlarr_api_key>>` |
| `registry_context` | Values bound via `bind_as` from `file_read`, `registry_read`, or `bind_response_json` | `<<registry_context.prowlarr_real_api_key>>` |
| `inputs` | The app's resolved config values (from config_schema) | `<<inputs.web_ui_port>>` |
| `app` | App metadata | `<<app.slug>>`, `<<app.id>>` |
| `reconcile` | Reconcile event metadata (only populated during reconcile runs) | `<<reconcile.event_type>>`, `<<reconcile.provider_slug>>` |

**Practical note**: `registry_read` steps bind into `registry.<bind_as>`. `file_read` and `bind_response_json` bind into `registry_context.<bind_as>`. Use `inputs.<field_id>` to reference the app's own config values (e.g., the user-chosen port number).

---

## 4. Actions Reference

Actions are defined in `actions.yaml` alongside `template.yaml`. They represent on-demand or post-install operations that create resources in the app (e.g., adding indexers to Prowlarr, creating download clients in Radarr).

```yaml
actions:
  - id: add_indexer
    label: Add Indexer
    description: Add a search indexer to Prowlarr
    method: POST
    url_template: "http://<<registry.prowlarr_url_external>>/api/v1/indexer"
    headers:
      Content-Type: application/json
      X-Api-Key: "<<registry.prowlarr_api_key>>"
    idempotency_check:
      url_template: "http://<<registry.prowlarr_url_external>>/api/v1/indexer"
      headers:
        X-Api-Key: "<<registry.prowlarr_api_key>>"
      match_field: definitionName
    variants:
      - id: yts
        label: YTS
        description: HD movies, compact file sizes
        idempotency_value: yts
        body_template: >-
          {"name":"<<field.name>>","enable":<<field.enable>>,...}
        fields:
          - id: name
            label: Name
            type: text
            default: YTS
          - id: enable
            label: Enabled
            type: boolean
            default: "true"
```

### 4.1 Action fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Unique action identifier within the template. |
| `label` | string | yes | Human-readable label shown in the wizard. |
| `description` | string | no | Short description of what this action does. |
| `method` | string | yes | HTTP method: `POST`, `PUT`, `DELETE`, `GET`. |
| `url_template` | string | yes | Target URL. Supports `<<registry.key>>` and `<<field.id>>` expressions. |
| `headers` | object | no | Request headers. Values support template expressions. |
| `idempotency_check` | object | no | Configuration for checking if the resource already exists. |
| `variants` | list | yes | One or more variants (e.g., specific indexers). |

#### idempotency_check

```yaml
idempotency_check:
  url_template: "http://<<registry.prowlarr_url_external>>/api/v1/indexer"
  headers:
    X-Api-Key: "<<registry.prowlarr_api_key>>"
  match_field: definitionName
```

| Field | Required | Description |
|-------|----------|-------------|
| `url_template` | yes | URL to GET for the idempotency check. |
| `headers` | no | Headers for the GET request. |
| `match_field` | yes | JSON field in each list item to compare against `idempotency_value`. |

Before executing an action, the executor performs a GET to `url_template`, parses the JSON response as a list, and searches for an item where `match_field == variant.idempotency_value`. If found, the action is skipped with SKIPPED status.

---

### 4.2 Variant fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Unique identifier within the action. |
| `label` | string | yes | Human-readable variant name shown in the wizard. |
| `description` | string | no | Short description. |
| `idempotency_value` | string | no | Value compared against `idempotency_check.match_field`. Required for idempotency to work. |
| `enabled_by_default` | bool | no | If `true`, this variant is pre-selected in the install wizard for new installs. Ignored when editing an existing app. |
| `body_template` | string | yes | Request body. Supports `<<field.id>>` and `<<registry.key>>` expressions. |
| `fields` | list | yes | User-configurable fields for this variant. |

#### enabled_by_default

Setting `enabled_by_default: true` on a variant causes it to appear pre-checked (with default field values populated) when a user opens the install wizard for the first time. The user can remove it before proceeding. This flag has no effect when re-opening an app that is already in the queue (editing mode).

---

### 4.3 Field types

Action fields are the per-variant inputs users fill in before the action runs.

```yaml
fields:
  - id: name
    label: Name
    type: text
    default: YTS

  - id: enable
    label: Enabled
    type: boolean
    default: "true"

  - id: priority
    label: Priority
    type: number
    default: "25"
    visibility: advanced

  - id: baseUrl
    label: Base URL
    type: select
    options:
      - https://yts.bz/
      - https://yts.proxyninja.org/
    allow_custom: true
    default: https://yts.bz/
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Field identifier. Referenced in `body_template` as `<<field.id>>`. |
| `label` | string | yes | Human-readable label. |
| `type` | string | yes | `text`, `boolean`, `number`, or `select`. |
| `default` | string | yes | Default value (always a string, even for boolean/number). |
| `options` | list | no | For `type: select` — the enumerated choices. |
| `allow_custom` | bool | no | For `type: select` — whether the user can type a custom value. Default `false`. |
| `visibility` | string | no | `visible` (default) or `advanced`. Advanced fields are hidden behind a toggle. |

In `body_template`, reference field values as `<<field.<id>>>`. Note that boolean and number values are interpolated as their raw string (e.g., `true` or `25`), so place them without surrounding quotes in JSON bodies:

```yaml
body_template: >-
  {"enable":<<field.enable>>,"priority":<<field.priority>>,"name":"<<field.name>>"}
```

---

### 4.4 Idempotency

Actions are designed to be re-run safely. When an idempotency check is configured:

1. The executor performs a GET to `idempotency_check.url_template`.
2. The response is parsed as a JSON array.
3. Each item is searched for `match_field == idempotency_value`.
4. If a match is found, the action is recorded as SKIPPED — no HTTP request is made.

This means running the same action twice does not create duplicate resources.

---

## 5. The Registry

The registry is a shared key-value store. It is the backbone of cross-app integration.

**Writing**: Only hooks can write to the registry, via `registry_write` steps. A hook may only write keys that start with its own template's slug. Writing a key increments its `capability_version`, which triggers reconcile jobs for all consumers.

**Reading**: Hooks read registry values via `registry_read` steps. Actions read registry values directly via `<<registry.key>>` expressions in their URL and body templates (no explicit read step required for actions).

**Key naming**: Always `<slug>.<capability_name>`. Use dots to organize:
- `prowlarr.api_key`
- `prowlarr.url_internal`
- `prowlarr.url_external`
- `radarr.prowlarr_app_id`

**Sensitive values**: Mark capabilities as `sensitive: true` in `provides` to prevent them from being surfaced in logs. The registry stores them regardless — sensitivity is a display hint.

**Version tracking**: Every write increments `capability_version`. Consumers track `last_seen_versions` in their `reconcile_state`. If a consumer's last-seen version for a key is behind the current version, a reconcile job is enqueued.

---

## 6. Reconciliation

Reconciliation is the mechanism that keeps integrated apps in sync when capabilities change.

**Trigger**: A `registry_write` step completes. The system checks all installed apps whose `consumes` list includes the written key. For each, an event is recorded and a reconcile job is enqueued.

**Execution**: The consumer's `post_install` hook runs again, this time with `is_reconcile: true`. The hook re-reads all registry values (which now include the updated value) and re-runs any integration steps.

**Loop prevention**: The `is_reconcile: true` flag is available as `<<reconcile.event_type>>` in the hook context. If your `post_install` hook itself writes to the registry (which it should, to publish its own capabilities), the reconciler does not cascade — reconcile jobs do not trigger further reconcile jobs.

**Event types**:
- `capability_published` — a capability key was written for the first time.
- `capability_changed` — an existing capability key was updated.
- `provider_removed` — an app that provided consumed capabilities was removed.

**`when:` guard for reconcile idempotency**:

The most important pattern in consumer hooks is guarding the integration step so it only runs once:

```yaml
- id: read_existing_app_id
  type: registry_read
  params:
    key: radarr.prowlarr_app_id
    bind_as: existing_prowlarr_app_id
  on_error: continue

- id: register_with_prowlarr
  type: http_request
  depends_on: [read_existing_app_id, read_prowlarr_key]
  when: "registry.prowlarr_api_key != '' and registry.existing_prowlarr_app_id == ''"
  ...
```

This pattern reads the stored app ID before attempting registration, then skips registration if an ID already exists. On a reconcile triggered by a Prowlarr API key rotation, the hook re-runs but skips re-registration because the app is already registered.

---

## 7. Validation Rules

The hook validator runs at template sync time and at job dispatch time. Violations at sync time prevent ingestion. Violations at dispatch time are surfaced in the job log.

### Error-level rules (block ingestion)

- YAML is syntactically valid.
- All steps have unique `id` values.
- All steps have both `id` and `type`.
- All `depends_on` references point to existing step IDs.
- No dependency cycles exist in the DAG.
- `when:` expressions use valid grammar (no Jinja, no `or`, no numeric comparisons).
- `registry_write` keys start with the template's slug.
- `registry_write` keys contain no template expressions.

### Warning-level rules (accepted with advisory)

- `compose_command` steps with no `when:` guard and no explicit `critical: true`.
- Steps using `on_error: continue` with no explicit `critical` flag.
- Steps depending on a conditionally-skippable dependency (the downstream step may never run).

### Info-level rules (advisory only)

- Steps with no explicit `timeout_seconds`.

---

## 8. Complete Examples

### Example: Simple provider (Prowlarr)

**`prowlarr/template.yaml`** (abridged):

```yaml
schema_version: 2

app:
  id: prowlarr
  name: Prowlarr
  version: "1.0.1"
  flavor: linuxserver

services:
  - id: prowlarr
    image:
      repository: lscr.io/linuxserver/prowlarr
      tag: 2.4.0.5397-ls149
    networking:
      ports:
        - id: web_ui
          listen_port: 9696
          protocol: http
          reachability: external
    storage:
      - id: config
        container_path: /config
        persistence: persistent
        propagation: private
        mutability: read-write
        durability: configuration
    lifecycle:
      restart:
        behavior: persistent

config_schema:
  - id: web_ui_port
    label: Web UI Port
    type: port
    default: 9696
    binds_to: services.prowlarr.ports.web_ui.published_port
    required: false
    visibility: visible
    source: user

  - id: config_path
    label: Config Path
    type: storage_path
    default: ./config
    binds_to: services.prowlarr.storage.config.host_path
    required: false
    visibility: visible
    source: user

  - id: web_ui_port_env
    label: Web UI Port (env)
    type: port
    default: 9696
    binds_to: services.prowlarr.env.PROWLARR__SERVER__PORT
    required: false
    visibility: hidden
    source: platform

provides:
  - key: prowlarr.api_key
    type: credential
    sensitive: true
    rotates: true
  - key: prowlarr.url_internal
    type: endpoint
    sensitive: false
    rotates: false
  - key: prowlarr.url_external
    type: endpoint
    sensitive: false
    rotates: false

hooks:
  post_install: hooks/post_install.yaml
  pre_remove:   hooks/pre_remove.yaml
```

**`prowlarr/hooks/post_install.yaml`**:

```yaml
steps:
  - id: wait_for_config
    type: wait_for_file
    params:
      path: /host-compose/prowlarr/config/config.xml
      poll_interval_seconds: 5
      timeout_seconds: 180

  - id: read_api_key
    type: file_read
    depends_on: [wait_for_config]
    params:
      path: /host-compose/prowlarr/config/config.xml
      regex: '<ApiKey>(.*?)</ApiKey>'
      bind_as: prowlarr_real_api_key

  - id: publish_api_key
    type: registry_write
    depends_on: [read_api_key]
    params:
      key: prowlarr.api_key
      value: "<<registry_context.prowlarr_real_api_key>>"

  - id: publish_url_internal
    type: registry_write
    depends_on: [publish_api_key]
    params:
      key: prowlarr.url_internal
      value: "prowlarr:9696"

  - id: publish_url_external
    type: registry_write
    depends_on: [publish_api_key]
    params:
      key: prowlarr.url_external
      value: "host.docker.internal:<<inputs.web_ui_port>>"
```

**`prowlarr/hooks/pre_remove.yaml`**:

```yaml
steps:
  - id: log_removing
    type: log
    params:
      message: "Prowlarr removing — consumers will self-deregister via reconcile"
```

---

### Example: Consumer with reconcile-safe registration (Radarr)

**`radarr/hooks/post_install.yaml`** (key steps only):

```yaml
steps:
  # Phase 1: Publish own capabilities
  - id: wait_for_config
    type: wait_for_file
    params:
      path: /host-compose/radarr/config/config.xml
      poll_interval_seconds: 5
      timeout_seconds: 180

  - id: read_self_api_key
    type: file_read
    depends_on: [wait_for_config]
    params:
      path: /host-compose/radarr/config/config.xml
      regex: '<ApiKey>(.*?)</ApiKey>'
      bind_as: radarr_self_api_key

  - id: publish_self_api_key
    type: registry_write
    depends_on: [read_self_api_key]
    params:
      key: radarr.api_key
      value: "<<registry_context.radarr_self_api_key>>"

  - id: publish_self_url_internal
    type: registry_write
    depends_on: [publish_self_api_key]
    params:
      key: radarr.url_internal
      value: "radarr:7878"

  - id: publish_self_url_external
    type: registry_write
    depends_on: [publish_self_api_key]
    params:
      key: radarr.url_external
      value: "host.docker.internal:<<inputs.web_ui_port>>"

  # Phase 2: Register with Prowlarr (idempotent)
  - id: read_existing_app_id
    type: registry_read
    depends_on: [publish_self_url_external]
    on_error: continue
    params:
      key: radarr.prowlarr_app_id
      bind_as: existing_prowlarr_app_id

  - id: read_prowlarr_api_key
    type: registry_read
    depends_on: [read_existing_app_id]
    on_error: continue
    params:
      key: prowlarr.api_key
      bind_as: prowlarr_api_key

  - id: read_prowlarr_url_internal
    type: registry_read
    depends_on: [read_prowlarr_api_key]
    on_error: continue
    params:
      key: prowlarr.url_internal
      bind_as: prowlarr_url_internal

  - id: register_with_prowlarr
    type: http_request
    depends_on: [read_prowlarr_api_key, read_prowlarr_url_internal]
    when: "registry.prowlarr_api_key != '' and registry.existing_prowlarr_app_id == ''"
    on_error: continue
    params:
      method: POST
      url: "http://<<registry.prowlarr_url_internal>>/api/v1/applications"
      headers:
        Content-Type: application/json
        X-Api-Key: "<<registry.prowlarr_api_key>>"
      body: >-
        {"name":"Radarr","syncLevel":"fullSync","appProfileId":1,
         "prowlarrUrl":"http://prowlarr:9696",
         "baseUrl":"http://radarr:7878",
         "apiKey":"<<registry.radarr_api_key>>",
         "syncCategories":[2000,2010,2020,2030,2040,2050,2060,2070,2080]}
      bind_response_json: id
      bind_as: radarr_prowlarr_app_id

  - id: store_app_id
    type: registry_write
    depends_on: [register_with_prowlarr]
    when: "registry.radarr_prowlarr_app_id != ''"
    params:
      key: radarr.prowlarr_app_id
      value: "<<registry_context.radarr_prowlarr_app_id>>"
```

**`radarr/hooks/pre_remove.yaml`**:

```yaml
steps:
  - id: read_prowlarr_api_key
    type: registry_read
    on_error: continue
    params:
      key: prowlarr.api_key
      bind_as: prowlarr_api_key

  - id: read_prowlarr_url
    type: registry_read
    depends_on: [read_prowlarr_api_key]
    on_error: continue
    params:
      key: prowlarr.url_external
      bind_as: prowlarr_url_external

  - id: read_app_id
    type: registry_read
    depends_on: [read_prowlarr_url]
    on_error: continue
    params:
      key: radarr.prowlarr_app_id
      bind_as: existing_app_id

  - id: deregister_from_prowlarr
    type: http_request
    depends_on: [read_app_id]
    when: "registry.existing_app_id != ''"
    on_error: continue
    params:
      method: DELETE
      url: "http://<<registry.prowlarr_url_external>>/api/v1/applications/<<registry.existing_app_id>>"
      headers:
        X-Api-Key: "<<registry.prowlarr_api_key>>"
```

---

### Example: Actions (Prowlarr indexers)

**`prowlarr/actions.yaml`**:

```yaml
actions:
  - id: add_indexer
    label: Add Indexer
    description: Add a search indexer to Prowlarr
    method: POST
    url_template: "http://<<registry.prowlarr_url_external>>/api/v1/indexer"
    headers:
      Content-Type: application/json
      X-Api-Key: "<<registry.prowlarr_api_key>>"
    idempotency_check:
      url_template: "http://<<registry.prowlarr_url_external>>/api/v1/indexer"
      headers:
        X-Api-Key: "<<registry.prowlarr_api_key>>"
      match_field: definitionName
    variants:
      - id: nyaasi
        label: Nyaa.si
        description: Anime and manga torrents
        idempotency_value: nyaasi
        enabled_by_default: true
        body_template: >-
          {"name":"<<field.name>>","enable":<<field.enable>>,"priority":<<field.priority>>,
           "appProfileId":1,"protocol":"torrent","privacy":"public","tags":[],
           "definitionName":"nyaasi","implementationName":"Cardigann",
           "implementation":"Cardigann","configContract":"CardigannSettings",
           "fields":[{"name":"definitionFile","value":"nyaasi"},
                     {"name":"baseUrl","value":"<<field.baseUrl>>"}]}
        fields:
          - id: name
            label: Name
            type: text
            default: Nyaa.si
          - id: enable
            label: Enabled
            type: boolean
            default: "true"
          - id: baseUrl
            label: Base URL
            type: text
            default: https://nyaa.si/
          - id: priority
            label: Priority
            type: number
            default: "25"
            visibility: advanced

      - id: yts
        label: YTS
        description: HD movies, compact file sizes
        idempotency_value: yts
        body_template: >-
          {"name":"<<field.name>>","enable":<<field.enable>>,"priority":<<field.priority>>,
           "appProfileId":1,"protocol":"torrent","privacy":"public","tags":[],
           "definitionName":"yts","implementationName":"Cardigann",
           "fields":[{"name":"definitionFile","value":"yts"},
                     {"name":"baseUrl","value":"<<field.baseUrl>>"},
                     {"name":"torrentBaseSettings.preferMagnetUrl","value":<<field.preferMagnetUrl>>}]}
        fields:
          - id: name
            label: Name
            type: text
            default: YTS
          - id: enable
            label: Enabled
            type: boolean
            default: "true"
          - id: baseUrl
            label: Base URL
            type: select
            options:
              - https://yts.bz/
              - https://yts.proxyninja.org/
            allow_custom: true
            default: https://yts.bz/
          - id: priority
            label: Priority
            type: number
            default: "25"
            visibility: advanced
          - id: preferMagnetUrl
            label: Prefer Magnet URL
            type: boolean
            default: "false"
            visibility: advanced
```

---

## 9. Design Patterns

### Graceful degradation

Consumer hooks should always use `on_error: continue` on every step that touches a provider's registry. This allows the consumer to install successfully even when the provider is absent. The job will be marked as degraded rather than failed.

```yaml
- id: read_prowlarr_key
  type: registry_read
  on_error: continue      # don't block install if Prowlarr isn't there yet
  params:
    key: prowlarr.api_key
    bind_as: prowlarr_api_key
```

### Idempotent registration

Always read a stored ID before attempting to create a resource. Guard the creation step with a `when:` condition that checks the ID is empty.

```yaml
- id: read_existing_id
  type: registry_read
  on_error: continue
  params:
    key: myapp.provider_resource_id
    bind_as: existing_id

- id: create_resource
  type: http_request
  depends_on: [read_existing_id]
  when: "registry.existing_id == ''"   # skip if already registered
  ...
```

### Publishing capabilities immediately

A provider app should publish its capabilities as early as possible in `post_install`. This allows consumers to receive their reconcile jobs sooner. Publish self-keys before attempting any outbound integration.

### Safe removal

All steps in `pre_remove` should use `on_error: continue`. Removal must never be blocked by an unavailable dependency. A failed deregistration is a minor inconvenience; a stuck removal blocks the whole stack.

### Using host paths in hooks

Config field values for storage paths are available as `<<inputs.<field_id>>>`. However, hook file paths must be computed at YAML-write time using the pattern:

```
/host-compose/<slug>/relative/path
```

Where `/host-compose` is the container-side mount of the compose base directory. The actual host path is resolved by the ECB pipeline; hooks reference the container-side view.

### Versioning your template

Increment `app.version` when you change anything in `template.yaml` or its hooks. Template versions are immutable — you cannot modify a published version. Use semantic versioning: `1.0.0` → `1.0.1` for patches, `1.1.0` for new features, `2.0.0` for breaking changes.
