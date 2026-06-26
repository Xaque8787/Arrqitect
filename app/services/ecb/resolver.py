"""
ECB Stages 2-5: Pure resolution functions.

Each function is a pure transformation — no I/O, no side effects.
They take parsed template models and contextual data, and return
typed IR sub-models.
"""

from __future__ import annotations
import os
import subprocess
import json
from pathlib import Path

from app.models.template import TemplateModel, ServiceModel, StorageModel, ConfigField
from app.models.ir import StorageMountIR, MountPropagationIR, PortIR, EnvVarIR, LifecycleIR, HealthcheckIR

CONTAINER_COMPOSE_DIR = "/compose"

# Template layer → IR intent. Docker terms never appear here.
_PROPAGATION_INTENT = {
    "private": "none",
    "shared": "bidirectional-nonrecursive",
    "rshared": "bidirectional",
    "slave": "host-to-container-nonrecursive",
    "rslave": "host-to-container",
}

GLOBAL_ENV_MAP = {
    "puid": ("PUID", "global"),
    "pgid": ("PGID", "global"),
    "timezone": ("TZ", "global"),
}


def get_compose_base() -> str:
    env_override = os.environ.get("HOST_COMPOSE_DIR", "")
    if env_override:
        return env_override
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{json .Mounts}}", "arrqitect"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            mounts = json.loads(result.stdout)
            mount = next(
                (m for m in mounts if m.get("Destination") == "/compose"), None
            )
            if mount and mount.get("Source"):
                return mount["Source"]
    except Exception:
        pass
    return CONTAINER_COMPOSE_DIR


def resolve_host_path(raw_path: str, app_slug: str, compose_base: str) -> str:
    p = Path(raw_path)
    if p.is_absolute():
        return str(p)
    parts = p.parts
    if parts and parts[0] == ".":
        p = Path(*parts[1:]) if len(parts) > 1 else Path("")
    return str(Path(compose_base) / app_slug / p)


def resolve_config(template: TemplateModel, user_config: dict) -> dict[str, str]:
    """
    Merge user-supplied config with schema defaults.
    Returns a flat dict of config_field_id -> resolved string value.
    """
    resolved: dict[str, str] = {}
    for field in template.config_schema:
        raw = user_config.get(field.id)
        if raw is None:
            raw = field.default
        resolved[field.id] = str(raw) if raw is not None else ""
    return resolved


def resolve_storage(
    service: ServiceModel,
    resolved_config: dict[str, str],
    app_slug: str,
    compose_base: str,
    config_schema: list[ConfigField],
) -> list[StorageMountIR]:
    """
    Resolve storage declarations into StorageMountIR list.
    Finds the config field that binds to each storage mount to get the host path.
    """
    mounts: list[StorageMountIR] = []

    for storage in service.storage:
        dotpath_prefix = f"services.{service.id}.storage.{storage.id}"

        # host_path: ConfigField binding → compose_base fallback
        host_path = _find_bound_value(
            dotpath_prefix + ".host_path",
            config_schema,
            resolved_config,
        )
        if host_path is None:
            host_path = str(Path(compose_base) / app_slug / storage.id)
        else:
            host_path = resolve_host_path(host_path, app_slug, compose_base)

        # propagation: ConfigField override → template default → safe fallback ("none")
        prop_override = _find_bound_value(
            dotpath_prefix + ".propagation",
            config_schema,
            resolved_config,
        )
        prop_template = prop_override if prop_override else storage.propagation
        prop_mode = _PROPAGATION_INTENT.get(prop_template, "none")

        mounts.append(StorageMountIR(
            id=storage.id,
            host_path=host_path,
            container_path=storage.container_path,
            persistence=storage.persistence,
            propagation=MountPropagationIR(mode=prop_mode),
            mutability=storage.mutability,
            durability=storage.durability,
        ))

    return mounts


def resolve_ports(
    service: ServiceModel,
    resolved_config: dict[str, str],
    config_schema: list[ConfigField],
) -> list[PortIR]:
    """
    Resolve port declarations into PortIR list.
    Published port comes from the config field that binds to it.
    """
    ports: list[PortIR] = []

    for port in service.networking.ports:
        dotpath = f"services.{service.id}.networking.ports.{port.id}.published_port"
        published_raw = _find_bound_value(dotpath, config_schema, resolved_config)

        if published_raw is not None:
            try:
                published_port = int(published_raw)
            except (ValueError, TypeError):
                published_port = port.listen_port
        else:
            published_port = port.listen_port

        ports.append(PortIR(
            id=port.id,
            listen_port=port.listen_port,
            published_port=published_port,
            protocol=port.protocol,
            reachability=port.reachability,
        ))

    return ports


def resolve_env_vars(
    service: ServiceModel,
    resolved_config: dict[str, str],
    global_settings: dict[str, str],
    registry_entries: list[dict],
    config_schema: list[ConfigField],
    app_slug: str,
    flavor: str,
) -> list[EnvVarIR]:
    """
    Build the complete env var list for a service with full provenance tagging.

    Env vars are emitted only when a config field's binds_to targets
    services.<service_id>.env.<ENV_KEY>. The env var name is extracted
    from the dotpath itself — no guessing from field type or id.

    Order: global → user_config → registry
    """
    env_vars: list[EnvVarIR] = []
    env_prefix = f"services.{service.id}.env."

    # Global vars — injected for linuxserver flavor
    if flavor == "linuxserver":
        for setting_key, (env_name, _source) in GLOBAL_ENV_MAP.items():
            env_vars.append(EnvVarIR(
                name=env_name,
                value=str(global_settings.get(setting_key, _global_default(setting_key))),
                source="global",
                source_key=setting_key,
            ))

    # User config vars — only fields whose binds_to targets an env var dotpath
    for field in config_schema:
        if not field.binds_to or not field.binds_to.startswith(env_prefix):
            continue
        env_name = field.binds_to[len(env_prefix):]
        if not env_name:
            continue
        value = resolved_config.get(field.id, "")
        if value:
            env_vars.append(EnvVarIR(
                name=env_name,
                value=value,
                source="user_config",
                source_key=field.id,
            ))

    # Registry vars — values from consumed capabilities
    for entry in registry_entries:
        env_name = _registry_key_to_env_name(entry["key"])
        env_vars.append(EnvVarIR(
            name=env_name,
            value=entry["value"],
            source="registry",
            source_key=entry["key"],
        ))

    return env_vars


def resolve_custom_storage(
    custom_entries: list[dict],
    app_slug: str,
    compose_base: str,
    existing_ids: set[str],
) -> list[StorageMountIR]:
    """
    Compile user-defined custom mount rows into StorageMountIR objects.
    Each entry must have host_path, container_path; propagation and mutability
    are optional and default to "private" / "read-write".
    IDs are generated as custom-storage-N and validated against existing_ids.
    """
    mounts: list[StorageMountIR] = []
    for i, entry in enumerate(custom_entries, start=1):
        host_path = entry.get("host_path", "").strip()
        container_path = entry.get("container_path", "").strip()
        if not host_path or not container_path:
            continue

        mount_id = f"custom-storage-{i}"
        if mount_id in existing_ids:
            # collision guard — skip rather than corrupt; compiler validates further
            continue

        host_path = resolve_host_path(host_path, app_slug, compose_base)
        prop_template = entry.get("propagation", "private")
        prop_mode = _PROPAGATION_INTENT.get(prop_template, "none")
        mutability = entry.get("mutability", "read-write")
        if mutability not in ("read-write", "read-only"):
            mutability = "read-write"

        mounts.append(StorageMountIR(
            id=mount_id,
            host_path=host_path,
            container_path=container_path,
            persistence="persistent",
            propagation=MountPropagationIR(mode=prop_mode),
            mutability=mutability,
            durability="user-data",
            is_custom=True,
        ))

    return mounts


def resolve_custom_env(custom_entries: list[dict]) -> list[EnvVarIR]:
    """
    Compile user-defined custom env var rows into EnvVarIR objects.
    Each entry must have key and value. Empty keys are skipped.
    Ordering is preserved; last-write-wins dedup is handled in the compiler.
    """
    env_vars: list[EnvVarIR] = []
    for entry in custom_entries:
        key = entry.get("key", "").strip()
        value = entry.get("value", "")
        if not key:
            continue
        env_vars.append(EnvVarIR(
            name=key,
            value=value,
            source="user_config",
            source_key=None,
            is_custom=True,
        ))
    return env_vars


def resolve_runtime_constraints(service: ServiceModel) -> tuple[list[str], str]:
    return list(service.required_devices), service.mac_policy


def resolve_lifecycle(service: ServiceModel) -> LifecycleIR:
    healthcheck: HealthcheckIR | None = None
    if service.lifecycle.healthcheck is not None:
        hc = service.lifecycle.healthcheck
        healthcheck = HealthcheckIR(
            type=hc.test.type,
            command=hc.test.command,
            interval=hc.interval,
            timeout=hc.timeout,
            retries=hc.retries,
            start_period=hc.start_period,
        )
    return LifecycleIR(
        restart_behavior=service.lifecycle.restart.behavior,
        init_process=service.lifecycle.init_process,
        healthcheck=healthcheck,
    )


# --- internal helpers ---

def _find_bound_value(
    dotpath: str,
    config_schema: list[ConfigField],
    resolved_config: dict[str, str],
) -> str | None:
    for field in config_schema:
        if field.binds_to == dotpath:
            return resolved_config.get(field.id)
    return None


def _global_default(key: str) -> str:
    defaults = {"puid": "1000", "pgid": "1000", "timezone": "Etc/UTC"}
    return defaults.get(key, "")


def _registry_key_to_env_name(registry_key: str) -> str:
    return registry_key.upper().replace(".", "_").replace("-", "_")
