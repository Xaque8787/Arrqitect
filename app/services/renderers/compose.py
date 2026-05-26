"""
ComposeRenderer — the only file in this codebase that knows Docker Compose syntax.

Two stages:
  Stage 1 — Semantic lowering: IR types -> Compose domain dicts
  Stage 2 — Canonical serialization: deterministic YAML output

Values are embedded directly in compose. No .env substitution.

If you find yourself writing Compose concepts anywhere other than this file,
that is an architecture violation.

Semantic lowering rules:
  lifecycle.restart_behavior:
    persistent  -> "unless-stopped"
    on-failure  -> "on-failure"
    never       -> "no"

  port.reachability:
    external    -> published port mapping (host:container)
    internal    -> no port mapping (accessible on platform network only)
    none        -> port omitted entirely

  storage axes -> bind mount:
    propagation.mode=none               -> propagation: rprivate
    propagation.mode=bidirectional      -> propagation: rshared
    propagation.mode=host-to-container  -> propagation: rslave
    propagation.mode=container-to-host  -> propagation: slave
    persistence=persistent  -> create_host_path: true
    persistence=ephemeral   -> create_host_path: false
    mutability=read-only    -> read_only: true
    mutability=read-write   -> read_only: false

  protocol -> compose port protocol:
    http/https/tcp  -> tcp
    udp             -> udp
"""

from __future__ import annotations
import hashlib
from typing import Any

from app.models.ir import AppIR, ServiceIR, StorageMountIR, PortIR, EnvVarIR, LifecycleIR, NetworkIR

_RESTART_MAP = {
    "persistent": "unless-stopped",
    "on-failure": "on-failure",
    "never": "no",
}

_PROTOCOL_MAP = {
    "http": "tcp",
    "https": "tcp",
    "tcp": "tcp",
    "udp": "udp",
}

_PROPAGATION_MAP = {
    "none": "rprivate",
    "bidirectional": "rshared",
    "host-to-container": "rslave",
    "container-to-host": "slave",
}


class ComposeRenderer:
    def __init__(self, app_ir: AppIR):
        self._ir = app_ir

    def render(self) -> tuple[str, str]:
        """
        Returns (compose_yaml, env_content).
        Values are embedded directly in compose — env_content is always empty.
        Both outputs are deterministic.
        """
        doc = self._build_document()
        compose_yaml = _serialize_canonical(doc)
        return compose_yaml, ""

    def compose_hash(self) -> str:
        compose_yaml, _ = self.render()
        return hashlib.sha256(compose_yaml.encode()).hexdigest()

    # --- Phase 1: Semantic lowering ---

    def _build_document(self) -> dict[str, Any]:
        services: dict[str, Any] = {}
        for svc in sorted(self._ir.services, key=lambda s: s.id):
            services[svc.id] = self._emit_service(svc)

        networks: dict[str, Any] = {}
        for net_id in sorted(self._ir.networks):
            networks[net_id] = self._emit_network(self._ir.networks[net_id])

        doc: dict[str, Any] = {"services": services}
        if networks:
            doc["networks"] = networks
        return doc

    def _emit_service(self, svc: ServiceIR) -> dict[str, Any]:
        result: dict[str, Any] = {
            "image": f"{svc.image_repository}:{svc.image_tag}",
        }

        env = self._emit_env(svc.env_vars)
        if env:
            result["environment"] = env

        volumes = [self._emit_volume(m) for m in sorted(svc.storage, key=lambda s: s.id)]
        if volumes:
            result["volumes"] = volumes

        ports = [self._emit_port(p) for p in sorted(svc.ports, key=lambda p: p.listen_port)
                 if p.reachability != "none"]
        if ports:
            result["ports"] = ports

        net_ids = sorted(m.network_id for m in svc.networks)
        if net_ids:
            result["networks"] = net_ids

        result["restart"] = _RESTART_MAP[svc.lifecycle.restart_behavior]

        return result

    def _emit_volume(self, mount: StorageMountIR) -> dict[str, Any]:
        return {
            "type": "bind",
            "source": mount.host_path,
            "target": mount.container_path,
            "read_only": mount.mutability == "read-only",
            "bind": {
                "create_host_path": mount.persistence == "persistent",
                "propagation": _PROPAGATION_MAP[mount.propagation.mode],
            },
        }

    def _emit_port(self, port: PortIR) -> dict[str, Any]:
        if port.reachability == "internal":
            # Internal ports are not published — they are only accessible
            # on the platform network. No host binding.
            return None  # filtered out by caller
        return {
            "target": port.listen_port,
            "published": port.published_port,
            "protocol": _PROTOCOL_MAP[port.protocol],
            "mode": "host",
        }

    def _emit_env(self, env_vars: list[EnvVarIR]) -> list[str]:
        # Order: global first, then user_config alphabetical, then registry, then derived
        order = {"global": 0, "user_config": 1, "registry": 2, "derived": 3}
        sorted_vars = sorted(env_vars, key=lambda e: (order.get(e.source, 9), e.name))
        return [f"{e.name}={e.value}" for e in sorted_vars]

    def _emit_network(self, network: NetworkIR) -> dict[str, Any]:
        if network.scope == "external":
            # `name` pins the exact Docker network name, bypassing compose project-prefix.
            return {"external": True, "name": network.id}
        # `name` pins the owned network name so consumers can reference it exactly.
        return {"driver": "bridge", "name": network.id}


# --- Canonical YAML serializer ---

def _serialize_canonical(doc: dict[str, Any]) -> str:
    """
    Deterministic YAML serialization. Always uses long syntax.
    Does not use yaml.dump() — we control formatting explicitly.
    """
    lines: list[str] = []
    _write_mapping(doc, lines, indent=0)
    return "\n".join(lines) + "\n"


def _write_value(key: str, value: Any, lines: list[str], indent: int) -> None:
    pad = "  " * indent
    if value is None:
        lines.append(f"{pad}{key}:")
    elif isinstance(value, bool):
        lines.append(f"{pad}{key}: {'true' if value else 'false'}")
    elif isinstance(value, (int, float)):
        lines.append(f"{pad}{key}: {value}")
    elif isinstance(value, str):
        if _needs_quotes(value):
            lines.append(f'{pad}{key}: "{_escape(value)}"')
        else:
            lines.append(f"{pad}{key}: {value}")
    elif isinstance(value, dict):
        lines.append(f"{pad}{key}:")
        _write_mapping(value, lines, indent + 1)
    elif isinstance(value, list):
        lines.append(f"{pad}{key}:")
        _write_list(value, lines, indent + 1)


def _write_mapping(d: dict[str, Any], lines: list[str], indent: int) -> None:
    pad = "  " * indent
    for k in d:
        v = d[k]
        if v is None:
            continue
        _write_value(k, v, lines, indent)


def _write_list(lst: list[Any], lines: list[str], indent: int) -> None:
    pad = "  " * indent
    for item in lst:
        if item is None:
            continue
        if isinstance(item, str):
            if _needs_quotes(item):
                lines.append(f'{pad}- "{_escape(item)}"')
            else:
                lines.append(f"{pad}- {item}")
        elif isinstance(item, dict):
            first = True
            for k, v in item.items():
                if v is None:
                    continue
                if first:
                    prefix = f"{pad}- "
                    first = False
                else:
                    prefix = f"{pad}  "
                if isinstance(v, bool):
                    lines.append(f"{prefix}{k}: {'true' if v else 'false'}")
                elif isinstance(v, (int, float)):
                    lines.append(f"{prefix}{k}: {v}")
                elif isinstance(v, str):
                    if _needs_quotes(v):
                        lines.append(f'{prefix}{k}: "{_escape(v)}"')
                    else:
                        lines.append(f"{prefix}{k}: {v}")
                elif isinstance(v, dict):
                    lines.append(f"{prefix}{k}:")
                    _write_mapping(v, lines, indent + 2)
                elif isinstance(v, list):
                    lines.append(f"{prefix}{k}:")
                    _write_list(v, lines, indent + 2)
        else:
            lines.append(f"{pad}- {item}")


def _needs_quotes(s: str) -> bool:
    if not s:
        return True
    # Quote if contains special chars or looks like a number/bool
    special = set(':{}[]|>&*!,#`"\'@%')
    if any(c in special for c in s):
        return True
    lower = s.lower()
    if lower in ("true", "false", "yes", "no", "null", "~"):
        return True
    return False


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')
