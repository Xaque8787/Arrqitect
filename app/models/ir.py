"""
Platform IR models — renderer-agnostic desired state.

These models represent the fully compiled, resolved desired state
of an application. They contain zero Docker Compose concepts.
Terms like 'rprivate', 'unless-stopped', 'mode: host' do not
appear here — those are renderer decisions.
"""

from __future__ import annotations
from typing import Literal
from pydantic import BaseModel


class MountPropagationIR(BaseModel):
    mode: Literal["none", "bidirectional", "host-to-container", "container-to-host"] = "none"


class StorageMountIR(BaseModel):
    id: str
    host_path: str                   # resolved absolute path
    container_path: str
    persistence: Literal["persistent", "ephemeral"]
    propagation: MountPropagationIR = MountPropagationIR()
    mutability: Literal["read-write", "read-only"]
    durability: str
    is_custom: bool = False


class PortIR(BaseModel):
    id: str
    listen_port: int
    published_port: int              # resolved from config
    protocol: Literal["http", "https", "tcp", "udp"]
    reachability: Literal["external", "internal", "none"]


class EnvVarIR(BaseModel):
    name: str
    value: str
    source: Literal["global", "user_config", "registry", "derived"]
    source_key: str | None = None    # provenance: which config field or registry key
    is_custom: bool = False


class LifecycleIR(BaseModel):
    restart_behavior: Literal["persistent", "on-failure", "never"]


class NetworkMembershipIR(BaseModel):
    network_id: str
    aliases: list[str] = []


class ServiceIR(BaseModel):
    id: str
    image_repository: str
    image_tag: str
    env_vars: list[EnvVarIR]
    storage: list[StorageMountIR]
    ports: list[PortIR]
    networks: list[NetworkMembershipIR]
    lifecycle: LifecycleIR


class NetworkIR(BaseModel):
    id: str
    scope: Literal["platform-internal", "capability-shared", "external"]


class AppIR(BaseModel):
    app_id: str
    slug: str
    services: list[ServiceIR]
    networks: dict[str, NetworkIR]
    ir_hash: str = ""                # set by compiler after assembly
