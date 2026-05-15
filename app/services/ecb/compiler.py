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

    for service_tmpl in template.services:
        storage = resolve_storage(
            service_tmpl,
            resolved_config,
            app_slug,
            compose_base,
            template.config_schema,
        )
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
        lifecycle = resolve_lifecycle(service_tmpl)

        services.append(ServiceIR(
            id=service_tmpl.id,
            image_repository=service_tmpl.image.repository,
            image_tag=service_tmpl.image.tag,
            env_vars=env_vars,
            storage=storage,
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
