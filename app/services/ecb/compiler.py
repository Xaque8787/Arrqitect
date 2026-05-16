"""
ECB Stage 7: IR assembly and hashing.

compile_app() is the public entry point for the ECB pipeline.
It calls all resolution stages and assembles the final AppIR,
then computes an ir_hash over the canonical serialization.
"""

from __future__ import annotations
import hashlib

from app.models.template import TemplateModel
from app.models.ir import AppIR, ServiceIR
from app.services.ecb.resolver import (
    get_compose_base,
    resolve_config,
    resolve_storage,
    resolve_ports,
    resolve_env_vars,
    resolve_custom_storage,
    resolve_custom_env,
    resolve_lifecycle,
)
from app.services.ecb.network import infer_networks


def compile_app(
    template: TemplateModel,
    user_config: dict,
    global_settings: dict,
    registry_entries: list[dict],
    installed_providers: list[dict],
    app_slug: str,
) -> AppIR:
    """
    Compile a TemplateModel into a fully resolved AppIR.

    All stages are pure — no I/O beyond the compose_base detection
    which is handled once at the start.
    """
    compose_base = get_compose_base()
    resolved_config = resolve_config(template, user_config)
    networks, memberships = infer_networks(template, installed_providers)

    services: list[ServiceIR] = []

    custom_storage_entries: list[dict] = user_config.get("custom_storage", []) or []
    custom_env_entries: list[dict] = user_config.get("custom_env", []) or []

    for service_tmpl in template.services:
        storage = resolve_storage(
            service_tmpl,
            resolved_config,
            app_slug,
            compose_base,
            template.config_schema,
        )

        # Compile custom mounts and append — no template-defined ID can collide
        existing_storage_ids = {m.id for m in storage}
        custom_mounts = resolve_custom_storage(
            custom_storage_entries,
            app_slug,
            compose_base,
            existing_storage_ids,
        )

        # Duplicate container path validation — compiler is the right boundary
        all_mounts = storage + custom_mounts
        seen_container_paths: set[str] = set()
        for mount in all_mounts:
            if mount.container_path in seen_container_paths:
                raise ValueError(
                    f"Duplicate container path '{mount.container_path}' in app '{app_slug}'"
                )
            seen_container_paths.add(mount.container_path)

        ports = resolve_ports(
            service_tmpl,
            resolved_config,
            template.config_schema,
        )
        env_vars = resolve_env_vars(
            service_tmpl,
            resolved_config,
            global_settings,
            registry_entries,
            template.config_schema,
            app_slug,
            template.app.flavor,
        )

        # Append custom env vars — last-write-wins by building a name-keyed dict
        custom_env = resolve_custom_env(custom_env_entries)
        env_by_name: dict[str, object] = {e.name: e for e in env_vars}
        for e in custom_env:
            env_by_name[e.name] = e  # custom overrides template env on collision
        merged_env = list(env_by_name.values())

        lifecycle = resolve_lifecycle(service_tmpl)

        services.append(ServiceIR(
            id=service_tmpl.id,
            image_repository=service_tmpl.image.repository,
            image_tag=service_tmpl.image.tag,
            env_vars=merged_env,
            storage=all_mounts,
            ports=ports,
            networks=memberships,
            lifecycle=lifecycle,
        ))

    app_ir = AppIR(
        app_id=template.app.id,
        slug=app_slug,
        services=services,
        networks=networks,
    )

    # Compute hash over canonical JSON — this is the platform's source of truth
    canonical = app_ir.model_dump_json(exclude={"ir_hash"})
    app_ir.ir_hash = hashlib.sha256(canonical.encode()).hexdigest()

    return app_ir
