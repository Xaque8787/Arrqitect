"""
Platform Template models — schema_version 2.

These models represent parsed, validated template intent.
They contain zero Docker Compose concepts. If a field only
exists because Compose exists, it does not belong here.
"""

from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, field_validator


class RestartModel(BaseModel):
    behavior: Literal["persistent", "on-failure", "never"] = "persistent"


class LifecycleModel(BaseModel):
    restart: RestartModel = RestartModel()


class StorageModel(BaseModel):
    id: str
    persistence: Literal["persistent", "ephemeral"]
    propagation: Literal["private", "shared", "slave", "rslave"] = "private"
    mutability: Literal["read-write", "read-only"]
    durability: Literal["configuration", "user-data", "transient", "model-store"]
    container_path: str


class PortModel(BaseModel):
    id: str
    listen_port: int
    protocol: Literal["http", "https", "tcp", "udp"]
    reachability: Literal["external", "internal", "none"]


class NetworkingModel(BaseModel):
    ports: list[PortModel] = []


class ImageModel(BaseModel):
    repository: str
    tag: str = "latest"


class ServiceModel(BaseModel):
    id: str
    image: ImageModel
    networking: NetworkingModel = NetworkingModel()
    storage: list[StorageModel] = []
    lifecycle: LifecycleModel = LifecycleModel()

    @field_validator("storage")
    @classmethod
    def storage_ids_unique(cls, v: list) -> list:
        ids = [s.id for s in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Storage mount ids must be unique within a service")
        return v


class CapabilityProvides(BaseModel):
    key: str
    type: Literal["credential", "endpoint", "metadata", "feature-flag"] = "metadata"
    sensitive: bool = False
    rotates: bool = False


class CapabilityConsumes(BaseModel):
    key: str
    required: bool = False
    connectivity: bool = False


class ConfigField(BaseModel):
    id: str
    label: str
    type: Literal["port", "storage_path", "string", "number", "boolean"]
    default: str | int | bool | None = None
    placeholder: str | None = None
    binds_to: str
    required: bool = False
    visibility: Literal["visible", "advanced", "hidden"] = "visible"
    source: Literal["user", "platform", "derived"] = "user"
    allowed_values: list[str] | None = None
    ui_widget: Literal["input", "select"] = "input"


class AppModel(BaseModel):
    id: str
    name: str
    version: str
    flavor: Literal["linuxserver", "generic"] = "generic"


class TemplateModel(BaseModel):
    schema_version: Literal[2]
    app: AppModel
    services: list[ServiceModel]
    provides: list[CapabilityProvides] = []
    consumes: list[CapabilityConsumes] = []
    config_schema: list[ConfigField] = []
    hooks: dict[str, str] = {}

    @field_validator("services")
    @classmethod
    def at_least_one_service(cls, v: list) -> list:
        if not v:
            raise ValueError("Template must define at least one service")
        return v
